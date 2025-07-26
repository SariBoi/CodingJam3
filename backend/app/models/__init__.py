"""
Database models for Spark LMS.

This module contains all SQLAlchemy models for the application:
- User models for authentication and profiles
- Course models for learning content structure
- Progress models for tracking user progress
- Admin models for administrative features
"""

from app.core.database import Base

# Import all models to ensure they're registered with SQLAlchemy
from .user import User
from .course import Course, Chapter, Segment, ChapterPath
from .progress import UserProgress, SegmentAttempt, UserScore, UserXP
from .admin import AdminLog, CourseAnalytics, SystemSettings

# Export all models
__all__ = [
    "Base",
    "User",
    "Course",
    "Chapter",
    "Segment",
    "ChapterPath",
    "UserProgress",
    "SegmentAttempt",
    "UserScore",
    "UserXP",
    "AdminLog",
    "CourseAnalytics",
    "SystemSettings"
]