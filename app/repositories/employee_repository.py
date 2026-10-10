"""
Employee Data Repository
"""
from typing import Any, Dict, List, Optional, Tuple

from pymongo.database import Database

from app.db.mongodb import get_database


class EmployeeRepository:
    def __init__(self, db: Optional[Database] = None):
        self._db = db

    @property
    def db(self) -> Database:
        return self._db if self._db is not None else get_database()

    def create(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Inserts a new employee document. Raises DuplicateKeyError on collision."""
        self.db.employees.insert_one(doc)
        return doc

    def get_by_emp_code(self, emp_code: str) -> Optional[Dict[str, Any]]:
        """Fetches an employee document by emp_code."""
        return self.db.employees.find_one({"emp_code": emp_code})

    def list_employees(
        self, department: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Returns paginated employees and total count, sorted stably by emp_code."""
        q: Dict[str, Any] = {}
        if department:
            q["department"] = department
        total = self.db.employees.count_documents(q)
        cursor = self.db.employees.find(q).sort("emp_code", 1).skip(skip).limit(limit)
        return list(cursor), total

    def get_department_employees(self, department: str) -> List[Dict[str, Any]]:
        """Returns minimal list of employees in a department for analytics calculations."""
        return list(
            self.db.employees.find(
                {"department": department},
                {"_id": 0, "emp_code": 1, "joined_on": 1},
            )
        )
