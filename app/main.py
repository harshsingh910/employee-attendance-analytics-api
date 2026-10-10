"""
Employee Attendance & Analytics API

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (reads from environment variables, .env file supported)
"""
from __future__ import annotations

import calendar
import math
import os
import re
from contextlib import asynccontextmanager
from datetime import date as dt_date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from bson import json_util
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Path, Request, status as http_status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

load_dotenv()

IST = timezone(timedelta(hours=5, minutes=30))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB", "attendance_db")

client: Optional[MongoClient] = None
db = None


def get_db():
    global client, db
    if client is None or db is None:
        client = MongoClient(
            os.getenv("MONGO_URI", "mongodb://localhost:27017"),
            serverSelectionTimeoutMS=2000,
            tz_aware=True,
        )
        db = client[os.getenv("MONGO_DB", "attendance_db")]
    return db


def create_indexes(database):
    """Idempotently create required indexes for performance, uniqueness, and analytics."""
    # employees indexes
    database.employees.create_index([("emp_code", 1)], unique=True, name="idx_employees_emp_code_unique")
    database.employees.create_index([("department", 1)], name="idx_employees_department")
    database.employees.create_index([("joined_on", 1)], name="idx_employees_joined_on")
    database.employees.create_index([("department", 1), ("joined_on", 1)], name="idx_employees_dept_joined")

    # attendance_logs indexes
    database.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="idx_attendance_emp_date_unique",
    )
    database.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="idx_attendance_date_desc_emp_asc",
    )
    database.attendance_logs.create_index(
        [("emp_code", 1), ("punch_in", -1)],
        name="idx_attendance_emp_punch_in",
    )
    database.attendance_logs.create_index(
        [("date", 1), ("late_minutes", 1), ("emp_code", 1)],
        name="idx_attendance_date_late_emp",
    )
    database.attendance_logs.create_index(
        [("status", 1), ("date", -1), ("emp_code", 1)],
        name="idx_attendance_status_date_emp",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, db
    client = MongoClient(
        os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=2000,
        tz_aware=True,
    )
    db = client[os.getenv("MONGO_DB", "attendance_db")]
    try:
        create_indexes(db)
    except Exception:
        # Index creation failure should not crash in mock environments, but in production it ensures indexes exist
        pass
    yield
    if client is not None:
        client.close()
        client = None
        db = None


app = FastAPI(
    title="Employee Attendance & Analytics API",
    version="2.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# Date, Time & Math Helpers
# --------------------------------------------------------------------------- #
def to_epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    """Convert datetime to integer epoch milliseconds truncated to whole seconds."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (int(dt.timestamp()) * 1000)


def from_epoch_ms(ms: int) -> datetime:
    """Convert integer epoch milliseconds to UTC datetime truncated to whole seconds (R1)."""
    truncated_ms = (ms // 1000) * 1000
    return datetime.fromtimestamp(truncated_ms / 1000, tz=timezone.utc)


def to_ist(dt: datetime) -> datetime:
    """Convert UTC datetime to IST datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def round_half_up(value: float | Decimal, decimals: int = 2) -> float:
    """Round using Decimal ROUND_HALF_UP (R4, R8)."""
    d = Decimal(str(value))
    target = Decimal("10") ** (-decimals)
    return float(d.quantize(target, rounding=ROUND_HALF_UP))


def get_attendance_date(punch_in_utc: datetime, shift_start: str, shift_end: str) -> str:
    """
    R1: A record's date is the IST calendar date of its punch_in.
    Exception: overnight shifts (shift_end <= shift_start, e.g. 22:00 - 06:00):
    a punch-in whose IST time is strictly earlier than shift_end belongs to the shift
    that started the previous day.
    """
    punch_in_ist = to_ist(punch_in_utc)
    is_overnight = shift_end <= shift_start
    if is_overnight:
        end_h, end_m = map(int, shift_end.split(":"))
        punch_time = (punch_in_ist.hour, punch_in_ist.minute, punch_in_ist.second)
        shift_end_time = (end_h, end_m, 0)
        if punch_time < shift_end_time:
            return (punch_in_ist.date() - timedelta(days=1)).isoformat()
    return punch_in_ist.date().isoformat()


def compute_late_minutes(punch_in_utc: datetime, shift_start: str, attendance_date: str) -> int:
    """
    R2: Grace period 10 minutes. Late only if punch-in is strictly more than 10:00 after shift_start;
    then late_minutes = whole minutes (floor) since shift_start, not since grace period ended.
    """
    punch_in_ist = to_ist(punch_in_utc)
    start_h, start_m = map(int, shift_start.split(":"))
    d = dt_date.fromisoformat(attendance_date)
    shift_start_dt = datetime(d.year, d.month, d.day, start_h, start_m, 0, tzinfo=IST)
    diff_seconds = (punch_in_ist - shift_start_dt).total_seconds()
    if diff_seconds > 600:
        return int(math.floor(diff_seconds / 60))
    return 0


def compute_overtime(punch_out_utc: datetime, shift_start: str, shift_end: str, attendance_date: str) -> int:
    """
    R3: Whole minutes (floor) from shift_end to punch_out, counted only if at least 30; otherwise 0.
    Handles overnight shifts across midnight (shift_end falls on next calendar day).
    """
    punch_out_ist = to_ist(punch_out_utc)
    end_h, end_m = map(int, shift_end.split(":"))
    d = dt_date.fromisoformat(attendance_date)
    is_overnight = shift_end <= shift_start
    if is_overnight:
        d = d + timedelta(days=1)
    shift_end_dt = datetime(d.year, d.month, d.day, end_h, end_m, 0, tzinfo=IST)
    diff_seconds = (punch_out_ist - shift_end_dt).total_seconds()
    if diff_seconds >= 1800:
        return int(math.floor(diff_seconds / 60))
    return 0


def compute_work_hours(punch_in_utc: Optional[datetime], punch_out_utc: Optional[datetime]) -> Optional[float]:
    """
    R4: (punch_out - punch_in) in seconds / 3600, rounded to 2 decimals half-up. Null until punch-out.
    """
    if punch_in_utc is None or punch_out_utc is None:
        return None
    sec = int((punch_out_utc - punch_in_utc).total_seconds())
    val = Decimal(sec) / Decimal(3600)
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_half_day(work_hours: Optional[float]) -> bool:
    """
    R5: After punch-out, half_day is true when rounded work_hours < 4.50.
    """
    if work_hours is None:
        return False
    return work_hours < 4.50


def count_working_days(joined_on_str: str, year: int, month: int) -> int:
    """
    R7: Monday-Friday working days in the month, counted from joined_on for mid-month joiners.
    """
    num_days = calendar.monthrange(year, month)[1]
    first_month_day = dt_date(year, month, 1)
    last_month_day = dt_date(year, month, num_days)
    joined_date = dt_date.fromisoformat(joined_on_str)

    start_date = max(first_month_day, joined_date)
    if start_date > last_month_day:
        return 0

    count = 0
    cur = start_date
    while cur <= last_month_day:
        if cur.weekday() < 5:  # Mon-Fri
            count += 1
        cur += timedelta(days=1)
    return count


# --------------------------------------------------------------------------- #
# Pydantic Schemas
# --------------------------------------------------------------------------- #
class EmployeeCreate(BaseModel):
    emp_code: str = Field(..., pattern=r"^EMP\d{4,6}$")
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(..., min_length=1, max_length=50)
    shift_start: str = Field("09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field("18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    joined_on: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")

    @model_validator(mode="after")
    def validate_shift_times(self) -> EmployeeCreate:
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start must differ from shift_end")
        return self


class Employee(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str
    shift_end: str
    joined_on: str
    created_at: int


class EmployeePage(BaseModel):
    items: List[Employee]
    total: int
    page: int
    page_size: int


class PunchInRequest(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(None, ge=100000000000, le=4102444800000)
    status: str = Field("PRESENT", pattern=r"^(PRESENT|WFH|ON_DUTY)$")


class PunchOutRequest(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(None, ge=100000000000, le=4102444800000)


class RegularizeRequest(BaseModel):
    status: Optional[str] = Field(None, pattern=r"^(PRESENT|ABSENT|LEAVE|WFH|ON_DUTY)$")
    punch_in: Optional[int] = Field(None, ge=100000000000, le=4102444800000)
    punch_out: Optional[int] = Field(None, ge=100000000000, le=4102444800000)
    reason: str = Field(..., min_length=5, max_length=200)
    regularized_by: str = Field(..., min_length=1, max_length=50)


class HistoryEntry(BaseModel):
    at: int
    by: str
    reason: str
    changes: Dict[str, Dict[str, Any]]


class AttendanceRecord(BaseModel):
    emp_code: str
    date: str
    status: str
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    work_hours: Optional[float] = None
    late_minutes: int = 0
    overtime_minutes: int = 0
    half_day: bool = False
    history: List[HistoryEntry] = []


class AttendancePage(BaseModel):
    items: List[AttendanceRecord]
    total: int
    page: int
    page_size: int


class EmployeeMonthly(BaseModel):
    emp_code: str
    month: str
    working_days: int
    present_days: float
    leave_days: int
    late_count: int
    total_late_minutes: int
    total_overtime_minutes: int
    attendance_pct: Optional[float]


class DepartmentSummaryItem(BaseModel):
    department: str
    headcount: int
    present_days: float
    avg_work_hours: Optional[float]
    late_count: int
    total_late_minutes: int
    leave_count: int
    on_duty_count: int


class DepartmentSummary(BaseModel):
    month: str
    items: List[DepartmentSummaryItem]


class LeaderboardItem(BaseModel):
    rank: int
    emp_code: str
    name: str
    department: str
    total_late_minutes: int
    late_count: int


class Leaderboard(BaseModel):
    month: str
    items: List[LeaderboardItem]


class TrendItem(BaseModel):
    date: str
    is_working_day: bool
    headcount: int
    present_count: float
    late_count: int
    attendance_rate: Optional[float]
    moving_avg_7d: Optional[float]


class Trend(BaseModel):
    department: str
    items: List[TrendItem]


# --------------------------------------------------------------------------- #
# Document Serializers
# --------------------------------------------------------------------------- #
def serialize_employee(doc: Dict[str, Any]) -> Employee:
    created = doc.get("created_at")
    created_ms = to_epoch_ms(created) if isinstance(created, datetime) else created
    return Employee(
        emp_code=doc["emp_code"],
        name=doc["name"],
        email=doc["email"],
        department=doc["department"],
        shift_start=doc["shift_start"],
        shift_end=doc["shift_end"],
        joined_on=doc["joined_on"],
        created_at=created_ms or 0,
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


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["system"])
def health():
    database = get_db()
    try:
        database.client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )


@app.post("/employees", response_model=Employee, status_code=201, tags=["employees"])
def create_employee(body: EmployeeCreate):
    database = get_db()
    now_utc = datetime.now(timezone.utc)
    # Truncate created_at to whole seconds
    now_utc = from_epoch_ms(int(now_utc.timestamp() * 1000))
    doc = body.model_dump()
    doc["created_at"] = now_utc

    try:
        database.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="emp_code already exists",
        )

    return serialize_employee(doc)


@app.get("/employees", response_model=EmployeePage, tags=["employees"])
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    database = get_db()
    q: Dict[str, Any] = {}
    if department:
        q["department"] = department

    total = database.employees.count_documents(q)
    skip = (page - 1) * page_size
    cursor = (
        database.employees.find(q)
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_employee(d) for d in cursor]
    return EmployeePage(items=items, total=total, page=page, page_size=page_size)


@app.post("/attendance/punch-in", response_model=AttendanceRecord, status_code=201, tags=["attendance"])
def punch_in(body: PunchInRequest):
    database = get_db()
    emp = database.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Employee not found")

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
        database.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="already punched in for this date",
        )

    return serialize_attendance(doc)


@app.post("/attendance/punch-out", response_model=AttendanceRecord, tags=["attendance"])
def punch_out(body: PunchOutRequest):
    database = get_db()
    emp = database.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if body.punched_at is not None:
        punch_out_utc = from_epoch_ms(body.punched_at)
    else:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        punch_out_utc = from_epoch_ms(now_ms)

    # Closes the employee's most recent record whose punch_in is at or before punched_at
    rec = (
        database.attendance_logs.find(
            {"emp_code": body.emp_code, "punch_in": {"$lte": punch_out_utc}}
        )
        .sort("punch_in", -1)
        .limit(1)
    )
    docs = list(rec)
    if not docs:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No open punch-in record found",
        )

    target_rec = docs[0]
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

    # Atomic update to prevent race conditions (two simultaneous punch-outs yield exactly one 200 and one 409)
    res = database.attendance_logs.find_one_and_update(
        {"_id": target_rec["_id"], "punch_out": None},
        {
            "$set": {
                "punch_out": punch_out_utc,
                "work_hours": wh,
                "overtime_minutes": ot,
                "half_day": hd,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if res is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Record was already punched out concurrently",
        )

    return serialize_attendance(res)


@app.get("/attendance", response_model=AttendancePage, tags=["attendance"])
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    date_to: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    status: Optional[str] = Query(None, pattern=r"^(PRESENT|ABSENT|LEAVE|WFH|ON_DUTY)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must not be after date_to",
        )

    database = get_db()
    q: Dict[str, Any] = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status

    total = database.attendance_logs.count_documents(q)
    skip = (page - 1) * page_size
    cursor = (
        database.attendance_logs.find(q)
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_attendance(d) for d in cursor]
    return AttendancePage(items=items, total=total, page=page, page_size=page_size)


@app.patch("/attendance/{emp_code}/{date}", response_model=AttendanceRecord, tags=["attendance"])
def regularize_attendance(
    emp_code: str = Path(...),
    date: str = Path(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    body: RegularizeRequest = ...,
):
    database = get_db()
    emp = database.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Employee not found")

    rec = database.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not rec:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Attendance record not found for date")

    # Business rule: setting status ABSENT or LEAVE clears both punch times
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
        # Presence status requires punch_in (supplied or already stored)
        if body.punch_in is not None:
            new_p_in = from_epoch_ms(body.punch_in)
        else:
            new_p_in = rec.get("punch_in")

        if new_p_in is None:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Presence status requires punch_in",
            )

        # punch_in must stay on the record's attendance date (R1)
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

    # Check for actual changes
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

    # Optimistic concurrency: ensure history matches current to prevent lost updates
    current_history = rec.get("history", [])
    updated = database.attendance_logs.find_one_and_update(
        {"_id": rec["_id"], "history": current_history},
        {
            "$set": {
                "status": target_status,
                "punch_in": new_p_in,
                "punch_out": new_p_out,
                "work_hours": new_wh,
                "late_minutes": new_late,
                "overtime_minutes": new_ot,
                "half_day": new_hd,
            },
            "$push": {"history": history_entry},
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Concurrent modification detected on attendance record",
        )

    return serialize_attendance(updated)


@app.get("/analytics/employees/{emp_code}/monthly", response_model=EmployeeMonthly, tags=["analytics"])
def employee_monthly(
    emp_code: str = Path(...),
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
):
    database = get_db()
    emp = database.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Employee not found")

    year, m_num = map(int, month.split("-"))
    num_days = calendar.monthrange(year, m_num)[1]
    first_day = f"{month}-01"
    last_day = f"{month}-{num_days:02d}"

    working_days = count_working_days(emp["joined_on"], year, m_num)

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {"$gte": first_day, "$lte": last_day},
            }
        },
        {
            "$project": {
                "status": 1,
                "late_minutes": {"$ifNull": ["$late_minutes", 0]},
                "overtime_minutes": {"$ifNull": ["$overtime_minutes", 0]},
                "half_day": {"$ifNull": ["$half_day", False]},
                "day_of_week": {
                    "$dayOfWeek": {
                        "$dateFromString": {"dateString": "$date"}
                    }
                },
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$day_of_week", [2, 3, 4, 5, 6]]},  # Mon-Fri
                                    {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                ]
                            },
                            {"$cond": ["$half_day", 0.5, 1.0]},
                            0.0,
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}
                },
                "late_count": {
                    "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
                },
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {"$sum": "$overtime_minutes"},
            }
        },
    ]

    agg_res = list(database.attendance_logs.aggregate(pipeline))
    if agg_res:
        row = agg_res[0]
        present_days = float(row.get("present_days", 0.0))
        leave_days = int(row.get("leave_days", 0))
        late_count = int(row.get("late_count", 0))
        total_late = int(row.get("total_late_minutes", 0))
        total_ot = int(row.get("total_overtime_minutes", 0))
    else:
        present_days = 0.0
        leave_days = 0
        late_count = 0
        total_late = 0
        total_ot = 0

    if working_days == 0:
        att_pct = None
    else:
        att_pct = round_half_up((present_days / working_days) * 100, 2)

    return EmployeeMonthly(
        emp_code=emp_code,
        month=month,
        working_days=working_days,
        present_days=present_days,
        leave_days=leave_days,
        late_count=late_count,
        total_late_minutes=total_late,
        total_overtime_minutes=total_ot,
        attendance_pct=att_pct,
    )


