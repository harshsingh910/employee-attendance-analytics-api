"""
Unit Tests for MongoDB Configuration and Sanitization
Verifies environment loading, URI credential masking, and connection timeout behavior.
"""
from unittest.mock import patch

from pymongo.errors import ServerSelectionTimeoutError

from app.core.config import Settings
from app.db.mongodb import _sanitize_uri, close_mongo_client, get_mongo_client


def test_sanitize_uri_masks_passwords():
    raw_atlas_uri = "mongodb+srv://mockuser:mock_password_to_mask@cluster.example.com/?appName=TestCluster"
    sanitized = _sanitize_uri(raw_atlas_uri)
    assert "mock_password_to_mask" not in sanitized
    assert sanitized == "mongodb+srv://mockuser:****@cluster.example.com/?appName=TestCluster"

    raw_standard_uri = "mongodb://mockuser:mock_password_to_mask@localhost:27017/attendance_db"
    sanitized_std = _sanitize_uri(raw_standard_uri)
    assert "mock_password_to_mask" not in sanitized_std
    assert sanitized_std == "mongodb://mockuser:****@localhost:27017/attendance_db"

    # URI without credentials should remain unchanged
    local_uri = "mongodb://localhost:27017"
    assert _sanitize_uri(local_uri) == "mongodb://localhost:27017"


def test_settings_loads_configured_variables(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb+srv://testuser:<db_password>@testcluster.mongodb.net/")
    monkeypatch.setenv("MONGO_DB", "attendance_db")
    monkeypatch.setenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "3000")

    custom_settings = Settings()
    assert custom_settings.MONGO_URI == "mongodb+srv://testuser:<db_password>@testcluster.mongodb.net/"
    assert custom_settings.MONGO_DB == "attendance_db"
    assert custom_settings.MONGO_SERVER_SELECTION_TIMEOUT_MS == 3000


def test_mongodb_connection_failure_raises_server_timeout():
    # Test client connection failure against an unreachable host with low timeout
    close_mongo_client()
    with patch("app.db.mongodb.settings.MONGO_URI", "mongodb://127.0.0.1:1"), \
         patch("app.db.mongodb.settings.MONGO_SERVER_SELECTION_TIMEOUT_MS", 100):
        client = get_mongo_client()
        try:
            client.admin.command("ping")
            assert False, "Should raise ServerSelectionTimeoutError on unreachable host"
        except ServerSelectionTimeoutError:
            pass  # Expected behavior
        finally:
            close_mongo_client()


def test_explain_command_serializes_bson_types():
    from unittest.mock import MagicMock

    from bson.binary import Binary
    from bson.timestamp import Timestamp
    from fastapi.encoders import jsonable_encoder

    from app.repositories.analytics_repository import AnalyticsRepository

    mock_db = MagicMock()
    mock_db.command.return_value = {
        "executionStats": {"executionSuccess": True, "nReturned": 1},
        "$clusterTime": {
            "clusterTime": Timestamp(12345678, 1),
            "signature": {
                "hash": Binary(b"\x01\x02\x03\x04"),
                "raw_bytes": b"\xaa\xbb\xcc",
                "keyId": 1234567890,
            },
        },
        "operationTime": Timestamp(12345678, 1),
    }

    repo = AnalyticsRepository(mock_db)
    result = repo.explain_command("attendance_logs", {"find": "attendance_logs"})

    # Must be serializable by FastAPI's jsonable_encoder without raising ValueError / TypeError
    encoded = jsonable_encoder(result)
    assert encoded["executionStats"]["executionSuccess"] is True
    assert "$clusterTime" in encoded
    assert "clusterTime" in encoded["$clusterTime"]
    assert "signature" in encoded["$clusterTime"]
    assert "hash" in encoded["$clusterTime"]["signature"]
    assert "operationTime" in encoded

