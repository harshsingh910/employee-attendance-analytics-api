"""
API Routers Export
"""
from app.api.routers.admin import router as admin_router
from app.api.routers.analytics import router as analytics_router
from app.api.routers.attendance import router as attendance_router
from app.api.routers.employees import router as employees_router
from app.api.routers.health import router as health_router

__all__ = [
    "health_router",
    "employees_router",
    "attendance_router",
    "analytics_router",
    "admin_router",
]
