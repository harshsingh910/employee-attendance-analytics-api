"""
Application Lifecycle and Database Availability Tests
Covers Section B.7:
- Health probe when MongoDB is available (HTTP 200)
- Health probe when MongoDB is unavailable (HTTP 503)
- Lifespan startup and shutdown execution
"""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.api.dependencies import get_db
from app.db.mongodb import close_mongo_client
from app.db.redis import close_redis_client
from app.main import app


def test_lifecycle_health_when_database_available():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


def test_lifecycle_health_when_database_unavailable():
    # Mock broken database dependency
    mock_db = MagicMock()
    mock_db.client.admin.command.side_effect = ServerSelectionTimeoutError("No MongoDB server available")

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with TestClient(app) as client:
            res = client.get("/health")
            assert res.status_code == 503
            assert res.json() == {"detail": "Database unavailable"}
    finally:
        app.dependency_overrides.clear()


def test_lifecycle_clean_shutdown():
    # Calling close_mongo_client and close_redis_client cleanly on shutdown
    close_mongo_client()
    close_redis_client()
    # Safe to call multiple times (idempotent shutdown)
    close_mongo_client()
    close_redis_client()
    # Re-initialize client for subsequent test isolation
    get_db()
