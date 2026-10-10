"""
Attendance Data Repository
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ReturnDocument
from pymongo.database import Database

from app.db.mongodb import get_database


class AttendanceRepository:
    def __init__(self, db: Optional[Database] = None):
        self._db = db

    @property
    def db(self) -> Database:
        return self._db if self._db is not None else get_database()

    def create_punch_in(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Inserts an attendance record for punch-in. Raises DuplicateKeyError on duplicate (emp_code, date)."""
        self.db.attendance_logs.insert_one(doc)
        return doc

    def find_latest_open_record(
        self, emp_code: str, punch_out_utc: datetime
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the employee's most recent record whose punch_in is at or before punch_out_utc.
        """
        cursor = (
            self.db.attendance_logs.find(
                {"emp_code": emp_code, "punch_in": {"$lte": punch_out_utc}}
            )
            .sort("punch_in", -1)
            .limit(1)
        )
        docs = list(cursor)
        return docs[0] if docs else None

    def atomic_punch_out(
        self,
        record_id: Any,
        punch_out_utc: datetime,
        work_hours: float,
        overtime_minutes: int,
        half_day: bool,
    ) -> Optional[Dict[str, Any]]:
        """
        Atomically updates punch_out if currently None, preventing race conditions.
        """
        return self.db.attendance_logs.find_one_and_update(
            {"_id": record_id, "punch_out": None},
            {
                "$set": {
                    "punch_out": punch_out_utc,
                    "work_hours": work_hours,
                    "overtime_minutes": overtime_minutes,
                    "half_day": half_day,
                }
            },
            return_document=ReturnDocument.AFTER,
        )

    def get_by_emp_and_date(self, emp_code: str, date: str) -> Optional[Dict[str, Any]]:
        """Fetches attendance record by emp_code and date."""
        return self.db.attendance_logs.find_one({"emp_code": emp_code, "date": date})

    def list_attendance(
        self,
        emp_code: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Paginated attendance records sorted by date descending, emp_code ascending."""
        q: Dict[str, Any] = {}
        if emp_code:
            q["emp_code"] = emp_code
        if date_from or date_to:
            q["date"] = {}
            if date_from:
                q["date"]["$gte"] = date_from
            if date_to:
                q["date"]["$lte"] = date_to
        if status:
            q["status"] = status

        total = self.db.attendance_logs.count_documents(q)
        cursor = (
            self.db.attendance_logs.find(q)
            .sort([("date", -1), ("emp_code", 1)])
            .skip(skip)
            .limit(limit)
        )
        return list(cursor), total

    def atomic_regularize(
        self,
        record_id: Any,
        current_history: List[Dict[str, Any]],
        update_fields: Dict[str, Any],
        history_entry: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Optimistic concurrency regularization update checking exact history state.
        """
        return self.db.attendance_logs.find_one_and_update(
            {"_id": record_id, "history": current_history},
            {
                "$set": update_fields,
                "$push": {"history": history_entry},
            },
            return_document=ReturnDocument.AFTER,
        )
