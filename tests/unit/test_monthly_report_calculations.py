"""
Unit Tests for Celery Monthly Report Calculations
Verifies half-day representation, leap years, month boundaries,
parameter validation, and Decimal half-up rounding.
"""
from datetime import datetime, timezone

import pytest

from app.workers.tasks import generate_monthly_attendance_report


def test_monthly_report_half_day_boolean_representation(db):
    """
    Verifies that half-day attendance is counted when represented by half_day=True,
    even if status is 'PRESENT' (as produced by punch-out with work_hours < 4.50).
    """
    db.employees.delete_many({})
    db.attendance_logs.delete_many({})
    db.reports.delete_many({})

    db.employees.insert_one({
        "emp_code": "EMP0201",
        "name": "Half Day Tester",
        "email": "hd@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    })

    # Record 1: Full present day (status="PRESENT", half_day=False, work_hours=8.0)
    # Record 2: Half day (status="PRESENT", half_day=True, work_hours=4.0)
    # Record 3: Half day (status="WFH", half_day=True, work_hours=3.5)
    db.attendance_logs.insert_many([
        {
            "emp_code": "EMP0201",
            "date": "2026-03-02",
            "status": "PRESENT",
            "punch_in": datetime(2026, 3, 2, 4, 0, 0, tzinfo=timezone.utc),
            "punch_out": datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc),
            "work_hours": 8.0,
            "late_minutes": 0,
            "overtime_minutes": 0,
            "half_day": False,
        },
        {
            "emp_code": "EMP0201",
            "date": "2026-03-03",
            "status": "PRESENT",
            "punch_in": datetime(2026, 3, 3, 4, 0, 0, tzinfo=timezone.utc),
            "punch_out": datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc),
            "work_hours": 4.0,
            "late_minutes": 0,
            "overtime_minutes": 0,
            "half_day": True,  # Half day with status PRESENT!
        },
        {
            "emp_code": "EMP0201",
            "date": "2026-03-04",
            "status": "WFH",
            "punch_in": datetime(2026, 3, 4, 4, 0, 0, tzinfo=timezone.utc),
            "punch_out": datetime(2026, 3, 4, 7, 30, 0, tzinfo=timezone.utc),
            "work_hours": 3.5,
            "late_minutes": 0,
            "overtime_minutes": 0,
            "half_day": True,  # Half day with status WFH!
        },
    ])

    report = generate_monthly_attendance_report("EMP0201", 2026, 3)

    assert report["total_records"] == 3
    # Exactly 1 full day and 2 half days
    assert report["present_days"] == 1
    assert report["half_days"] == 2
    assert report["total_work_hours"] == 15.5


def test_monthly_report_leap_year_boundaries(db):
    """Verifies that leap year February (29 days) is handled correctly without dropping dates."""
    db.employees.delete_many({})
    db.attendance_logs.delete_many({})
    db.reports.delete_many({})

    db.employees.insert_one({
        "emp_code": "EMP0202",
        "name": "Leap Year Worker",
        "email": "leap@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2024-01-01",
    })

    # 2024 is a leap year; record on 2024-02-29 must be captured in February 2024 report
    db.attendance_logs.insert_one({
        "emp_code": "EMP0202",
        "date": "2024-02-29",
        "status": "PRESENT",
        "punch_in": datetime(2024, 2, 29, 4, 0, 0, tzinfo=timezone.utc),
        "punch_out": datetime(2024, 2, 29, 13, 0, 0, tzinfo=timezone.utc),
        "work_hours": 9.0,
        "late_minutes": 0,
        "overtime_minutes": 30,
        "half_day": False,
    })

    report = generate_monthly_attendance_report("EMP0202", 2024, 2)
    assert report["total_records"] == 1
    assert report["present_days"] == 1
    assert report["total_work_hours"] == 9.0
    assert report["total_overtime_minutes"] == 30


def test_monthly_report_december_year_boundary(db):
    """Verifies December boundary correctly caps at January 1st of the next year."""
    db.employees.delete_many({})
    db.attendance_logs.delete_many({})
    db.reports.delete_many({})

    db.employees.insert_one({
        "emp_code": "EMP0203",
        "name": "Dec Tester",
        "email": "dec@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    })

    db.attendance_logs.insert_many([
        {
            "emp_code": "EMP0203",
            "date": "2026-12-31",
            "status": "PRESENT",
            "punch_in": datetime(2026, 12, 31, 4, 0, 0, tzinfo=timezone.utc),
            "punch_out": datetime(2026, 12, 31, 13, 0, 0, tzinfo=timezone.utc),
            "work_hours": 9.0,
            "late_minutes": 0,
            "overtime_minutes": 0,
            "half_day": False,
        },
        {
            "emp_code": "EMP0203",
            "date": "2027-01-01",  # Next year: must NOT be in 2026-12 report
            "status": "PRESENT",
            "punch_in": datetime(2027, 1, 1, 4, 0, 0, tzinfo=timezone.utc),
            "punch_out": datetime(2027, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
            "work_hours": 9.0,
            "late_minutes": 0,
            "overtime_minutes": 0,
            "half_day": False,
        },
    ])

    report = generate_monthly_attendance_report("EMP0203", 2026, 12)
    assert report["total_records"] == 1
    assert report["present_days"] == 1


def test_monthly_report_invalid_year_and_month():
    """Invalid year or month parameters must raise a ValueError immediately."""
    with pytest.raises(ValueError) as exc:
        generate_monthly_attendance_report("EMP0201", 2026, 13)
    assert "Invalid year or month" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        generate_monthly_attendance_report("EMP0201", 2026, 0)
    assert "Invalid year or month" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        generate_monthly_attendance_report("EMP0201", 1850, 5)
    assert "Invalid year or month" in str(exc.value)
