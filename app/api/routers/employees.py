"""
Employees Management Router
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_employee_service
from app.schemas.common import ErrorResponse
from app.schemas.employee import Employee, EmployeeCreate, EmployeePage
from app.services.employee_service import EmployeeService

router = APIRouter(prefix="/employees", tags=["employees"])


@router.post(
    "",
    response_model=Employee,
    status_code=201,
    responses={409: {"model": ErrorResponse, "description": "Duplicate employee code"}},
)
def create_employee(
    body: EmployeeCreate,
    service: EmployeeService = Depends(get_employee_service),
):
    """Creates a new employee record with unique emp_code constraint."""
    return service.create_employee(body)


@router.get("", response_model=EmployeePage)
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: EmployeeService = Depends(get_employee_service),
):
    """Lists employees with optional department filter and pagination."""
    return service.list_employees(department=department, page=page, page_size=page_size)
