"""
Analytics and Aggregations Router
"""
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.api.dependencies import get_analytics_service
from app.schemas.analytics import (
    DepartmentSummary,
    EmployeeMonthly,
    Leaderboard,
    Trend,
)
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/employees/{emp_code}/monthly", response_model=EmployeeMonthly)
def employee_monthly(
    emp_code: str = Path(...),
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    service: AnalyticsService = Depends(get_analytics_service),
):
    """Monthly attendance analytics for an employee, handling zero-attendance records."""
    return service.get_employee_monthly(emp_code=emp_code, month=month)


@router.get("/departments/summary", response_model=DepartmentSummary)
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
    service: AnalyticsService = Depends(get_analytics_service),
):
    """Department summary aggregated across all employees in the department."""
    return service.get_department_summary(month=month, department=department)


@router.get("/leaderboard/late", response_model=Leaderboard)
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
    service: AnalyticsService = Depends(get_analytics_service),
):
    """Late arrival leaderboard with standard competition ranking ($rank) preserving ties."""
    return service.get_late_leaderboard(month=month, limit=limit, department=department)


@router.get("/departments/{department}/trend", response_model=Trend)
def department_trend(
    department: str = Path(...),
    from_date: str = Query(..., alias="from", pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    to_date: str = Query(..., alias="to", pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    service: AnalyticsService = Depends(get_analytics_service),
):
    """Department daily attendance trend with calendar date densification and 7-day moving avg."""
    return service.get_department_trend(department=department, from_date=from_date, to_date=to_date)
