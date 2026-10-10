"""
FastAPI Route Dependencies
"""
from pymongo.database import Database

from app.db.mongodb import get_database
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.employee_repository import EmployeeRepository
from app.services.analytics_service import AnalyticsService
from app.services.attendance_service import AttendanceService
from app.services.employee_service import EmployeeService


def get_db() -> Database:
    """Dependency that supplies the MongoDB database instance."""
    return get_database()


def get_employee_service() -> EmployeeService:
    """Dependency that supplies the EmployeeService."""
    repo = EmployeeRepository(get_db())
    return EmployeeService(repo)


def get_attendance_service() -> AttendanceService:
    """Dependency that supplies the AttendanceService."""
    db = get_db()
    att_repo = AttendanceRepository(db)
    emp_repo = EmployeeRepository(db)
    return AttendanceService(att_repo, emp_repo)


def get_analytics_service() -> AnalyticsService:
    """Dependency that supplies the AnalyticsService."""
    db = get_db()
    ana_repo = AnalyticsRepository(db)
    emp_repo = EmployeeRepository(db)
    return AnalyticsService(ana_repo, emp_repo)
