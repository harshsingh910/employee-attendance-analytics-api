"""
Attendance Business Rules Calculator (R2, R3, R4, R5, R7)
Pure, deterministic calculations for shifts, durations, and working days.
"""
import calendar
import math
from datetime import date as dt_date
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app.utils.datetime_utils import IST, to_ist


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
