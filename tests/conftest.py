"""
Shared Pytest Fixtures for Unit, Integration, and Performance Tests
"""
import os

import pytest
from fastapi.testclient import TestClient

# Ensure test database is used; safely fall back to local instance if Atlas placeholder password is set
raw_mongo_uri = os.getenv("TEST_MONGO_URI") or os.getenv("MONGO_URI", "mongodb://localhost:27017")
if "<db_password>" in raw_mongo_uri or "<password>" in raw_mongo_uri:
    raw_mongo_uri = "mongodb://localhost:27017"

os.environ["MONGO_URI"] = raw_mongo_uri
os.environ["MONGO_DB"] = "test_attendance_db"
os.environ["REDIS_URL"] = os.getenv("REDIS_URL", "redis://localhost:6379/15")
os.environ["RATE_LIMIT_ENABLED"] = "false"  # Default off in general API tests so tests aren't throttled

from app.main import app, create_indexes, get_db  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    database = get_db()
    database.employees.delete_many({})
    database.attendance_logs.delete_many({})
    database.reports.delete_many({})
    create_indexes(database)
    yield
    db_teardown = get_db()
    db_teardown.employees.delete_many({})
    db_teardown.attendance_logs.delete_many({})
    db_teardown.reports.delete_many({})


@pytest.fixture
def db():
    return get_db()
