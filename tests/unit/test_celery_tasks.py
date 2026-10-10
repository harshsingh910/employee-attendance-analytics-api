"""
Unit, Idempotency, and Retry Tests for Celery Background Tasks
Covers Section D:
- Successful monthly report generation and retrieval
- Successful department export and retrieval
- Task idempotency: repeated delivery updates document in place without duplicates
- Isolation between monthly employee reports and department exports
- Bounded retry behavior on transient errors
- Failure handling for invalid/missing employee
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import PyMongoError

from app.workers.tasks import (
    export_department_analytics,
    generate_monthly_attendance_report,
    get_department_analytics_report,
    get_monthly_attendance_report,
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


def test_generate_and_retrieve_monthly_report(db):
    seed_test_data(db)

    report = generate_monthly_attendance_report("EMP0101", 2026, 3)
    assert report["emp_code"] == "EMP0101"
    assert report["year"] == 2026
    assert report["month"] == 3
    assert report["total_records"] == 2
    assert report["present_days"] == 1
    assert report["half_days"] == 1
    assert report["total_work_hours"] == 13.0
    assert report["total_late_minutes"] == 15

    # Test retrieval function
    retrieved = get_monthly_attendance_report("EMP0101", 2026, 3)
    assert retrieved is not None
    assert retrieved["emp_code"] == "EMP0101"
    assert retrieved["total_records"] == 2
    assert retrieved["type"] == "monthly_attendance"


def test_monthly_report_idempotency_in_place_update(db):
    seed_test_data(db)

    generate_monthly_attendance_report("EMP0101", 2026, 3)
    doc_first = db.reports.find_one({"emp_code": "EMP0101", "year": 2026, "month": 3})
    assert doc_first is not None
    first_id = doc_first["_id"]

    # Re-run task: document must update in-place with the exact same ObjectId
    generate_monthly_attendance_report("EMP0101", 2026, 3)
    count = db.reports.count_documents({"emp_code": "EMP0101", "year": 2026, "month": 3})
    assert count == 1

    doc_second = db.reports.find_one({"emp_code": "EMP0101", "year": 2026, "month": 3})
    assert doc_second["_id"] == first_id


def test_export_and_retrieve_department_analytics(db):
    seed_test_data(db)

    export = export_department_analytics("Engineering", 2026, 3)
    assert export["department"] == "Engineering"
    assert export["headcount"] == 1
    assert export["total_attendance_records"] == 2

    # Retrieve
    retrieved = get_department_analytics_report("Engineering", 2026, 3)
    assert retrieved is not None
    assert retrieved["department"] == "Engineering"
    assert retrieved["headcount"] == 1
    assert retrieved["type"] == "department_export"


def test_task_isolation_between_types(db):
    seed_test_data(db)

    # Generate both types of reports
    generate_monthly_attendance_report("EMP0101", 2026, 3)
    export_department_analytics("Engineering", 2026, 3)

    # Verify both exist independently and do not overwrite each other
    emp_report = get_monthly_attendance_report("EMP0101", 2026, 3)
    dept_report = get_department_analytics_report("Engineering", 2026, 3)

    assert emp_report is not None and emp_report["type"] == "monthly_attendance"
    assert dept_report is not None and dept_report["type"] == "department_export"
    assert db.reports.count_documents({}) == 2


def test_task_retry_on_transient_failure():
    # Simulate a transient database failure and verify retry is triggered
    with patch.object(
        generate_monthly_attendance_report,
        "retry",
        side_effect=RuntimeError("Retry scheduled"),
    ) as mock_retry, patch("app.workers.tasks.get_database") as mock_get_db:
        mock_db = MagicMock()
        mock_db.employees.find_one.side_effect = PyMongoError("Transient network timeout")
        mock_get_db.return_value = mock_db

        with pytest.raises(RuntimeError, match="Retry scheduled"):
            generate_monthly_attendance_report("EMP0101", 2026, 3)

        assert mock_retry.called


def test_task_raises_on_invalid_employee(db):
    seed_test_data(db)
    # Permanent validation error must raise ValueError directly without invoking retry
    with patch.object(generate_monthly_attendance_report, "retry") as mock_retry:
        with pytest.raises(ValueError, match="not found"):
            generate_monthly_attendance_report("EMP_DOES_NOT_EXIST", 2026, 3)
        assert not mock_retry.called, "Permanent validation error should not invoke retry"


def test_cross_year_report_separation(db):
    seed_test_data(db)

    # Insert log for Jan 2025
    db.attendance_logs.insert_one({
        "emp_code": "EMP0101",
        "date": "2025-01-15",
        "status": "PRESENT",
        "punch_in": datetime(2025, 1, 15, 4, 0, 0, tzinfo=timezone.utc),
        "punch_out": datetime(2025, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        "work_hours": 9.0,
        "late_minutes": 0,
        "overtime_minutes": 0,
        "half_day": False,
    })

    # Generate for Jan 2025 and Jan 2026
    rep_2025 = generate_monthly_attendance_report("EMP0101", 2025, 1)
    rep_2026 = generate_monthly_attendance_report("EMP0101", 2026, 1)

    assert rep_2025["idempotency_key"] == "monthly_report:EMP0101:2025:01"
    assert rep_2026["idempotency_key"] == "monthly_report:EMP0101:2026:01"
    assert rep_2025["total_records"] == 1
    assert rep_2026["total_records"] == 0

    # Ensure retrieval by canonical key returns separate reports
    ret_2025 = get_monthly_attendance_report("EMP0101", 2025, 1)
    ret_2026 = get_monthly_attendance_report("EMP0101", 2026, 1)
    assert ret_2025 is not None and ret_2026 is not None
    assert ret_2025["year"] == 2025 and ret_2026["year"] == 2026
    assert db.reports.count_documents({"emp_code": "EMP0101"}) == 2


def test_concurrent_task_execution_idempotency(db):
    seed_test_data(db)
    from concurrent.futures import ThreadPoolExecutor

    # Concurrently trigger the same report generation across 5 threads
    def run_task():
        return generate_monthly_attendance_report("EMP0101", 2026, 3)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_task) for _ in range(5)]
        results = [f.result() for f in futures]

    assert len(results) == 5
    for r in results:
        assert r["idempotency_key"] == "monthly_report:EMP0101:2026:03"

    # Only 1 document exists in db.reports
    count = db.reports.count_documents({"idempotency_key": "monthly_report:EMP0101:2026:03"})
    assert count == 1
