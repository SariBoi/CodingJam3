"""
API routers for Spark LMS.

This module contains all API endpoint routers:
- auth: Authentication endpoints (login, register, logout)
- courses: User-facing course endpoints
- progress: User progress and XP tracking
- admin: Administrative endpoints for content management
"""

from fastapi import APIRouter

# Import individual routers
from .auth import router as auth_router
from .courses import router as courses_router
from .progress import router as progress_router

# Import admin sub-routers
from .admin import admin_router

# Create main API router
api_router = APIRouter()

# Include all routers with their prefixes
api_router.include_router(
    auth_router,
    prefix="/auth",
    tags=["authentication"]
)

api_router.include_router(
    courses_router,
    prefix="/courses",
    tags=["courses"]
)

api_router.include_router(
    progress_router,
    prefix="/progress",
    tags=["progress"]
)

api_router.include_router(
    admin_router,
    prefix="/admin",
    tags=["admin"]
)

# Export all routers
__all__ = [
    "api_router",
    "auth_router",
    "courses_router",
    "progress_router",
    "admin_router"
]