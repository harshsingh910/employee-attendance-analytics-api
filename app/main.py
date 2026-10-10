"""
Employee Attendance & Analytics REST API (Portfolio Version)

Modular FastAPI entry point that registers authoritative routers,
connection lifecycles, and middleware.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.routers import (
    admin_router,
    analytics_router,
    attendance_router,
    employees_router,
    health_router,
)
from app.core.config import settings
from app.core.logging import logger
from app.db.indexes import create_indexes
from app.db.mongodb import close_mongo_client, get_database
from app.db.redis import close_redis_client
from app.middleware import CorrelationIdMiddleware, RateLimitMiddleware
from app.schemas.analytics import (
    DepartmentSummary,
    DepartmentSummaryItem,
    EmployeeMonthly,
    Leaderboard,
    LeaderboardItem,
    Trend,
    TrendItem,
)
from app.schemas.attendance import (
    AttendancePage,
    AttendanceRecord,
    HistoryEntry,
    PunchInRequest,
    PunchOutRequest,
    RegularizeRequest,
)
from app.schemas.common import ErrorResponse, ValidationErrorResponse
from app.schemas.employee import Employee, EmployeeCreate, EmployeePage
from app.utils.datetime_utils import (
    IST,
    from_epoch_ms,
    get_attendance_date,
    round_half_up,
    to_epoch_ms,
    to_ist,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager: initializes database client and indexes,
    then closes database and Redis connections on shutdown.
    Fails fast if mandatory index creation fails.
    """
    logger.info("Starting up application; verifying database and indexes...")
    database = get_database()
    try:
        create_indexes(database)
    except Exception as exc:
        logger.critical("Mandatory index initialization failed during startup: %s", exc)
        raise RuntimeError(f"Database index initialization failure: {exc}") from exc
    yield
    logger.info("Shutting down application; closing database connections...")
    close_mongo_client()
    close_redis_client()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# Request tracing and correlation ID middleware
app.add_middleware(CorrelationIdMiddleware)

# Cross-Origin Resource Sharing (explicitly configured origins, prevent wildcard with credentials)
cors_has_wildcard = "*" in settings.CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=not cors_has_wildcard,  # Wildcard origins cannot be combined with credentialed CORS
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Extended mode: Register Redis-backed rate limiting middleware
if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(RateLimitMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catches unhandled exceptions and sanitizes 500 responses without exposing internals."""
    req_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        "Unhandled exception [req_id=%s] on %s %s: %s",
        req_id,
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    headers = {"X-Request-ID": req_id} if req_id != "unknown" else {}
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )


# Authoritative Router Registration (One Authoritative Handler Per Endpoint)
app.include_router(health_router)
app.include_router(employees_router)
app.include_router(attendance_router)
app.include_router(analytics_router)
app.include_router(admin_router)

# Compatibility re-exports for test runners and helper scripts
get_db = get_database

__all__ = [
    "app",
    "get_db",
    "create_indexes",
    "IST",
    "round_half_up",
    "to_epoch_ms",
    "from_epoch_ms",
    "to_ist",
    "get_attendance_date",
    "EmployeeCreate",
    "Employee",
    "EmployeePage",
    "PunchInRequest",
    "PunchOutRequest",
    "RegularizeRequest",
    "HistoryEntry",
    "AttendanceRecord",
    "AttendancePage",
    "EmployeeMonthly",
    "DepartmentSummaryItem",
    "DepartmentSummary",
    "LeaderboardItem",
    "Leaderboard",
    "TrendItem",
    "Trend",
    "ErrorResponse",
    "ValidationErrorResponse",
]
