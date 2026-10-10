"""
Attendance Management Router
"""
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.api.dependencies import get_attendance_service
from app.schemas.attendance import (
    AttendancePage,
    AttendanceRecord,
    PunchInRequest,
    PunchOutRequest,
    RegularizeRequest,
)
from app.services.attendance_service import AttendanceService

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.post("/punch-in", response_model=AttendanceRecord, status_code=201)
def punch_in(
    body: PunchInRequest,
    service: AttendanceService = Depends(get_attendance_service),
):
    """Records an employee punch-in event with shift-based date determination."""
    return service.punch_in(body)


@router.post("/punch-out", response_model=AttendanceRecord)
def punch_out(
    body: PunchOutRequest,
    service: AttendanceService = Depends(get_attendance_service),
):
    """Closes an open punch-in record atomically and calculates derived durations."""
    return service.punch_out(body)


@router.get("", response_model=AttendancePage)
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    date_to: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    status: Optional[str] = Query(None, pattern=r"^(PRESENT|ABSENT|LEAVE|WFH|ON_DUTY)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: AttendanceService = Depends(get_attendance_service),
):
    """Lists attendance records with filtering, date range checks, and pagination."""
    return service.list_attendance(
        emp_code=emp_code,
        date_from=date_from,
        date_to=date_to,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.patch("/{emp_code}/{date}", response_model=AttendanceRecord)
def regularize_attendance(
    emp_code: str = Path(...),
    date: str = Path(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    body: RegularizeRequest = ...,
    service: AttendanceService = Depends(get_attendance_service),
):
    """Regularizes an attendance record with append-only audit trail and optimistic locking."""
    return service.regularize(emp_code=emp_code, date=date, body=body)
