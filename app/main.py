"""
Employee Attendance & Analytics REST API (Portfolio Version)

Modular FastAPI entry point that registers authoritative routers,
connection lifecycles, and middleware.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
from app.middleware.rate_limit import RateLimitMiddleware
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
    """
    logger.info("Starting up application; verifying database and indexes...")
    database = get_database()
    try:
        create_indexes(database)
    except Exception as exc:
        logger.warning("Index initialization notice during startup: %s", exc)
    yield
    logger.info("Shutting down application; closing database connections...")
    close_mongo_client()
    close_redis_client()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# Extended mode: Register Redis-backed rate limiting middleware
if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(RateLimitMiddleware)

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
