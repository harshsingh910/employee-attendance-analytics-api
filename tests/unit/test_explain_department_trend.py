"""
Unit and Regression Tests for /admin/explain/department_trend endpoint.
Verifies query parameter mapping, date bounds, department filtering,
BSON serialization, and validation handling with deterministic mocks.
"""
from unittest.mock import MagicMock

import pytest
from bson.binary import Binary
from bson.timestamp import Timestamp
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services.analytics_service import AnalyticsService


@pytest.fixture
def mock_analytics_service():
    """Mock service fixture to inspect pipeline parameters without hitting Atlas."""
    mock_analytics_repo = MagicMock()
    mock_emp_repo = MagicMock()

    service = AnalyticsService(
        analytics_repo=mock_analytics_repo,
        emp_repo=mock_emp_repo,
    )
    return service, mock_analytics_repo, mock_emp_repo


def test_department_trend_october_date_and_department_mapping(mock_analytics_service):
    """Verifies October dates and department emp_codes are accurately passed to pipeline."""
    service, mock_repo, mock_emp_repo = mock_analytics_service

    mock_emp_repo.get_department_employees.return_value = [
        {"emp_code": "EMP1001", "name": "Alice", "department": "Engineering"},
        {"emp_code": "EMP1002", "name": "Bob", "department": "Engineering"},
    ]
    mock_repo.explain_command.return_value = {
        "executionStats": {"executionSuccess": True, "totalKeysExamined": 2},
        "$clusterTime": {"clusterTime": Timestamp(1791619768, 1)},
    }

    result = service.explain(
        endpoint="department_trend",
        department="Engineering",
        from_date="2026-10-01",
        to_date="2026-10-31",
    )

    mock_repo.explain_command.assert_called_once()
    called_collection, called_cmd = mock_repo.explain_command.call_args[0]
    assert called_collection == "attendance_logs"

    pipeline = called_cmd["pipeline"]
    match_stage = pipeline[0]["$match"]

    # 1. Date filter must contain exact October bounds
    assert match_stage["date"]["$gte"] == "2026-10-01"
    assert match_stage["date"]["$lte"] == "2026-10-31"

    # 2. March fallback dates must NOT be present
    assert "2026-03-01" not in str(pipeline)
    assert "2026-03-15" not in str(pipeline)

    # 3. Department constraint must match department employees
    assert match_stage["emp_code"] == {"$in": ["EMP1001", "EMP1002"]}

    # 4. Result must contain explain data
    assert result["endpoint"] == "department_trend"
    assert result["collection"] == "attendance_logs"
    assert "explain" in result


def test_department_trend_dynamic_date_range(mock_analytics_service):
    """Verifies different supplied date ranges are respected rather than hard-coded."""
    service, mock_repo, mock_emp_repo = mock_analytics_service

    mock_emp_repo.get_department_employees.return_value = [
        {"emp_code": "EMP2001", "name": "Charlie", "department": "Sales"}
    ]
    mock_repo.explain_command.return_value = {"executionStats": {"executionSuccess": True}}

    service.explain(
        endpoint="department_trend",
        department="Sales",
        from_date="2026-11-05",
        to_date="2026-11-20",
    )

    _, called_cmd = mock_repo.explain_command.call_args[0]
    match_stage = called_cmd["pipeline"][0]["$match"]
    assert match_stage["date"]["$gte"] == "2026-11-05"
    assert match_stage["date"]["$lte"] == "2026-11-20"
    assert match_stage["emp_code"] == {"$in": ["EMP2001"]}


def test_department_trend_validation_missing_parameters(mock_analytics_service):
    """Verifies missing required parameters raise 422."""
    service, _, _ = mock_analytics_service

    # Missing department
    with pytest.raises(HTTPException) as exc_info:
        service.explain(endpoint="department_trend", department=None, from_date="2026-10-01", to_date="2026-10-31")
    assert exc_info.value.status_code == 422
    assert "required" in exc_info.value.detail

    # Missing from_date
    with pytest.raises(HTTPException) as exc_info:
        service.explain(endpoint="department_trend", department="Engineering", from_date=None, to_date="2026-10-31")
    assert exc_info.value.status_code == 422

    # Missing to_date
    with pytest.raises(HTTPException) as exc_info:
        service.explain(endpoint="department_trend", department="Engineering", from_date="2026-10-01", to_date=None)
    assert exc_info.value.status_code == 422


