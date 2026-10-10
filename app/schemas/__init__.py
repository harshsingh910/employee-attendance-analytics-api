"""Schemas package."""
from app.schemas.analytics import (
    DepartmentSummary,
    DepartmentSummaryItem,
    EmployeeMonthly,
    Leaderboard,
    LeaderboardItem,
    Trend,
    TrendItem,
)
from app.schemas.attendance import (
    AttendancePage,
    AttendanceRecord,
    HistoryEntry,
    PunchInRequest,
    PunchOutRequest,
    RegularizeRequest,
)
from app.schemas.common import ErrorResponse, ValidationErrorResponse
from app.schemas.employee import Employee, EmployeeCreate, EmployeePage

__all__ = [
    "ErrorResponse",
    "ValidationErrorResponse",
    "EmployeeCreate",
    "Employee",
    "EmployeePage",
    "PunchInRequest",
    "PunchOutRequest",
    "RegularizeRequest",
    "HistoryEntry",
    "AttendanceRecord",
    "AttendancePage",
    "EmployeeMonthly",
    "DepartmentSummaryItem",
    "DepartmentSummary",
    "LeaderboardItem",
    "Leaderboard",
    "TrendItem",
    "Trend",
]
