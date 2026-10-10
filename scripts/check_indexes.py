"""
Index Verification and Audit Script
Inspects all indexes in MongoDB and verifies required uniqueness and performance indexes.
"""
import os
import pathlib
import sys

from dotenv import load_dotenv

# Ensure app package is importable
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from pymongo import MongoClient

from app.db.indexes import create_indexes, get_existing_indexes

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")

REQUIRED_INDEXES = {
    "employees": [
        "idx_employees_emp_code_unique",
        "idx_employees_department",
        "idx_employees_joined_on",
        "idx_employees_dept_joined",
    ],
    "attendance_logs": [
        "idx_attendance_emp_date_unique",
        "idx_attendance_date_desc_emp_asc",
        "idx_attendance_emp_punch_in",
        "idx_attendance_date_late_emp",
        "idx_attendance_status_date_emp",
    ],
}


def check_indexes():
    print(f"Connecting to MongoDB at {MONGO_URI}, DB: {MONGO_DB}")
    client = MongoClient(MONGO_URI, tz_aware=True)
    db = client[MONGO_DB]

    # Ensure indexes are present
    create_indexes(db)
    existing = get_existing_indexes(db)

    print("\n================ Index Audit Report ================")
    all_ok = True

    for coll, required_list in REQUIRED_INDEXES.items():
        print(f"\nCollection: {coll}")
        existing_names = {idx["name"]: idx for idx in existing.get(coll, [])}
        for req in required_list:
            if req in existing_names:
                idx_info = existing_names[req]
                unique_str = " (UNIQUE)" if idx_info.get("unique") else ""
                key_pattern = idx_info.get("key", {})
                print(f"  [PASS] {req}: {key_pattern}{unique_str}")
            else:
                print(f"  [FAIL] Missing required index: {req}")
                all_ok = False

    print("\n====================================================")
    if all_ok:
        print("All required indexes are verified and active!")
        sys.exit(0)
    else:
        print("Some required indexes are missing.")
        sys.exit(1)


if __name__ == "__main__":
    check_indexes()
