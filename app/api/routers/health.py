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
