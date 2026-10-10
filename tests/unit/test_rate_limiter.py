"""
Unit and Concurrency Tests for Redis Rate Limiter Middleware
Covers Section 7:
- Allowed requests and headers
- Rate limit exhaustion (HTTP 429)
- Retry-After header
- Key expiration
- Path exemption (/health)
- Fail closed behavior on Redis failure (HTTP 503)
"""
import time
from unittest.mock import MagicMock

import pytest
import redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limit import RateLimitMiddleware


def create_test_app(redis_client, limit=5, window=2):
    test_app = FastAPI()
    test_app.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_client,
        requests_limit=limit,
        window_seconds=window,
        exempt_paths=["/health"],
        enabled=True,
    )

    @test_app.get("/health")
    def health():
        return {"status": "ok"}

    @test_app.get("/api/resource")
    def resource():
        return {"data": "success"}

    return test_app


@pytest.fixture
def redis_conn():
    r = redis.Redis(host="127.0.0.1", port=6379, db=14, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


def test_rate_limiter_allowed_and_headers(redis_conn):
    app = create_test_app(redis_conn, limit=5, window=2)
    client = TestClient(app)

    # 1st request
    res = client.get("/api/resource")
    assert res.status_code == 200
    assert res.headers["X-RateLimit-Limit"] == "5"
    assert res.headers["X-RateLimit-Remaining"] == "4"
    assert int(res.headers["X-RateLimit-Reset"]) > 0


def test_rate_limiter_exhaustion_429(redis_conn):
    app = create_test_app(redis_conn, limit=3, window=2)
    client = TestClient(app)

    # Make 3 allowed requests
    for i in range(3):
        res = client.get("/api/resource")
        assert res.status_code == 200

    # 4th request must be rejected with 429
    res = client.get("/api/resource")
    assert res.status_code == 429
    assert "Rate limit exceeded" in res.json()["detail"]
    assert "Retry-After" in res.headers
    assert int(res.headers["Retry-After"]) >= 1


def test_rate_limiter_window_expiration(redis_conn):
    app = create_test_app(redis_conn, limit=2, window=1)
    client = TestClient(app)

    # Exhaust limit
    assert client.get("/api/resource").status_code == 200
    assert client.get("/api/resource").status_code == 200
    assert client.get("/api/resource").status_code == 429

    # Wait for window expiration
    time.sleep(1.2)

    # New request should be allowed again
    res = client.get("/api/resource")
    assert res.status_code == 200
    assert res.headers["X-RateLimit-Remaining"] == "1"


def test_rate_limiter_exempt_paths(redis_conn):
    app = create_test_app(redis_conn, limit=1, window=10)
    client = TestClient(app)

    # /health should never be throttled even after limit is reached on resource
    assert client.get("/api/resource").status_code == 200
    assert client.get("/api/resource").status_code == 429

    for _ in range(5):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


def test_rate_limiter_redis_failure_fails_closed():
    # Mock Redis client that raises ConnectionError
    mock_redis = MagicMock()
    mock_redis.register_script.side_effect = redis.ConnectionError("Redis connection refused")

    app = create_test_app(mock_redis, limit=5, window=10)
    client = TestClient(app)

    # When Redis is down, we must NOT silently bypass rate limits. Returns HTTP 503
    res = client.get("/api/resource")
    assert res.status_code == 503
    assert "Rate limiting backend service temporarily unavailable" in res.json()["detail"]

    # But health check is still reachable
    assert client.get("/health").status_code == 200
