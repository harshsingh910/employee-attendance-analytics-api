"""
Date, Time and Decimal Math Utilities
Handles IST (UTC+05:30) timezone, sub-second instant truncation,
and Decimal Half-Up rounding.
"""
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))


def to_epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    """Convert datetime to integer epoch milliseconds truncated to whole seconds."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp()) * 1000


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
