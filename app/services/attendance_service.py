"""
Attendance Domain Service
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from fastapi import status as http_status
from pymongo.errors import DuplicateKeyError

from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.attendance import (
    AttendancePage,
    AttendanceRecord,
    HistoryEntry,
    PunchInRequest,
    PunchOutRequest,
    RegularizeRequest,
)
from app.services.attendance_calculator import (
    compute_half_day,
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
)
from app.utils.datetime_utils import (
    from_epoch_ms,
    get_attendance_date,
    to_epoch_ms,
)


def serialize_history(history_list: Optional[List[Dict[str, Any]]]) -> List[HistoryEntry]:
    if not history_list:
        return []
    result = []
    for h in history_list:
        at_dt = h.get("at")
        at_ms = to_epoch_ms(at_dt) if isinstance(at_dt, datetime) else at_dt
        changes = {}
        for k, v in h.get("changes", {}).items():
            f_val = v.get("from")
            t_val = v.get("to")
            if k in ("punch_in", "punch_out"):
                if isinstance(f_val, datetime):
                    f_val = to_epoch_ms(f_val)
                if isinstance(t_val, datetime):
                    t_val = to_epoch_ms(t_val)
            changes[k] = {"from": f_val, "to": t_val}
        result.append(
            HistoryEntry(
                at=at_ms or 0,
                by=h.get("by", ""),
                reason=h.get("reason", ""),
                changes=changes,
            )
        )
    return result


def serialize_attendance(doc: Dict[str, Any]) -> AttendanceRecord:
    p_in = doc.get("punch_in")
    p_out = doc.get("punch_out")
    return AttendanceRecord(
        emp_code=doc["emp_code"],
        date=doc["date"],
        status=doc["status"],
        punch_in=to_epoch_ms(p_in) if isinstance(p_in, datetime) else p_in,
        punch_out=to_epoch_ms(p_out) if isinstance(p_out, datetime) else p_out,
        work_hours=doc.get("work_hours"),
        late_minutes=doc.get("late_minutes", 0),
        overtime_minutes=doc.get("overtime_minutes", 0),
        half_day=doc.get("half_day", False),
        history=serialize_history(doc.get("history", [])),
    )


class AttendanceService:
    def __init__(
        self,
        att_repo: Optional[AttendanceRepository] = None,
        emp_repo: Optional[EmployeeRepository] = None,
    ):
        self.att_repo = att_repo or AttendanceRepository()
        self.emp_repo = emp_repo or EmployeeRepository()

    def punch_in(self, body: PunchInRequest) -> AttendanceRecord:
        emp = self.emp_repo.get_by_emp_code(body.emp_code)
        if not emp:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )

        if body.punched_at is not None:
            punch_in_utc = from_epoch_ms(body.punched_at)
        else:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            punch_in_utc = from_epoch_ms(now_ms)

        att_date = get_attendance_date(punch_in_utc, emp["shift_start"], emp["shift_end"])
        late_min = compute_late_minutes(punch_in_utc, emp["shift_start"], att_date)

        doc = {
            "emp_code": body.emp_code,
            "date": att_date,
            "status": body.status,
            "punch_in": punch_in_utc,
            "punch_out": None,
            "work_hours": None,
            "late_minutes": late_min,
            "overtime_minutes": 0,
            "half_day": False,
            "history": [],
        }

        try:
            self.att_repo.create_punch_in(doc)
        except DuplicateKeyError:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="already punched in for this date",
            )

        return serialize_attendance(doc)

    def punch_out(self, body: PunchOutRequest) -> AttendanceRecord:
        emp = self.emp_repo.get_by_emp_code(body.emp_code)
        if not emp:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )

        if body.punched_at is not None:
            punch_out_utc = from_epoch_ms(body.punched_at)
        else:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            punch_out_utc = from_epoch_ms(now_ms)

        target_rec = self.att_repo.find_latest_open_record(body.emp_code, punch_out_utc)
        if not target_rec:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="No open punch-in record found",
            )

        if target_rec.get("punch_out") is not None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Record is already punched out",
            )

        punch_in_utc = target_rec["punch_in"]
        diff_sec = (punch_out_utc - punch_in_utc).total_seconds()
        if diff_sec <= 0 or diff_sec > 86400:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="punched_at must be strictly after punch_in and within 24 hours",
            )

        wh = compute_work_hours(punch_in_utc, punch_out_utc)
        ot = compute_overtime(punch_out_utc, emp["shift_start"], emp["shift_end"], target_rec["date"])
        hd = compute_half_day(wh)

        res = self.att_repo.atomic_punch_out(
            record_id=target_rec["_id"],
            punch_out_utc=punch_out_utc,
            work_hours=wh,
            overtime_minutes=ot,
            half_day=hd,
        )
        if res is None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Record was already punched out concurrently",
            )

        return serialize_attendance(res)

    def list_attendance(
        self,
        emp_code: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AttendancePage:
        if date_from and date_to and date_from > date_to:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_from must not be after date_to",
            )

        skip = (page - 1) * page_size
        items_raw, total = self.att_repo.list_attendance(
            emp_code=emp_code,
            date_from=date_from,
            date_to=date_to,
            status=status,
            skip=skip,
            limit=page_size,
        )
        items = [serialize_attendance(d) for d in items_raw]
        return AttendancePage(items=items, total=total, page=page, page_size=page_size)

    def regularize(
        self, emp_code: str, date: str, body: RegularizeRequest
    ) -> AttendanceRecord:
        emp = self.emp_repo.get_by_emp_code(emp_code)
        if not emp:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )

        rec = self.att_repo.get_by_emp_and_date(emp_code, date)
        if not rec:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Attendance record not found for date",
            )

        if body.status in ("ABSENT", "LEAVE") and (body.punch_in is not None or body.punch_out is not None):
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="ABSENT or LEAVE status cannot have punch_in or punch_out",
            )

        target_status = body.status if body.status is not None else rec.get("status")

        if target_status in ("ABSENT", "LEAVE"):
            new_p_in = None
            new_p_out = None
            new_wh = None
            new_late = 0
            new_ot = 0
            new_hd = False
        else:
            if body.punch_in is not None:
                new_p_in = from_epoch_ms(body.punch_in)
            else:
                new_p_in = rec.get("punch_in")

            if new_p_in is None:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Presence status requires punch_in",
                )

            calc_date = get_attendance_date(new_p_in, emp["shift_start"], emp["shift_end"])
            if calc_date != date:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="punch_in must stay on the record's attendance date",
                )

            new_late = compute_late_minutes(new_p_in, emp["shift_start"], date)

            if body.punch_out is not None:
                new_p_out = from_epoch_ms(body.punch_out)
            else:
                new_p_out = rec.get("punch_out")

            if new_p_out is not None:
                diff_sec = (new_p_out - new_p_in).total_seconds()
                if diff_sec <= 0 or diff_sec > 86400:
                    raise HTTPException(
                        status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="punch_out must be after punch_in and within 24 hours",
                    )
                new_wh = compute_work_hours(new_p_in, new_p_out)
                new_ot = compute_overtime(new_p_out, emp["shift_start"], emp["shift_end"], date)
                new_hd = compute_half_day(new_wh)
            else:
                new_p_out = None
                new_wh = None
                new_ot = 0
                new_hd = False

        old_p_in = rec.get("punch_in")
        old_p_out = rec.get("punch_out")
        old_status = rec.get("status")
        old_wh = rec.get("work_hours")
        old_late = rec.get("late_minutes", 0)
        old_ot = rec.get("overtime_minutes", 0)
        old_hd = rec.get("half_day", False)

        changes: Dict[str, Dict[str, Any]] = {}
        if old_status != target_status:
            changes["status"] = {"from": old_status, "to": target_status}
        if old_p_in != new_p_in:
            changes["punch_in"] = {"from": old_p_in, "to": new_p_in}
        if old_p_out != new_p_out:
            changes["punch_out"] = {"from": old_p_out, "to": new_p_out}
        if old_wh != new_wh:
            changes["work_hours"] = {"from": old_wh, "to": new_wh}
        if old_late != new_late:
            changes["late_minutes"] = {"from": old_late, "to": new_late}
        if old_ot != new_ot:
            changes["overtime_minutes"] = {"from": old_ot, "to": new_ot}
        if old_hd != new_hd:
            changes["half_day"] = {"from": old_hd, "to": new_hd}

        if not changes:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Request changes nothing",
            )

        now_utc = from_epoch_ms(int(datetime.now(timezone.utc).timestamp() * 1000))
        history_entry = {
            "at": now_utc,
            "by": body.regularized_by,
            "reason": body.reason,
            "changes": changes,
        }

        current_history = rec.get("history", [])
        update_fields = {
            "status": target_status,
            "punch_in": new_p_in,
            "punch_out": new_p_out,
            "work_hours": new_wh,
            "late_minutes": new_late,
            "overtime_minutes": new_ot,
            "half_day": new_hd,
        }

        updated = self.att_repo.atomic_regularize(
            record_id=rec["_id"],
            current_history=current_history,
            update_fields=update_fields,
            history_entry=history_entry,
        )

        if updated is None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Concurrent modification detected on attendance record",
            )

        return serialize_attendance(updated)
