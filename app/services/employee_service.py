"""
Employee Domain Service
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException
from fastapi import status as http_status
from pymongo.errors import DuplicateKeyError

from app.repositories.employee_repository import EmployeeRepository
from app.schemas.employee import Employee, EmployeeCreate, EmployeePage
from app.utils.datetime_utils import from_epoch_ms, to_epoch_ms


def serialize_employee(doc: Dict[str, Any]) -> Employee:
    created = doc.get("created_at")
    created_ms = to_epoch_ms(created) if isinstance(created, datetime) else created
    return Employee(
        emp_code=doc["emp_code"],
        name=doc["name"],
        email=doc["email"],
        department=doc["department"],
        shift_start=doc["shift_start"],
        shift_end=doc["shift_end"],
        joined_on=doc["joined_on"],
        created_at=created_ms or 0,
    )


class EmployeeService:
    def __init__(self, repo: Optional[EmployeeRepository] = None):
        self.repo = repo or EmployeeRepository()

    def create_employee(self, body: EmployeeCreate) -> Employee:
        now_utc = datetime.now(timezone.utc)
        # Truncate created_at to whole seconds
        now_utc = from_epoch_ms(int(now_utc.timestamp() * 1000))
        doc = body.model_dump()
        doc["created_at"] = now_utc

        try:
            self.repo.create(doc)
        except DuplicateKeyError:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="emp_code already exists",
            )
        return serialize_employee(doc)

    def list_employees(
        self, department: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> EmployeePage:
        skip = (page - 1) * page_size
        items_raw, total = self.repo.list_employees(department, skip=skip, limit=page_size)
        items = [serialize_employee(d) for d in items_raw]
        return EmployeePage(items=items, total=total, page=page, page_size=page_size)

    def get_employee(self, emp_code: str) -> Employee:
        doc = self.repo.get_by_emp_code(emp_code)
        if not doc:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )
        return serialize_employee(doc)
