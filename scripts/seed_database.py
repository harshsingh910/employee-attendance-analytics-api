"""
Database Seeding Script
Loads sample data from sample_data/ or generates synthetic test records,
and ensures indexes are built idempotently.
"""
import os
import pathlib
import sys

from bson import json_util
from dotenv import load_dotenv

# Ensure app package is importable
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from pymongo import MongoClient

from app.db.indexes import create_indexes

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")


def seed_database():
    print(f"Connecting to MongoDB at {MONGO_URI}, DB: {MONGO_DB}")
    client = MongoClient(MONGO_URI, tz_aware=True)
    db = client[MONGO_DB]

    # Create indexes first
    create_indexes(db)

    here = pathlib.Path(__file__).parent.parent / "sample_data"
    opts = json_util.JSONOptions(tz_aware=True)

    for name in ("employees", "attendance_logs"):
        json_file = here / f"{name}.json"
        if json_file.exists():
            docs = json_util.loads(json_file.read_text(), json_options=opts)
            for doc in docs:
                # Upsert to avoid duplicate key errors on repeated runs
                if name == "employees":
                    db[name].replace_one({"emp_code": doc["emp_code"]}, doc, upsert=True)
                elif name == "attendance_logs":
                    db[name].replace_one(
                        {"emp_code": doc["emp_code"], "date": doc["date"]}, doc, upsert=True
                    )
            print(f"Seeded {len(docs)} documents into '{db.name}.{name}'")

    emp_count = db.employees.count_documents({})
    att_count = db.attendance_logs.count_documents({})
    print(f"Total current documents: employees={emp_count}, attendance_logs={att_count}")


if __name__ == "__main__":
    seed_database()
