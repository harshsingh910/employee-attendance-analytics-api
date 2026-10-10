"""
Redis Client Connection Lifecycle
"""
from typing import Optional

import redis

from app.core.config import settings
from app.core.logging import logger

_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """
    Returns a singleton Redis client instance with socket timeouts configured.
    """
    global _redis_client
    if _redis_client is None:
        logger.info("Initializing Redis client with URL: %s", settings.REDIS_URL)
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
            decode_responses=True,
        )
    return _redis_client


def close_redis_client():
    """Closes the Redis connection cleanly."""
    global _redis_client
    if _redis_client is not None:
        logger.info("Closing Redis client")
        try:
            _redis_client.close()
        except Exception as e:
            logger.warning("Error closing Redis client: %s", e)
        _redis_client = None


def ping_redis() -> bool:
    """Returns True if Redis is reachable, False otherwise."""
    try:
        client = get_redis_client()
        return bool(client.ping())
    except Exception as e:
        logger.error("Redis ping failed: %s", e)
        return False