@app.get("/analytics/departments/summary", response_model=DepartmentSummary, tags=["analytics"])
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
):
    database = get_db()
    year, m_num = map(int, month.split("-"))
    num_days = calendar.monthrange(year, m_num)[1]
    first_day = f"{month}-01"
    last_day = f"{month}-{num_days:02d}"

    match_stage: Dict[str, Any] = {"joined_on": {"$lte": last_day}}
    if department:
        match_stage["department"] = department

    pipeline = [
        {"$match": match_stage},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"emp": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$emp"]},
                                    {"$gte": ["$date", first_day]},
                                    {"$lte": ["$date", last_day]},
                                ]
                            }
                        }
                    }
                ],
                "as": "logs",
            }
        },
        {
            "$addFields": {
                "emp_present_days": {
                    "$sum": {
                        "$map": {
                            "input": "$logs",
                            "as": "log",
                            "in": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {"$in": ["$$log.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                            {
                                                "$in": [
                                                    {
                                                        "$dayOfWeek": {
                                                            "$dateFromString": {"dateString": "$$log.date"}
                                                        }
                                                    },
                                                    [2, 3, 4, 5, 6],
                                                ]
                                            },
                                        ]
                                    },
                                    {"$cond": [{"$eq": ["$$log.half_day", True]}, 0.5, 1.0]},
                                    0.0,
                                ]
                            },
                        }
                    }
                },
                "emp_work_hours_sum": {
                    "$sum": {
                        "$map": {
                            "input": {
                                "$filter": {
                                    "input": "$logs",
                                    "as": "log",
                                    "cond": {
                                        "$and": [
                                            {"$in": ["$$log.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                            {"$ne": ["$$log.work_hours", None]},
                                        ]
                                    },
                                }
                            },
                            "as": "log",
                            "in": "$$log.work_hours",
                        }
                    }
                },
                "emp_work_hours_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "log",
                            "cond": {
                                "$and": [
                                    {"$in": ["$$log.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                    {"$ne": ["$$log.work_hours", None]},
                                ]
                            },
                        }
                    }
                },
                "emp_late_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "log",
                            "cond": {"$gt": [{"$ifNull": ["$$log.late_minutes", 0]}, 0]},
                        }
                    }
                },
                "emp_total_late_minutes": {
                    "$sum": {
                        "$map": {
                            "input": "$logs",
                            "as": "log",
                            "in": {"$ifNull": ["$$log.late_minutes", 0]},
                        }
                    }
                },
                "emp_leave_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "log",
                            "cond": {"$eq": ["$$log.status", "LEAVE"]},
                        }
                    }
                },
                "emp_on_duty_count": {
                    "$size": {
                        "$filter": {
                            "input": "$logs",
                            "as": "log",
                            "cond": {"$eq": ["$$log.status", "ON_DUTY"]},
                        }
                    }
                },
            }
        },
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": 1},
                "present_days": {"$sum": "$emp_present_days"},
                "total_work_hours": {"$sum": "$emp_work_hours_sum"},
                "work_hours_count": {"$sum": "$emp_work_hours_count"},
                "late_count": {"$sum": "$emp_late_count"},
                "total_late_minutes": {"$sum": "$emp_total_late_minutes"},
                "leave_count": {"$sum": "$emp_leave_count"},
                "on_duty_count": {"$sum": "$emp_on_duty_count"},
            }
        },
        {"$sort": {"_id": 1}},
    ]

    rows = list(database.employees.aggregate(pipeline))
    items = []
    for r in rows:
        wh_count = r.get("work_hours_count", 0)
        tot_wh = r.get("total_work_hours", 0.0)
        avg_wh = round_half_up(tot_wh / wh_count, 2) if wh_count > 0 else None
        items.append(
            DepartmentSummaryItem(
                department=r["_id"],
                headcount=r.get("headcount", 0),
                present_days=float(r.get("present_days", 0.0)),
                avg_work_hours=avg_wh,
                late_count=r.get("late_count", 0),
                total_late_minutes=r.get("total_late_minutes", 0),
                leave_count=r.get("leave_count", 0),
                on_duty_count=r.get("on_duty_count", 0),
            )
        )
    return DepartmentSummary(month=month, items=items)


