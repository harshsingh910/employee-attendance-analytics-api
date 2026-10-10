"""
Unit, Concurrency, and Isolation Tests for Redis Rate Limiter Middleware
Covers Section C:
- Allowed requests and rate limit headers
- Rate limit exhaustion (HTTP 429)
- Retry-After header format and values
- Window expiration and counter reset
- Path exemption (/health)
- Fail-closed behavior on Redis outages (HTTP 503)
- Client IP isolation
- Path isolation
- Trusted vs untrusted proxy header security
- Thread concurrency safety under burst loads
"""
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
import redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limit import RateLimitMiddleware


def create_test_app(redis_client, limit=5, window=2, trusted_proxies=None):
    test_app = FastAPI()
    test_app.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_client,
        requests_limit=limit,
        window_seconds=window,
        trusted_proxies=trusted_proxies or [],
        exempt_paths=["/health"],
        enabled=True,
    )

    @test_app.get("/health")
    def health():
        return {"status": "ok"}

    @test_app.get("/api/resource1")
    def resource1():
        return {"resource": "1"}

    @test_app.get("/api/resource2")
    def resource2():
        return {"resource": "2"}

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

    res = client.get("/api/resource1")
    assert res.status_code == 200
    assert res.headers["X-RateLimit-Limit"] == "5"
    assert res.headers["X-RateLimit-Remaining"] == "4"
    assert int(res.headers["X-RateLimit-Reset"]) > 0


def test_rate_limiter_exhaustion_429(redis_conn):
    app = create_test_app(redis_conn, limit=3, window=2)
    client = TestClient(app)

    for _ in range(3):
        res = client.get("/api/resource1")
        assert res.status_code == 200

    res = client.get("/api/resource1")
    assert res.status_code == 429
    assert "Rate limit exceeded" in res.json()["detail"]
    assert "Retry-After" in res.headers
    assert int(res.headers["Retry-After"]) >= 1


def test_rate_limiter_window_expiration(redis_conn):
    app = create_test_app(redis_conn, limit=2, window=1)
    client = TestClient(app)

    assert client.get("/api/resource1").status_code == 200
    assert client.get("/api/resource1").status_code == 200
    assert client.get("/api/resource1").status_code == 429

    time.sleep(1.2)

    res = client.get("/api/resource1")
    assert res.status_code == 200
    assert res.headers["X-RateLimit-Remaining"] == "1"


def test_rate_limiter_exempt_paths(redis_conn):
    app = create_test_app(redis_conn, limit=1, window=10)
    client = TestClient(app)

    assert client.get("/api/resource1").status_code == 200
    assert client.get("/api/resource1").status_code == 429

    for _ in range(5):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


def test_rate_limiter_redis_failure_fails_closed():
    mock_redis = MagicMock()
    mock_redis.register_script.side_effect = redis.ConnectionError("Redis connection refused")

    app = create_test_app(mock_redis, limit=5, window=10)
    client = TestClient(app)

    res = client.get("/api/resource1")
    assert res.status_code == 503
    assert "Rate limiting backend service temporarily unavailable" in res.json()["detail"]
    assert client.get("/health").status_code == 200


def test_rate_limiter_path_isolation(redis_conn):
    # Same client hitting two different paths has separate quotas
    app = create_test_app(redis_conn, limit=2, window=10)
    client = TestClient(app)

    # Exhaust resource1
    assert client.get("/api/resource1").status_code == 200
    assert client.get("/api/resource1").status_code == 200
    assert client.get("/api/resource1").status_code == 429

    # resource2 is still completely available for the same client
    assert client.get("/api/resource2").status_code == 200
    assert client.get("/api/resource2").status_code == 200
    assert client.get("/api/resource2").status_code == 429


def test_rate_limiter_client_isolation(redis_conn):
    # Two different clients have independent limits on the same path
    app = create_test_app(redis_conn, limit=2, window=10, trusted_proxies=["127.0.0.1", "testclient"])
    client = TestClient(app)

    # Client A exhausts quota
    headers_a = {"X-Forwarded-For": "198.51.100.1"}
    assert client.get("/api/resource1", headers=headers_a).status_code == 200
    assert client.get("/api/resource1", headers=headers_a).status_code == 200
    assert client.get("/api/resource1", headers=headers_a).status_code == 429

    # Client B should NOT be affected
    headers_b = {"X-Forwarded-For": "198.51.100.2"}
    assert client.get("/api/resource1", headers=headers_b).status_code == 200
    assert client.get("/api/resource1", headers=headers_b).status_code == 200
    assert client.get("/api/resource1", headers=headers_b).status_code == 429


def test_rate_limiter_untrusted_proxy_ignores_forwarded_for(redis_conn):
    # If peer is NOT in trusted_proxies, X-Forwarded-For header is ignored
    app = create_test_app(redis_conn, limit=2, window=10, trusted_proxies=[])  # empty trusted list
    client = TestClient(app)

    # Try spoofing X-Forwarded-For
    h1 = {"X-Forwarded-For": "10.0.0.1"}
    h2 = {"X-Forwarded-For": "10.0.0.2"}

    assert client.get("/api/resource1", headers=h1).status_code == 200
    assert client.get("/api/resource1", headers=h2).status_code == 200
    # 3rd request from same client (even with new spoofed header) must be blocked because peer IP is shared
    assert client.get("/api/resource1", headers={"X-Forwarded-For": "10.0.0.3"}).status_code == 429


def test_rate_limiter_concurrent_burst_safety(redis_conn):
    limit = 5
    app = create_test_app(redis_conn, limit=limit, window=10)
    client = TestClient(app)

    def send_request(_):
        return client.get("/api/resource1").status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        statuses = list(executor.map(send_request, range(15)))

    # Exactly `limit` requests must succeed, and the remaining must be 429
    assert statuses.count(200) == limit
    assert statuses.count(429) == 15 - limit