def test_department_trend_validation_invalid_date_range(mock_analytics_service):
    """Verifies inverted dates (to < from) and excessive range (>92 days) raise 422."""
    service, _, _ = mock_analytics_service

    # to < from
    with pytest.raises(HTTPException) as exc_info:
        service.explain(endpoint="department_trend", department="Engineering", from_date="2026-10-31", to_date="2026-10-01")
    assert exc_info.value.status_code == 422
    assert "greater than or equal to" in exc_info.value.detail

    # Range > 92 days
    with pytest.raises(HTTPException) as exc_info:
        service.explain(endpoint="department_trend", department="Engineering", from_date="2026-01-01", to_date="2026-05-01")
    assert exc_info.value.status_code == 422
    assert "92 days" in exc_info.value.detail


def test_department_trend_nonexistent_department_404(mock_analytics_service):
    """Verifies querying a non-existent department raises 404."""
    service, _, mock_emp_repo = mock_analytics_service
    mock_emp_repo.get_department_employees.return_value = []

    with pytest.raises(HTTPException) as exc_info:
        service.explain(endpoint="department_trend", department="NonExistentDept", from_date="2026-10-01", to_date="2026-10-31")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Department not found"


def test_department_trend_bson_serialization():
    """Verifies explain response containing BSON Timestamp and Binary is JSON-serializable."""
    from fastapi.encoders import jsonable_encoder

    from app.repositories.analytics_repository import AnalyticsRepository

    raw_mongo_res = {
        "executionStats": {
            "executionSuccess": True,
            "nReturned": 1,
        },
        "$clusterTime": {
            "clusterTime": Timestamp(1791619768, 1),
            "signature": {
                "hash": Binary(b"\x12\x34\x56\x78"),
                "keyId": 7647268035933241000,
            },
        },
        "operationTime": Timestamp(1791619768, 1),
    }

    mock_db = MagicMock()
    mock_db.command.return_value = raw_mongo_res
    repo = AnalyticsRepository(mock_db)
    serialized_explain = repo.explain_command("attendance_logs", {"aggregate": "attendance_logs"})

    payload = {
        "endpoint": "department_trend",
        "collection": "attendance_logs",
        "explain": serialized_explain,
    }

    # Should serialize without TypeError / ValueError
    encoded = jsonable_encoder(payload)
    assert encoded["endpoint"] == "department_trend"
    assert encoded["explain"]["executionStats"]["executionSuccess"] is True
    assert "clusterTime" in encoded["explain"]["$clusterTime"]
    assert "$timestamp" in encoded["explain"]["$clusterTime"]["clusterTime"]
    assert "$binary" in encoded["explain"]["$clusterTime"]["signature"]["hash"]


def test_admin_router_parameter_alias_mapping():
    """Verifies the FastAPI route accepts 'from', 'from_date', and 'date_from' aliases."""
    from app.api.dependencies import get_analytics_service

    mock_service = MagicMock()
    mock_service.explain.return_value = {
        "endpoint": "department_trend",
        "collection": "attendance_logs",
        "explain": {"executionStats": {"executionSuccess": True}},
    }

    app.dependency_overrides[get_analytics_service] = lambda: mock_service
    client = TestClient(app)

    try:
        # Standard alias 'from' and 'to'
        res1 = client.get("/admin/explain/department_trend?department=Engineering&from=2026-10-01&to=2026-10-31")
        assert res1.status_code == 200
        call_kwargs1 = mock_service.explain.call_args[1]
        assert call_kwargs1["from_date"] == "2026-10-01"
        assert call_kwargs1["to_date"] == "2026-10-31"

        # Alias 'from_date' and 'to_date'
        res2 = client.get("/admin/explain/department_trend?department=Engineering&from_date=2026-10-01&to_date=2026-10-31")
        assert res2.status_code == 200
        call_kwargs2 = mock_service.explain.call_args[1]
        assert call_kwargs2["from_date"] == "2026-10-01"
        assert call_kwargs2["to_date"] == "2026-10-31"

        # Alias 'date_from' and 'date_to'
        res3 = client.get("/admin/explain/department_trend?department=Engineering&date_from=2026-10-01&date_to=2026-10-31")
        assert res3.status_code == 200
        call_kwargs3 = mock_service.explain.call_args[1]
        assert call_kwargs3["from_date"] == "2026-10-01"
        assert call_kwargs3["to_date"] == "2026-10-31"
    finally:
        app.dependency_overrides.clear()
