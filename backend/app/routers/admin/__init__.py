"""
Admin routers for Spark LMS.

This module contains all admin-specific API endpoints:
- courses: Admin course management (CRUD)
- chapters: Admin chapter management with node-based workflow
- segments: Admin segment management for creating content
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user

# Import admin sub-routers
from .courses import router as courses_router
from .chapters import router as chapters_router
from .segments import router as segments_router


# Dependency to verify admin access
async def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Verify that the current user has admin privileges.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


# Create admin router
admin_router = APIRouter()

# Include all admin sub-routers
admin_router.include_router(
    courses_router,
    prefix="/courses",
    tags=["admin-courses"],
    dependencies=[Depends(get_current_admin_user)]
)

admin_router.include_router(
    chapters_router,
    prefix="/chapters",
    tags=["admin-chapters"],
    dependencies=[Depends(get_current_admin_user)]
)

admin_router.include_router(
    segments_router,
    prefix="/segments",
    tags=["admin-segments"],
    dependencies=[Depends(get_current_admin_user)]
)


# Admin dashboard endpoint
@admin_router.get("/dashboard")
async def get_admin_dashboard(
    admin_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Get admin dashboard overview with statistics.
    """
    from app.models.course import Course, Chapter, Segment, ContentStatus
    from app.models.progress import UserProgress
    from app.models.admin import CourseAnalytics
    from sqlalchemy import func
    
    # Get counts
    total_courses = db.query(Course).count()
    published_courses = db.query(Course).filter(
        Course.status == ContentStatus.PUBLISHED.value
    ).count()
    draft_courses = db.query(Course).filter(
        Course.status == ContentStatus.DRAFT.value
    ).count()
    
    total_chapters = db.query(Chapter).count()
    total_segments = db.query(Segment).count()
    
    # Get user statistics
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    verified_users = db.query(User).filter(User.is_verified == True).count()
    
    # Get enrollment statistics
    total_enrollments = db.query(UserProgress).count()
    completed_courses = db.query(UserProgress).filter(
        UserProgress.status == "completed"
    ).count()
    
    # Get recent analytics
    recent_analytics = db.query(CourseAnalytics).order_by(
        CourseAnalytics.created_at.desc()
    ).limit(5).all()
    
    # Get popular courses
    popular_courses = db.query(
        Course.id,
        Course.title,
        Course.enrolled_count,
        Course.average_rating
    ).order_by(
        Course.enrolled_count.desc()
    ).limit(5).all()
    
    return {
        "statistics": {
            "courses": {
                "total": total_courses,
                "published": published_courses,
                "draft": draft_courses
            },
            "content": {
                "chapters": total_chapters,
                "segments": total_segments
            },
            "users": {
                "total": total_users,
                "active": active_users,
                "verified": verified_users
            },
            "enrollments": {
                "total": total_enrollments,
                "completed": completed_courses,
                "completion_rate": (completed_courses / total_enrollments * 100) if total_enrollments > 0 else 0
            }
        },
        "popular_courses": [
            {
                "id": course.id,
                "title": course.title,
                "enrolled_count": course.enrolled_count,
                "average_rating": course.average_rating
            }
            for course in popular_courses
        ],
        "recent_activity": {
            "last_login": admin_user.last_login_at.isoformat() if admin_user.last_login_at else None,
            "recent_analytics": [
                {
                    "course_id": analytics.course_id,
                    "period_type": analytics.period_type,
                    "unique_users": analytics.unique_users,
                    "new_enrollments": analytics.new_enrollments,
                    "avg_progress": analytics.avg_progress,
                    "created_at": analytics.created_at.isoformat()
                }
                for analytics in recent_analytics
            ]
        }
    }


# System settings endpoints
@admin_router.get("/settings")
async def get_system_settings(
    admin_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Get all system settings.
    """
    from app.models.admin import SystemSettings
    
    settings = db.query(SystemSettings).all()
    
    # Group by category
    settings_by_category = {}
    for setting in settings:
        if setting.category not in settings_by_category:
            settings_by_category[setting.category] = []
        
        settings_by_category[setting.category].append({
            "id": setting.id,
            "key": setting.key,
            "value": setting.get_typed_value(),
            "value_type": setting.value_type,
            "description": setting.description,
            "is_editable": setting.is_editable,
            "validation_rules": setting.validation_rules
        })
    
    return settings_by_category


@admin_router.put("/settings/{setting_key}")
async def update_system_setting(
    setting_key: str,
    value: dict,
    admin_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Update a system setting.
    """
    from app.models.admin import SystemSettings, AdminLog, AdminAction
    
    setting = db.query(SystemSettings).filter(
        SystemSettings.key == setting_key
    ).first()
    
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Setting not found"
        )
    
    if not setting.is_editable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This setting cannot be edited"
        )
    
    # Validate value if rules exist
    if setting.validation_rules:
        # Implement validation based on rules
        pass
    
    # Update setting
    old_value = setting.get_typed_value()
    setting.set_typed_value(value["value"])
    setting.last_modified_by = admin_user.id
    
    # Log the change
    admin_log = AdminLog.log_action(
        user_id=admin_user.id,
        action=AdminAction.SETTINGS_CHANGE,
        entity_type="system_settings",
        entity_id=setting.id,
        details={
            "setting_key": setting_key,
            "old_value": old_value,
            "new_value": value["value"]
        }
    )
    db.add(admin_log)
    
    db.commit()
    
    return {
        "message": "Setting updated successfully",
        "setting": {
            "key": setting.key,
            "value": setting.get_typed_value(),
            "updated_at": setting.updated_at.isoformat()
        }
    }


# Admin logs endpoint
@admin_router.get("/logs")
async def get_admin_logs(
    skip: int = 0,
    limit: int = 50,
    action: str = None,
    entity_type: str = None,
    admin_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    Get admin action logs with filtering.
    """
    from app.models.admin import AdminLog
    
    query = db.query(AdminLog)
    
    # Apply filters
    if action:
        query = query.filter(AdminLog.action == action)
    if entity_type:
        query = query.filter(AdminLog.entity_type == entity_type)
    
    # Get total count
    total = query.count()
    
    # Get logs with pagination
    logs = query.order_by(
        AdminLog.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "success": log.success,
                "error_message": log.error_message,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat()
            }
            for log in logs
        ]
    }


# Export all routers
__all__ = ["admin_router", "get_current_admin_user"]