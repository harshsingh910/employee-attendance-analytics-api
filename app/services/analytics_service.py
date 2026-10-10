"""
Analytics Domain Service
"""
import calendar
from datetime import date as dt_date
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import HTTPException
from fastapi import status as http_status

from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.analytics import (
    DepartmentSummary,
    DepartmentSummaryItem,
    EmployeeMonthly,
    Leaderboard,
    LeaderboardItem,
    Trend,
    TrendItem,
)
from app.services.attendance_calculator import count_working_days
from app.utils.datetime_utils import round_half_up


class AnalyticsService:
    def __init__(
        self,
        analytics_repo: Optional[AnalyticsRepository] = None,
        emp_repo: Optional[EmployeeRepository] = None,
    ):
        self.analytics_repo = analytics_repo or AnalyticsRepository()
        self.emp_repo = emp_repo or EmployeeRepository()

    def get_employee_monthly(self, emp_code: str, month: str) -> EmployeeMonthly:
        emp = self.emp_repo.get_by_emp_code(emp_code)
        if not emp:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )

        year, m_num = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m_num)[1]
        first_day = f"{month}-01"
        last_day = f"{month}-{num_days:02d}"

        working_days = count_working_days(emp["joined_on"], year, m_num)
        agg_res = self.analytics_repo.aggregate_employee_monthly(emp_code, first_day, last_day)

        if agg_res:
            present_days = float(agg_res.get("present_days", 0.0))
            leave_days = int(agg_res.get("leave_days", 0))
            late_count = int(agg_res.get("late_count", 0))
            total_late = int(agg_res.get("total_late_minutes", 0))
            total_ot = int(agg_res.get("total_overtime_minutes", 0))
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

    def get_department_summary(
        self, month: str, department: Optional[str] = None
    ) -> DepartmentSummary:
        year, m_num = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m_num)[1]
        first_day = f"{month}-01"
        last_day = f"{month}-{num_days:02d}"

        rows = self.analytics_repo.aggregate_department_summary(first_day, last_day, department)
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

    def get_late_leaderboard(
        self, month: str, limit: int = 10, department: Optional[str] = None
    ) -> Leaderboard:
        year, m_num = map(int, month.split("-"))
        num_days = calendar.monthrange(year, m_num)[1]
        first_day = f"{month}-01"
        last_day = f"{month}-{num_days:02d}"

        rows = self.analytics_repo.aggregate_late_leaderboard(
            first_day, last_day, limit, department
        )
        items = [LeaderboardItem(**r) for r in rows]
        return Leaderboard(month=month, items=items)

    def get_department_trend(
        self, department: str, from_date: str, to_date: str
    ) -> Trend:
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

        dept_emps = self.emp_repo.get_department_employees(department)
        if not dept_emps:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Department not found",
            )

        dept_emp_codes = [e["emp_code"] for e in dept_emps]
        from_dt = datetime.fromisoformat(f"{from_date}T00:00:00Z")
        to_dt_plus_1 = datetime.fromisoformat(f"{to_date}T00:00:00Z") + timedelta(days=1)

        rows = self.analytics_repo.aggregate_department_trend(
            dept_emp_codes=dept_emp_codes,
            dept_emps=dept_emps,
            from_date=from_date,
            to_date=to_date,
            from_dt=from_dt,
            to_dt_plus_1=to_dt_plus_1,
        )

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

    def explain(
        self,
        endpoint: str,
        emp_code: Optional[str] = None,
        month: Optional[str] = None,
        department: Optional[str] = None,
        limit: int = 10,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
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
            cmd = {
                "find": "attendance_logs",
                "filter": q,
                "sort": {"date": -1, "emp_code": 1},
                "skip": skip,
                "limit": page_size,
            }
            exp_res = self.analytics_repo.explain_command("attendance_logs", cmd)
            return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp_res}

        if not month and endpoint in ("employee_monthly", "department_summary", "late_leaderboard"):
            month = "2026-03"

        year, m_num = map(int, month.split("-")) if month else (2026, 3)
        num_days = calendar.monthrange(year, m_num)[1]
        first_day = f"{year:04d}-{m_num:02d}-01"
        last_day = f"{year:04d}-{m_num:02d}-{num_days:02d}"

        if endpoint == "employee_monthly":
            target_emp = emp_code or "EMP0001"
            pipeline = [
                {"$match": {"emp_code": target_emp, "date": {"$gte": first_day, "$lte": last_day}}},
                {"$project": {"status": 1, "late_minutes": {"$ifNull": ["$late_minutes", 0]}}},
                {"$group": {"_id": None, "total_late": {"$sum": "$late_minutes"}}},
            ]
            cmd = {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}}
            exp_res = self.analytics_repo.explain_command("attendance_logs", cmd)
            return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp_res}

        if endpoint == "department_summary":
            match_stage: Dict[str, Any] = {"joined_on": {"$lte": last_day}}
            if department:
                match_stage["department"] = department
            pipeline = [
                {"$match": match_stage},
                {"$group": {"_id": "$department", "headcount": {"$sum": 1}}},
            ]
            cmd = {"aggregate": "employees", "pipeline": pipeline, "cursor": {}}
            exp_res = self.analytics_repo.explain_command("employees", cmd)
            return {"endpoint": endpoint, "collection": "employees", "explain": exp_res}

        if endpoint == "late_leaderboard":
            pipeline = [
                {"$match": {"date": {"$gte": first_day, "$lte": last_day}, "late_minutes": {"$gt": 0}}},
                {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}}},
                {"$sort": {"total_late_minutes": -1}},
                {"$limit": limit},
            ]
            cmd = {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}}
            exp_res = self.analytics_repo.explain_command("attendance_logs", cmd)
            return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp_res}

        if endpoint == "department_trend":
            f_d = from_date or "2026-03-01"
            t_d = to_date or "2026-03-15"
            pipeline = [
                {"$match": {"date": {"$gte": f_d, "$lte": t_d}}},
                {"$group": {"_id": "$date", "present_count": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ]
            cmd = {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}}
            exp_res = self.analytics_repo.explain_command("attendance_logs", cmd)
            return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp_res}

        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Unknown endpoint for explain")
