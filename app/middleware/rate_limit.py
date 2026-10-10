"""
Redis-Backed Rate Limiting Middleware
"""
from typing import Any, List, Optional

import redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import logger
from app.db.redis import get_redis_client

# Atomic Lua script: increments counter and sets TTL on first access
# Returns {current_count, ttl_remaining}
RATE_LIMIT_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])

local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, window)
end
local ttl = redis.call('TTL', key)
if ttl < 0 then
    redis.call('EXPIRE', key, window)
    ttl = window
end
return {current, ttl}
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware providing atomic Redis-backed rate limiting per IP address.
    Exempts /health and API documentation paths.
    Fails closed with HTTP 503 if Redis is unreachable when rate limiting is active.
    """

    def __init__(
        self,
        app,
        redis_client: Optional[redis.Redis] = None,
        requests_limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
        trusted_proxies: Optional[List[str]] = None,
        exempt_paths: Optional[List[str]] = None,
        enabled: Optional[bool] = None,
    ):
        super().__init__(app)
        self.redis_client = redis_client
        self.limit = requests_limit or settings.RATE_LIMIT_REQUESTS
        self.window = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS
        self.trusted_proxies = trusted_proxies or []
        self.exempt_paths = exempt_paths or [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
        self.enabled = enabled if enabled is not None else settings.RATE_LIMIT_ENABLED
        self._lua_script: Any = None

    def _get_client_ip(self, request: Request) -> str:
        """
        Safely extract client IP. Only inspects X-Forwarded-For if direct peer
        is in trusted_proxies list to avoid IP spoofing.
        """
        client_host = request.client.host if request.client else "127.0.0.1"
        if client_host in self.trusted_proxies:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return client_host

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check if rate limiting is disabled
        if not self.enabled:
            return await call_next(request)

        # Check path exemption (e.g. /health)
        path = request.url.path
        if any(path == exempt or path.startswith(exempt + "/") for exempt in self.exempt_paths):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        key = f"rate_limit:{client_ip}:{path}"

        try:
            r = self.redis_client or get_redis_client()
            if self._lua_script is None:
                self._lua_script = r.register_script(RATE_LIMIT_LUA)

            result = self._lua_script(keys=[key], args=[self.limit, self.window])
            current_count, ttl = int(result[0]), int(result[1])

            if current_count > self.limit:
                retry_after = max(1, ttl)
                logger.warning(
                    "Rate limit exceeded for IP %s on %s (count: %d, limit: %d)",
                    client_ip,
                    path,
                    current_count,
                    self.limit,
                )
                headers = {
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                }
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded. Maximum {self.limit} requests per {self.window}s. Retry after {retry_after}s."
                    },
                    headers=headers,
                )

            # Request allowed: execute endpoint and inject rate limit headers
            response = await call_next(request)
            remaining = max(0, self.limit - current_count)
            response.headers["X-RateLimit-Limit"] = str(self.limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(max(1, ttl))
            return response

        except (redis.ConnectionError, redis.TimeoutError) as exc:
            logger.error("Redis rate limiter unavailable: %s", exc)
            # Fail closed to prevent bypassing required limits during an outage
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Rate limiting backend service temporarily unavailable. Request throttled for protection."
                },
            )
        except Exception as exc:
            logger.error("Unexpected error in RateLimitMiddleware: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error during rate limit verification."},
            )