@app.get("/analytics/leaderboard/late", response_model=Leaderboard, tags=["analytics"])
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
):
    database = get_db()
    year, m_num = map(int, month.split("-"))
    num_days = calendar.monthrange(year, m_num)[1]
    first_day = f"{month}-01"
    last_day = f"{month}-{num_days:02d}"

    pipeline: List[Dict[str, Any]] = [
        {
            "$match": {
                "date": {"$gte": first_day, "$lte": last_day},
                "late_minutes": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "emp",
            }
        },
        {"$unwind": "$emp"},
    ]

    if department:
        pipeline.append({"$match": {"emp.department": department}})

    # Standard competition ranking: ties share rank, next rank skipped
    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                },
            }
        },
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$emp.name",
                "department": "$emp.department",
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
    ])

    rows = list(database.attendance_logs.aggregate(pipeline))
    items = [LeaderboardItem(**r) for r in rows]
    return Leaderboard(month=month, items=items)


@app.get("/analytics/departments/{department}/trend", response_model=Trend, tags=["analytics"])
def department_trend(
    department: str = Path(...),
    from_date: str = Query(..., alias="from", pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    to_date: str = Query(..., alias="to", pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
):
    if to_date < from_date:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="to date must be greater than or equal to from date",
        )

    d_start = dt_date.fromisoformat(from_date)
    d_end = dt_date.fromisoformat(to_date)
    days_count = (d_end - d_start).days + 1
    if days_count > 92:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Date range must not exceed 92 days",
        )

    database = get_db()
    dept_emps = list(
        database.employees.find(
            {"department": department},
            {"_id": 0, "emp_code": 1, "joined_on": 1},
        )
    )
    if not dept_emps:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    dept_emp_codes = [e["emp_code"] for e in dept_emps]
    from_dt = datetime.fromisoformat(f"{from_date}T00:00:00Z")
    to_dt_plus_1 = datetime.fromisoformat(f"{to_date}T00:00:00Z") + timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "emp_code": {"$in": dept_emp_codes},
                "date": {"$gte": from_date, "$lte": to_date},
            }
        },
        {
            "$group": {
                "_id": "$date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                            {"$cond": ["$half_day", 0.5, 1.0]},
                            0.0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": "$_id",
                "date_dt": {"$dateFromString": {"dateString": "$_id"}},
                "present_count": 1,
                "late_count": 1,
            }
        },
        {
            "$densify": {
                "field": "date_dt",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [from_dt, to_dt_plus_1],
                },
            }
        },
        {
            "$project": {
                "date": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$date_dt"}
                },
                "present_count": {"$ifNull": ["$present_count", 0.0]},
                "late_count": {"$ifNull": ["$late_count", 0]},
            }
        },
        {"$sort": {"date": 1}},
        {
            "$addFields": {
                "is_working_day": {
                    "$in": [
                        {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}},
                        [2, 3, 4, 5, 6],
                    ]
                },
                "headcount": {
                    "$size": {
                        "$filter": {
                            "input": dept_emps,
                            "as": "e",
                            "cond": {"$lte": ["$$e.joined_on", "$date"]},
                        }
                    }
                },
            }
        },
        {
            "$addFields": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {
                            "$round": [
                                {"$divide": ["$present_count", "$headcount"]},
                                4,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [-6, "current"]
                        },
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": {
                    "$cond": [
                        {"$ne": ["$moving_avg_7d", None]},
                        {"$round": ["$moving_avg_7d", 4]},
                        None,
                    ]
                },
            }
        },
    ]

    rows = list(database.attendance_logs.aggregate(pipeline))
    items = []
    for r in rows:
        rate = r.get("attendance_rate")
        m_avg = r.get("moving_avg_7d")
        items.append(
            TrendItem(
                date=r["date"],
                is_working_day=r["is_working_day"],
                headcount=r["headcount"],
                present_count=float(r["present_count"]),
                late_count=r["late_count"],
                attendance_rate=round_half_up(rate, 4) if rate is not None else None,
                moving_avg_7d=round_half_up(m_avg, 4) if m_avg is not None else None,
            )
        )
    return Trend(department=department, items=items)


