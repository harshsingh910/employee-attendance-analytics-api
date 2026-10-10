"""
MongoDB Client and Database Connection Lifecycle
"""
import re
from typing import Optional

from pymongo import MongoClient

from app.core.config import settings
from app.core.logging import logger

_client: Optional[MongoClient] = None


def _sanitize_uri(uri: str) -> str:
    """Masks credentials in MongoDB connection string for safe logging."""
    return re.sub(r":([^/@]+)@", r":****@", uri)


def get_mongo_client() -> MongoClient:
    global _client
    if _client is None:
        logger.info("Initializing MongoClient with URI: %s", _sanitize_uri(settings.MONGO_URI))
        _client = MongoClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=settings.MONGO_SERVER_SELECTION_TIMEOUT_MS,
            tz_aware=True,
        )
    return _client


def get_database():
    client = get_mongo_client()
    return client[settings.MONGO_DB]


def close_mongo_client():
    global _client
    if _client is not None:
        logger.info("Closing MongoClient")
        _client.close()
        _client = None


def ping_database() -> bool:
    client = get_mongo_client()
    client.admin.command("ping")
    return True
