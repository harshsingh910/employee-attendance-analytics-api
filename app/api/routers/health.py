"""
Health Check Router
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.api.dependencies import get_db
from app.schemas.common import ErrorResponse

router = APIRouter(tags=["system"])


@router.get("/health", responses={503: {"model": ErrorResponse, "description": "Database unavailable"}})
def health(db: Database = Depends(get_db)):
    """Health check endpoint verifying MongoDB connectivity."""
    try:
        db.client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )


@router.get("/health/live", include_in_schema=False)
def liveness():
    """Liveness probe: verifies process is alive without external service dependency."""
    return {"status": "alive"}


@router.get("/health/ready", include_in_schema=False)
def readiness(db: Database = Depends(get_db)):
    """Readiness probe: verifies critical dependencies (MongoDB, and Redis if enabled)."""
    from app.core.config import settings
    checks = {}
    is_ready = True

    try:
        db.client.admin.command("ping")
        checks["mongodb"] = "ok"
    except Exception as exc:
        checks["mongodb"] = f"unavailable: {exc}"
        is_ready = False

    if settings.RATE_LIMIT_ENABLED:
        from app.db.redis import ping_redis

        if ping_redis():
            checks["redis"] = "ok"
        else:
            checks["redis"] = "unavailable"
            is_ready = False
    else:
        checks["redis"] = "skipped"

    if not is_ready:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service dependencies not ready",
        )

    return {"status": "ready", "checks": checks}
