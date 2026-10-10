"""
Correlation ID Middleware for Distributed Request Tracing
Reads existing X-Request-ID header or generates a standard UUID4,
injects it into request state, and attaches it to response headers.
"""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware ensuring every HTTP interaction carries a traceable correlation ID.
    Exposes X-Request-ID in response headers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID")
        if not req_id or not req_id.strip():
            req_id = str(uuid.uuid4())
        else:
            req_id = req_id.strip()

        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response
