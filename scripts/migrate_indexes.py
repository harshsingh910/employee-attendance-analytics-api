"""
Explicit Database Index Migration Utility
Used by operators to safely inspect and migrate legacy or incompatible indexes.
Requires explicit confirmation flag --apply to execute changes.
Performs data integrity verification (detecting duplicates) before touching indexes.
"""
import os
import pathlib
import sys
from typing import Any, Dict, List

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")


def check_for_duplicates(db) -> Dict[str, List[Any]]:
    """Inspects collections for duplicate documents violating target unique constraints."""
    duplicates: Dict[str, List[Any]] = {}

    # Check employees.emp_code
    emp_dup_pipeline = [
        {"$group": {"_id": "$emp_code", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    emp_dups = list(db.employees.aggregate(emp_dup_pipeline))
    if emp_dups:
        duplicates["employees.emp_code"] = emp_dups

    # Check attendance_logs.(emp_code, date)
    att_dup_pipeline = [
        {"$group": {"_id": {"emp_code": "$emp_code", "date": "$date"}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    att_dups = list(db.attendance_logs.aggregate(att_dup_pipeline))
    if att_dups:
        duplicates["attendance_logs.(emp_code, date)"] = att_dups

    # Check reports.idempotency_key
    rep_dup_pipeline = [
        {"$group": {"_id": "$idempotency_key", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    rep_dups = list(db.reports.aggregate(rep_dup_pipeline))
    if rep_dups:
        duplicates["reports.idempotency_key"] = rep_dups

    return duplicates


def migrate_indexes(apply: bool = False) -> bool:
    print(f"Connecting to MongoDB database '{MONGO_DB}' at {MONGO_URI}...")
    client = MongoClient(MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=2000)
    db = client[MONGO_DB]

    # Step 1: Pre-migration data integrity check
    print("\n--- Step 1: Checking for duplicate data violating unique constraints ---")
    duplicates = check_for_duplicates(db)
    if duplicates:
        print("ERROR: Duplicate data detected! Creating unique indexes would fail or corrupt data.")
        for col_field, dups in duplicates.items():
            print(f"  Collection/Field: {col_field} has {len(dups)} duplicate key(s):")
            for dup in dups[:5]:
                print(f"    Key: {dup['_id']}, Count: {dup['count']}")
            if len(dups) > 5:
                print(f"    ... and {len(dups) - 5} more.")
        print("\nAction required: Deduplicate the affected collections before running migration.")
        return False
    print("Pre-migration data integrity check PASSED: No duplicate data found.")

    # Step 2: Detect conflicting / legacy indexes
    print("\n--- Step 2: Inspecting indexes for legacy or incompatible definitions ---")
    actions: List[Dict[str, Any]] = []

    # Check attendance_logs.(emp_code, date)
    for idx in db.attendance_logs.list_indexes():
        if dict(idx["key"]) == {"emp_code": 1, "date": 1} and not idx.get("unique", False):
            actions.append({
                "collection": "attendance_logs",
                "action": "drop_legacy_index",
                "index_name": idx["name"],
                "reason": "Non-unique index conflicting with target unique constraint",
            })

    if not actions:
        print("All indexes are clean and compatible. No conflicting legacy indexes found.")
    else:
        print(f"Found {len(actions)} conflicting index action(s) needed:")
        for act in actions:
            print(f"  - [{act['collection']}] {act['action']}: '{act['index_name']}' ({act['reason']})")

    # Step 3: Execution or Dry-Run summary
    print("\n--- Step 3: Migration Execution Plan ---")
    if apply:
        print("Execution mode: --apply flag provided. Executing migrations...")
        for act in actions:
            if act["action"] == "drop_legacy_index":
                print(f"Dropping index '{act['index_name']}' on '{act['collection']}'...")
                db[act["collection"]].drop_index(act["index_name"])
                print("Index dropped.")

        # Re-create canonical indexes
        from app.db.indexes import create_indexes
        created = create_indexes(db)
        print("Successfully ensured target canonical indexes:", created)
        print("Migration COMPLETED successfully.")
        return True
    else:
        print("DRY-RUN mode (non-destructive): No changes were applied.")
        if actions:
            print("To execute these index migrations, run:")
            print("  python3 scripts/migrate_indexes.py --apply")
        else:
            print("Database indexes are already up-to-date.")
        return True


if __name__ == "__main__":
    apply_flag = "--apply" in sys.argv
    success = migrate_indexes(apply=apply_flag)
    sys.exit(0 if success else 1)
