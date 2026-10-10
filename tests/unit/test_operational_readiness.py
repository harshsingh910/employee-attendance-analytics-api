"""
Unit Tests for Operational Readiness, Health Probes, Tracing, and Strict Validation
Verifies /health/live, /health/ready, correlation IDs, calendar date validation,
and startup index failure enforcement.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app, lifespan


def test_liveness_probe(client: TestClient):
    """GET /health/live must succeed without external database dependencies."""
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "alive"}


def test_readiness_probe_success(client: TestClient):
    """GET /health/ready must return ok when MongoDB is reachable."""
    res = client.get("/health/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["checks"]["mongodb"] == "ok"


def test_correlation_id_tracing(client: TestClient):
    """Verifies that requests receive X-Request-ID and custom headers are preserved."""
    # Auto-generated correlation ID
    res = client.get("/health/live")
    assert "X-Request-ID" in res.headers
    assert len(res.headers["X-Request-ID"]) > 10

    # Custom supplied correlation ID
    custom_id = "test-correlation-uuid-9876"
    res2 = client.get("/health/live", headers={"X-Request-ID": custom_id})
    assert res2.headers["X-Request-ID"] == custom_id


def test_calendar_date_validation_rejects_impossible_dates(client: TestClient):
    """Verifies that impossible calendar dates (like 2026-02-30) are rejected with HTTP 422."""
    # 1. Invalid joined_on date in employee creation
    payload = {
        "emp_code": "EMP0301",
        "name": "Invalid Date Tester",
        "email": "invaliddate@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-02-30",  # February 30th does not exist!
    }
    res = client.post("/employees", json=payload)
    assert res.status_code == 422

    # 2. Invalid date_from in list_attendance
    res2 = client.get("/attendance?date_from=2026-02-31")
    assert res2.status_code == 422

    # 3. Date range exceeding 366 days in list_attendance
    res3 = client.get("/attendance?date_from=2024-01-01&date_to=2026-01-01")
    assert res3.status_code == 422

    # 4. Reversed date range (date_from > date_to)
    res_rev = client.get("/attendance?date_from=2026-03-15&date_to=2026-03-01")
    assert res_rev.status_code == 422
    assert "date_from must not be after date_to" in res_rev.json()["detail"]

    # 5. Invalid pagination boundaries
    res_p0 = client.get("/attendance?page=0")
    assert res_p0.status_code == 422
    res_ps0 = client.get("/attendance?page_size=0")
    assert res_ps0.status_code == 422
    res_ps_large = client.get("/attendance?page_size=101")
    assert res_ps_large.status_code == 422

    # 6. Invalid calendar date in regularization path parameter
    res4 = client.patch(
        "/attendance/EMP0301/2026-02-31",
        json={"reason": "Fixing punch", "regularized_by": "HR001"},
    )
    assert res4.status_code == 422


def test_sanitized_500_error_response_does_not_leak_internals():
    """Unhandled internal errors must return sanitized 500 responses with X-Request-ID and no stack trace."""
    no_raise_client = TestClient(app, raise_server_exceptions=False)
    with patch("app.services.employee_service.EmployeeService.list_employees", side_effect=Exception("Database password=secret123 failed!")):
        res = no_raise_client.get("/employees")
        assert res.status_code == 500
        data = res.json()
        assert data["detail"] == "Internal server error"
        assert "password" not in str(data)
        assert "secret123" not in str(data)
        assert "Traceback" not in str(data)
        assert "X-Request-ID" in res.headers



@pytest.mark.asyncio
async def test_startup_fails_fast_on_mandatory_index_failure():
    """Application startup must fail fast with RuntimeError if mandatory index creation fails."""
    with patch("app.main.create_indexes", side_effect=RuntimeError("Unique constraint collision on startup")):
        with pytest.raises(RuntimeError) as exc_info:
            async with lifespan(app):
                pass
        assert "Database index initialization failure" in str(exc_info.value)


def test_cors_configuration_safe_origins_and_no_wildcard_credentials(client: TestClient):
    """Verifies that CORS origins default to explicit localhost URLs and never combine wildcard with credentials."""
    from starlette.middleware.cors import CORSMiddleware

    from app.core.config import settings

    # Default configured origins must be explicit list, not wildcard
    assert "*" not in settings.CORS_ORIGINS
    assert any("localhost" in origin or "127.0.0.1" in origin for origin in settings.CORS_ORIGINS)

    # Inspect app middleware stack to ensure CORSMiddleware is mounted with safe credentials policy
    cors_mw = next((m for m in app.user_middleware if m.cls is CORSMiddleware), None)
    assert cors_mw is not None
    allow_origins = cors_mw.kwargs.get("allow_origins", [])
    allow_credentials = cors_mw.kwargs.get("allow_credentials", False)
    if "*" in allow_origins:
        assert allow_credentials is False
    else:
        assert allow_credentials is True

    # Test HTTP OPTIONS preflight from trusted origin
    res_trusted = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_trusted.status_code == 200
    assert res_trusted.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert res_trusted.headers.get("access-control-allow-credentials") == "true"

    # Test HTTP OPTIONS preflight from untrusted origin (should not allow access)
    res_untrusted = client.options(
        "/health",
        headers={
            "Origin": "http://untrusted-malicious-site.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_untrusted.headers.get("access-control-allow-origin") is None

