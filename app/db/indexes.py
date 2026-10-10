"""
MongoDB Index Definitions and Verification (Safe, Non-Destructive)
"""
from typing import Any, Dict, List, Tuple

from pymongo.database import Database
from pymongo.errors import OperationFailure

from app.core.logging import logger


def _safe_create_index(collection, keys, **kwargs) -> str:
    desired_name = kwargs.get("name")
    required_unique = kwargs.get("unique", False)

    key_dict = dict(keys)
    # Check if an index with identical key pattern already exists
    try:
        existing_indexes = list(collection.list_indexes())
    except Exception as exc:
        logger.warning("Could not list indexes on collection '%s': %s", collection.name, exc)
        existing_indexes = []

    for existing in existing_indexes:
        existing_keys = dict(existing["key"])
        if existing_keys == key_dict:
            existing_unique = existing.get("unique", False)
            existing_name = existing["name"]

            if existing_unique != required_unique:
                # Incompatible unique constraints - require explicit DBA/operator migration
                error_msg = (
                    f"Incompatible index '{existing_name}' detected on collection '{collection.name}' "
                    f"for keys {keys}. Required unique={required_unique}, but existing index has "
                    f"unique={existing_unique}. Automatic deletion is disabled to protect production data. "
                    "Manual index migration is required."
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            if existing_name != desired_name:
                logger.info(
                    "Found compatible index '%s' on '%s' satisfying keys %s with matching "
                    "uniqueness constraint (unique=%s). Using existing index without unsafe deletion.",
                    existing_name,
                    collection.name,
                    keys,
                    existing_unique,
                )
            return existing_name

    # No conflicting index; create it
    try:
        return collection.create_index(keys, **kwargs)
    except OperationFailure as err:
        if err.code == 85:
            details = err.details
            details_msg = details.get("errmsg", str(err)) if details else str(err)
            error_msg = (
                f"IndexOptionsConflict (code 85) on '{collection.name}' for keys {keys}: "
                f"{details_msg}. Automatic index deletion is disabled. "
                "Please perform an explicit database migration."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from err
        raise


def create_indexes(database: Database) -> dict:
    """
    Idempotently creates all required indexes for performance, uniqueness, and analytics.
    Performs safe validation without automatically dropping existing production indexes.
    """
    logger.info("Ensuring MongoDB indexes...")

    # employees indexes
    emp_indexes: List[Tuple[List[Tuple[str, int]], Dict[str, Any]]] = [
        ([("emp_code", 1)], {"unique": True, "name": "idx_employees_emp_code_unique"}),
        ([("department", 1)], {"name": "idx_employees_department"}),
        ([("joined_on", 1)], {"name": "idx_employees_joined_on"}),
        ([("department", 1), ("joined_on", 1)], {"name": "idx_employees_dept_joined"}),
    ]

    # attendance_logs indexes
    att_indexes: List[Tuple[List[Tuple[str, int]], Dict[str, Any]]] = [
        ([("emp_code", 1), ("date", 1)], {"unique": True, "name": "idx_attendance_emp_date_unique"}),
        ([("date", -1), ("emp_code", 1)], {"name": "idx_attendance_date_desc_emp_asc"}),
        ([("emp_code", 1), ("punch_in", -1)], {"name": "idx_attendance_emp_punch_in"}),
        ([("date", 1), ("late_minutes", 1), ("emp_code", 1)], {"name": "idx_attendance_date_late_emp"}),
        ([("status", 1), ("date", -1), ("emp_code", 1)], {"name": "idx_attendance_status_date_emp"}),
    ]

    # reports indexes
    rep_indexes: List[Tuple[List[Tuple[str, int]], Dict[str, Any]]] = [
        ([("idempotency_key", 1)], {"unique": True, "name": "idx_reports_idempotency_key_unique"}),
        ([("type", 1), ("year", 1), ("month", 1)], {"name": "idx_reports_type_year_month"}),
    ]

    created: Dict[str, List[str]] = {"employees": [], "attendance_logs": [], "reports": []}

    for keys, kwargs in emp_indexes:
        name = _safe_create_index(database.employees, keys, **kwargs)
        created["employees"].append(name)

    for keys, kwargs in att_indexes:
        name = _safe_create_index(database.attendance_logs, keys, **kwargs)
        created["attendance_logs"].append(name)

    for keys, kwargs in rep_indexes:
        name = _safe_create_index(database.reports, keys, **kwargs)
        created["reports"].append(name)

    logger.info("MongoDB indexes verified successfully: %s", created)
    return created


def get_existing_indexes(database: Database) -> dict:
    """Returns all existing indexes on employees, attendance_logs, and reports collections."""
    return {
        "employees": list(database.employees.list_indexes()),
        "attendance_logs": list(database.attendance_logs.list_indexes()),
        "reports": list(database.reports.list_indexes()),
    }
