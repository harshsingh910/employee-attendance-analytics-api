"""
Celery Background Tasks for Reporting and Analytics Export
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.logging import logger
from app.db.mongodb import get_database
from app.utils.datetime_utils import round_half_up
from app.workers.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="tasks.generate_monthly_attendance_report",
    max_retries=3,
    default_retry_delay=5,
    retry_backoff=True,
    retry_jitter=True,
)
def generate_monthly_attendance_report(self, emp_code: str, year: int, month: int) -> Dict[str, Any]:
    """
    Idempotent task that compiles a comprehensive monthly attendance report for an employee.
    Stores the result in the reports collection.
    """
    task_id = self.request.id if getattr(self, "request", None) else "direct"
    logger.info("Starting monthly report task [%s] for emp_code=%s (%04d-%02d)", task_id, emp_code, year, month)
    try:
        # Validate year and month
        if not isinstance(year, int) or not isinstance(month, int) or month < 1 or month > 12 or year < 1900 or year > 2100:
            raise ValueError(f"Invalid year or month: year={year}, month={month}")

        db = get_database()
        emp = db.employees.find_one({"emp_code": emp_code}, {"_id": 0})
        if not emp:
            raise ValueError(f"Employee with emp_code '{emp_code}' not found")

        # Query month's logs with exact calendar boundaries
        start_date = f"{year:04d}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1:04d}-01-01"
        else:
            end_date = f"{year:04d}-{month + 1:02d}-01"

        logs = list(
            db.attendance_logs.find(
                {"emp_code": emp_code, "date": {"$gte": start_date, "$lt": end_date}},
                {"_id": 0},
            )
        )

        # Accurately distinguish full present days and half-days (via half_day boolean or legacy status)
        full_present_days = sum(
            1 for log in logs
            if log.get("status") in ("PRESENT", "WFH", "ON_DUTY") and not log.get("half_day")
        )
        half_days = sum(
            1 for log in logs
            if log.get("half_day") is True or log.get("status") == "HALF_DAY"
        )
        present_days = full_present_days
        absent_days = sum(1 for log in logs if log.get("status") == "ABSENT")
        leave_days = sum(1 for log in logs if log.get("status") == "LEAVE")
        total_hours = sum(log.get("work_hours", 0.0) for log in logs)
        total_late = sum(log.get("late_minutes", 0) for log in logs)
        total_overtime = sum(log.get("overtime_minutes", 0) for log in logs)

        idempotency_key = f"monthly_report:{emp_code}:{year:04d}:{month:02d}"
        report = {
            "idempotency_key": idempotency_key,
            "type": "monthly_attendance",
            "task_id": task_id,
            "status": "COMPLETED",
            "emp_code": emp_code,
            "year": year,
            "month": month,
            "total_records": len(logs),
            "present_days": present_days,
            "half_days": half_days,
            "absent_days": absent_days,
            "leave_days": leave_days,
            "total_work_hours": round_half_up(total_hours, 2),
            "total_late_minutes": total_late,
            "total_overtime_minutes": total_overtime,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Store report idempotently in reports collection by canonical idempotency key
        db.reports.update_one(
            {"idempotency_key": idempotency_key},
            {"$set": report},
            upsert=True,
        )

        logger.info("Successfully finished monthly report task [%s] for emp_code=%s", task_id, emp_code)
        return report

    except ValueError as exc:
        logger.error("Validation error generating monthly report task [%s]: %s", task_id, exc)
        raise  # Do not retry permanent validation errors
    except Exception as exc:
        logger.error("Error generating monthly report task [%s]: %s", task_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="tasks.export_department_analytics",
    max_retries=3,
    default_retry_delay=5,
    retry_backoff=True,
    retry_jitter=True,
)
def export_department_analytics(self, department: str, year: int, month: int) -> Dict[str, Any]:
    """
    Idempotent task that compiles and stores department summary analytics.
    """
    task_id = self.request.id if getattr(self, "request", None) else "direct"
    logger.info("Starting department export task [%s] for department=%s (%04d-%02d)", task_id, department, year, month)
    try:
        if not isinstance(year, int) or not isinstance(month, int) or month < 1 or month > 12 or year < 1900 or year > 2100:
            raise ValueError(f"Invalid year or month: year={year}, month={month}")

        db = get_database()
        employees = list(db.employees.find({"department": department}, {"_id": 0, "emp_code": 1}))
        emp_codes = [e["emp_code"] for e in employees]

        start_date = f"{year:04d}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1:04d}-01-01"
        else:
            end_date = f"{year:04d}-{month + 1:02d}-01"

        logs = list(
            db.attendance_logs.find(
                {"emp_code": {"$in": emp_codes}, "date": {"$gte": start_date, "$lt": end_date}},
                {"_id": 0},
            )
        )

        idempotency_key = f"dept_export:{department}:{year:04d}:{month:02d}"
        export_data = {
            "idempotency_key": idempotency_key,
            "type": "department_export",
            "task_id": task_id,
            "status": "COMPLETED",
            "department": department,
            "year": year,
            "month": month,
            "headcount": len(emp_codes),
            "total_attendance_records": len(logs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        db.reports.update_one(
            {"idempotency_key": idempotency_key},
            {"$set": export_data},
            upsert=True,
        )

        logger.info("Finished department export task [%s] for department=%s", task_id, department)
        return export_data

    except ValueError as exc:
        logger.error("Validation error running department export task [%s]: %s", task_id, exc)
        raise  # Do not retry permanent validation errors
    except Exception as exc:
        logger.error("Error running department export task [%s]: %s", task_id, exc)
        raise self.retry(exc=exc)


def get_monthly_attendance_report(emp_code: str, year: int, month: int) -> Optional[Dict[str, Any]]:
    """Retrieves an existing monthly attendance report from the database."""
    db = get_database()
    idempotency_key = f"monthly_report:{emp_code}:{year:04d}:{month:02d}"
    return db.reports.find_one(
        {"idempotency_key": idempotency_key},
        {"_id": 0},
    )


def get_department_analytics_report(department: str, year: int, month: int) -> Optional[Dict[str, Any]]:
    """Retrieves an existing department export report from the database."""
    db = get_database()
    idempotency_key = f"dept_export:{department}:{year:04d}:{month:02d}"
    return db.reports.find_one(
        {"idempotency_key": idempotency_key},
        {"_id": 0},
    )
