"""
Health Check Router
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.api.dependencies import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
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
