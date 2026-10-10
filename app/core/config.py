"""
Application Configuration and Settings
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.PROJECT_NAME: str = "Employee Attendance & Analytics API"
        self.VERSION: str = "2.0.0"
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

        # MongoDB settings
        self.MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.MONGO_DB: str = os.getenv("MONGO_DB", "attendance_db")
        self.MONGO_SERVER_SELECTION_TIMEOUT_MS: int = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "2000"))

        # Redis settings
        self.REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.REDIS_TIMEOUT_SECONDS: float = float(os.getenv("REDIS_TIMEOUT_SECONDS", "2.0"))

        # Rate Limiting
        self.RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
        self.RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
        self.RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
        self.TRUST_PROXY_HEADERS: bool = os.getenv("TRUST_PROXY_HEADERS", "false").lower() in ("true", "1", "yes")

        # Celery settings
        self.CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        self.CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://localhost:6379/1"))

        # CORS Configuration: Safe default trusted origins for local frontend/API development
        # In production, set CORS_ORIGINS to explicit HTTPS origins (e.g., https://app.example.com)
        raw_origins = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:8000",
        )
        self.CORS_ORIGINS: list[str] = [
            origin.strip() for origin in raw_origins.split(",") if origin.strip()
        ]


settings = Settings()
