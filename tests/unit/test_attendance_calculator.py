"""
Unit Tests for Attendance Business Rules and Calculator
Covers R1-R7: Late minutes, overtime, work hours, rounding, half day, working days.
"""
from datetime import datetime, timezone

from app.services.attendance_calculator import (
    compute_half_day,
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
    count_working_days,
)
from app.utils.datetime_utils import (
    IST,
    get_attendance_date,
)


def test_late_minutes_grace_period():
    # Shift start 09:30 IST. Shift date 2026-03-10
    # 09:40:00 IST (exactly 10 min = 600 sec) -> late_minutes = 0 (grace period)
    punch_dt_grace = datetime(2026, 3, 10, 9, 40, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(punch_dt_grace, "09:30", "2026-03-10") == 0

    # 09:40:01 IST (601 sec) -> strictly > 600 sec -> floor(601/60) = 10 minutes
    punch_dt_late = datetime(2026, 3, 10, 9, 40, 1, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(punch_dt_late, "09:30", "2026-03-10") == 10

    # 09:25:00 IST (early arrival) -> 0
    punch_dt_early = datetime(2026, 3, 10, 9, 25, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(punch_dt_early, "09:30", "2026-03-10") == 0


def test_overtime_threshold_30_minutes():
    # Shift 09:30 to 18:30 IST.
    # 18:59:00 IST (29 minutes after shift end) -> strictly < 30 min -> 0
    punch_out_29 = datetime(2026, 3, 10, 18, 59, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime(punch_out_29, "09:30", "18:30", "2026-03-10") == 0

    # 19:00:00 IST (exactly 30 minutes after shift end) -> 30
    punch_out_30 = datetime(2026, 3, 10, 19, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime(punch_out_30, "09:30", "18:30", "2026-03-10") == 30

    # 19:45:30 IST -> 75 minutes floor
    punch_out_75 = datetime(2026, 3, 10, 19, 45, 30, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime(punch_out_75, "09:30", "18:30", "2026-03-10") == 75


def test_overtime_overnight_shift():
    # Overnight shift: 22:00 to 06:00 IST next day
    # Attendance date 2026-03-10, shift ends 2026-03-11 06:00 IST
    # Punch out at 2026-03-11 07:15 IST (75 minutes overtime)
    punch_out = datetime(2026, 3, 11, 7, 15, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime(punch_out, "22:00", "06:00", "2026-03-10") == 75


def test_work_hours_half_up_rounding():
    t_in = datetime(2026, 3, 10, 9, 30, 0, tzinfo=timezone.utc)
    # 4 hours, 15 minutes, 30 seconds = 15330 seconds / 3600 = 4.258333... -> 4.26
    t_out = datetime(2026, 3, 10, 13, 45, 30, tzinfo=timezone.utc)
    wh = compute_work_hours(t_in, t_out)
    assert wh == 4.26

    # Exact boundary half-up rounding test: 18 seconds = 0.005 hours
    # 4 hours + 18 seconds = 14418 / 3600 = 4.005 -> 4.01
    t_out_halfup = datetime(2026, 3, 10, 13, 30, 18, tzinfo=timezone.utc)
    assert compute_work_hours(t_in, t_out_halfup) == 4.01


def test_half_day_boundary():
    assert compute_half_day(4.49) is True
    assert compute_half_day(4.50) is False
    assert compute_half_day(8.00) is False
    assert compute_half_day(None) is False


def test_working_days_count():
    # March 2026 has 31 days, starting on a Sunday, ending on a Tuesday.
    # Total Mon-Fri days in March 2026: 22 days
    assert count_working_days("2026-01-01", 2026, 3) == 22

    # Mid-month joiner: joined 2026-03-16 (Monday) -> 12 working days remaining in March
    assert count_working_days("2026-03-16", 2026, 3) == 12

    # Future joiner: joined 2026-04-01 -> 0 working days in March 2026
    assert count_working_days("2026-04-01", 2026, 3) == 0


def test_overnight_shift_date_determination():
    # Shift 22:00 to 06:00.
    # Punch in at 2026-03-11 02:30 IST (strictly before 06:00) -> belongs to 2026-03-10
    punch_early_morning = datetime(2026, 3, 11, 2, 30, 0, tzinfo=IST).astimezone(timezone.utc)
    assert get_attendance_date(punch_early_morning, "22:00", "06:00") == "2026-03-10"

    # Punch in at 2026-03-11 22:15 IST (after 06:00) -> belongs to 2026-03-11
    punch_night = datetime(2026, 3, 11, 22, 15, 0, tzinfo=IST).astimezone(timezone.utc)
    assert get_attendance_date(punch_night, "22:00", "06:00") == "2026-03-11"
