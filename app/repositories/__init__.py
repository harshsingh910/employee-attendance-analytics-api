"""
Data Repositories
"""
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.employee_repository import EmployeeRepository

__all__ = [
    "EmployeeRepository",
    "AttendanceRepository",
    "AnalyticsRepository",
]
