"""
Unit and Idempotency Tests for Celery Background Tasks
Covers Section 8:
- Successful monthly report generation
- Successful department export
- Idempotent updates in database (no duplicate reports)
- Bounded retry and failure handling for non-existent employee
"""
from datetime import datetime, timezone

import pytest

from app.workers.tasks import (
    export_department_analytics,
    generate_monthly_attendance_report,
)


def seed_test_data(db):
    db.employees.delete_many({})
    db.attendance_logs.delete_many({})
    db.reports.delete_many({})

    db.employees.insert_one({
        "emp_code": "EMP0101",
        "name": "Celery Tester",
        "email": "celery@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
        "created_at": datetime.now(timezone.utc),
    })

    db.attendance_logs.insert_many([
        {
            "emp_code": "EMP0101",
            "date": "2026-03-02",
            "status": "PRESENT",
            "punch_in": datetime(2026, 3, 2, 4, 0, 0, tzinfo=timezone.utc),
            "punch_out": datetime(2026, 3, 2, 13, 0, 0, tzinfo=timezone.utc),
            "work_hours": 9.0,
            "late_minutes": 0,
            "overtime_minutes": 0,
            "half_day": False,
        },
        {
            "emp_code": "EMP0101",
            "date": "2026-03-03",
            "status": "HALF_DAY",
            "punch_in": datetime(2026, 3, 3, 4, 0, 0, tzinfo=timezone.utc),
            "punch_out": datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc),
            "work_hours": 4.0,
            "late_minutes": 15,
            "overtime_minutes": 0,
            "half_day": True,
        },
    ])


def test_generate_monthly_attendance_report(db):
    seed_test_data(db)

    # Execute task directly (synchronous unit test)
    report = generate_monthly_attendance_report("EMP0101", 2026, 3)

    assert report["emp_code"] == "EMP0101"
    assert report["year"] == 2026
    assert report["month"] == 3
    assert report["total_records"] == 2
    assert report["present_days"] == 1
    assert report["half_days"] == 1
    assert report["total_work_hours"] == 13.0
    assert report["total_late_minutes"] == 15

    # Verify report is written to db
    saved_doc = db.reports.find_one({"emp_code": "EMP0101", "year": 2026, "month": 3})
    assert saved_doc is not None
    assert saved_doc["total_records"] == 2

    # Test idempotency: second execution must not create duplicates
    generate_monthly_attendance_report("EMP0101", 2026, 3)
    count = db.reports.count_documents({"emp_code": "EMP0101", "year": 2026, "month": 3})
    assert count == 1


def test_export_department_analytics(db):
    seed_test_data(db)

    export = export_department_analytics("Engineering", 2026, 3)
    assert export["department"] == "Engineering"
    assert export["headcount"] == 1
    assert export["total_attendance_records"] == 2

    # Check persistence and idempotency
    count = db.reports.count_documents({"department": "Engineering", "year": 2026, "month": 3})
    assert count == 1

    # Run again: count remains 1
    export_department_analytics("Engineering", 2026, 3)
    count_after = db.reports.count_documents({"department": "Engineering", "year": 2026, "month": 3})
    assert count_after == 1


def test_task_raises_on_invalid_employee(db):
    seed_test_data(db)
    with pytest.raises(Exception):
        generate_monthly_attendance_report("EMP_DOES_NOT_EXIST", 2026, 3)
