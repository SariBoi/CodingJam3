"""
Core module for Spark LMS backend.

This module contains core functionality including:
- Configuration management
- Database connections
- Security utilities (JWT, password hashing)
"""

from .config import settings
from .database import get_db, engine, SessionLocal
from .security import (
    create_access_token,
    verify_password,
    get_password_hash,
    verify_token
)

__all__ = [
    "settings",
    "get_db",
    "engine",
    "SessionLocal",
    "create_access_token",
    "verify_password",
    "get_password_hash",
    "verify_token"
]