@app.get("/admin/explain/{endpoint}", tags=["admin"])
def explain_endpoint(
    endpoint: str = Path(..., pattern=r"^(attendance_list|employee_monthly|department_summary|late_leaderboard|department_trend)$"),
    emp_code: Optional[str] = None,
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    date_to: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    status: Optional[str] = Query(None, pattern=r"^(PRESENT|ABSENT|LEAVE|WFH|ON_DUTY)$"),
    from_date: Optional[str] = Query(None, alias="from", pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    to_date: Optional[str] = Query(None, alias="to", pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    database = get_db()

    if endpoint == "attendance_list":
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date_from > date_to")
        q: Dict[str, Any] = {}
        if emp_code:
            q["emp_code"] = emp_code
        if date_from or date_to:
            q["date"] = {}
            if date_from:
                q["date"]["$gte"] = date_from
            if date_to:
                q["date"]["$lte"] = date_to
        if status:
            q["status"] = status
        skip = (page - 1) * page_size
        command = {
            "find": "attendance_logs",
            "filter": q,
            "sort": {"date": -1, "emp_code": 1},
            "skip": skip,
            "limit": page_size,
        }
        res = database.command("explain", command, verbosity="executionStats")
        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": json_util.loads(json_util.dumps(res)),
        }

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="emp_code and month are required",
            )
        year, m_num = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m_num)[1]
        first_day = f"{month}-01"
        last_day = f"{month}-{num_days:02d}"

        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {"$gte": first_day, "$lte": last_day},
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late": {"$sum": "$late_minutes"},
                }
            },
        ]
        command = {
            "aggregate": "attendance_logs",
            "pipeline": pipeline,
            "cursor": {},
        }
        res = database.command("explain", command, verbosity="executionStats")
        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": json_util.loads(json_util.dumps(res)),
        }

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="month is required",
            )
        year, m_num = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m_num)[1]
        first_day = f"{month}-01"
        last_day = f"{month}-{num_days:02d}"

        match_stage: Dict[str, Any] = {"joined_on": {"$lte": last_day}}
        if department:
            match_stage["department"] = department

        pipeline = [
            {"$match": match_stage},
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {"emp": "$emp_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$emp_code", "$$emp"]},
                                        {"$gte": ["$date", first_day]},
                                        {"$lte": ["$date", last_day]},
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "logs",
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "headcount": {"$sum": 1},
                }
            },
        ]
        command = {
            "aggregate": "employees",
            "pipeline": pipeline,
            "cursor": {},
        }
        res = database.command("explain", command, verbosity="executionStats")
        return {
            "endpoint": endpoint,
            "collection": "employees",
            "explain": json_util.loads(json_util.dumps(res)),
        }

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="month is required",
            )
        year, m_num = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m_num)[1]
        first_day = f"{month}-01"
        last_day = f"{month}-{num_days:02d}"

        pipeline = [
            {
                "$match": {
                    "date": {"$gte": first_day, "$lte": last_day},
                    "late_minutes": {"$gt": 0},
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "late_count": {"$sum": 1},
                }
            },
        ]
        command = {
            "aggregate": "attendance_logs",
            "pipeline": pipeline,
            "cursor": {},
        }
        res = database.command("explain", command, verbosity="executionStats")
        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": json_util.loads(json_util.dumps(res)),
        }

    elif endpoint == "department_trend":
        if not department or not from_date or not to_date:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="department, from, and to are required",
            )
        if to_date < from_date:
            raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="to < from")

        dept_emps = list(database.employees.find({"department": department}, {"_id": 0, "emp_code": 1}))
        dept_emp_codes = [e["emp_code"] for e in dept_emps]

        pipeline = [
            {
                "$match": {
                    "emp_code": {"$in": dept_emp_codes},
                    "date": {"$gte": from_date, "$lte": to_date},
                }
            },
            {
                "$group": {
                    "_id": "$date",
                    "present_count": {"$sum": 1},
                }
            },
        ]
        command = {
            "aggregate": "attendance_logs",
            "pipeline": pipeline,
            "cursor": {},
        }
        res = database.command("explain", command, verbosity="executionStats")
        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": json_util.loads(json_util.dumps(res)),
        }

    raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid endpoint")
