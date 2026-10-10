"""
MongoDB Index Definitions and Verification
"""
from pymongo.database import Database
from pymongo.errors import OperationFailure

from app.core.logging import logger


def _safe_create_index(collection, keys, **kwargs) -> str:
    desired_name = kwargs.get("name")
    try:
        return collection.create_index(keys, **kwargs)
    except OperationFailure as err:
        if err.code == 85:  # IndexOptionsConflict
            # Find and replace legacy conflicting index
            key_dict = dict(keys)
            for idx in collection.list_indexes():
                if dict(idx["key"]) == key_dict and idx["name"] != desired_name:
                    logger.info(
                        "Replacing conflicting legacy index '%s' on '%s' with '%s'",
                        idx["name"],
                        collection.name,
                        desired_name,
                    )
                    collection.drop_index(idx["name"])
                    break
            return collection.create_index(keys, **kwargs)
        raise


def create_indexes(database: Database) -> dict:
    """
    Idempotently creates all required indexes for performance, uniqueness, and analytics.
    Handles legacy unnamed or non-unique conflicting indexes safely.
    """
    logger.info("Ensuring MongoDB indexes...")

    # employees indexes
    emp_indexes = [
        ([("emp_code", 1)], {"unique": True, "name": "idx_employees_emp_code_unique"}),
        ([("department", 1)], {"name": "idx_employees_department"}),
        ([("joined_on", 1)], {"name": "idx_employees_joined_on"}),
        ([("department", 1), ("joined_on", 1)], {"name": "idx_employees_dept_joined"}),
    ]

    # attendance_logs indexes
    att_indexes = [
        ([("emp_code", 1), ("date", 1)], {"unique": True, "name": "idx_attendance_emp_date_unique"}),
        ([("date", -1), ("emp_code", 1)], {"name": "idx_attendance_date_desc_emp_asc"}),
        ([("emp_code", 1), ("punch_in", -1)], {"name": "idx_attendance_emp_punch_in"}),
        ([("date", 1), ("late_minutes", 1), ("emp_code", 1)], {"name": "idx_attendance_date_late_emp"}),
        ([("status", 1), ("date", -1), ("emp_code", 1)], {"name": "idx_attendance_status_date_emp"}),
    ]

    created = {"employees": [], "attendance_logs": []}

    for keys, kwargs in emp_indexes:
        name = _safe_create_index(database.employees, keys, **kwargs)
        created["employees"].append(name)

    for keys, kwargs in att_indexes:
        name = _safe_create_index(database.attendance_logs, keys, **kwargs)
        created["attendance_logs"].append(name)

    logger.info("MongoDB indexes verified successfully: %s", created)
    return created


def get_existing_indexes(database: Database) -> dict:
    """Returns all existing indexes on employees and attendance_logs collections."""
    return {
        "employees": list(database.employees.list_indexes()),
        "attendance_logs": list(database.attendance_logs.list_indexes()),
    }
