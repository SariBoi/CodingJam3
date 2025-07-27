"""
Admin courses router for Spark LMS.

Handles admin-specific course management including CRUD operations,
publishing, analytics, and bulk operations.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_

from app.core.database import get_db
from app.models.user import User
from app.models.course import Course, Chapter, Segment, ContentStatus, DifficultyLevel
from app.models.progress import UserProgress
from app.models.admin import AdminLog, AdminAction, CourseAnalytics
from app.schemas.admin import (
    CourseCreate,
    CourseUpdate,
    CourseResponse,
    CourseListResponse,
    CourseAnalyticsResponse,
    BulkOperation,
    BulkOperationResponse
)


router = APIRouter()


@router.get("/", response_model=CourseListResponse)
async def list_courses(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query("created_at", regex="^(created_at|updated_at|title|enrolled_count)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    List all courses with filtering and sorting for admin.
    """
    # Base query
    query = db.query(Course)
    
    # Apply filters
    if status_filter:
        query = query.filter(Course.status == status_filter)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Course.title.ilike(search_term),
                Course.description.ilike(search_term),
                Course.slug.ilike(search_term)
            )
        )
    
    # Get total count
    total = query.count()
    
    # Apply sorting
    sort_column = getattr(Course, sort_by)
    if sort_order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())
    
    # Apply pagination
    courses = query.options(
        joinedload(Course.chapters)
    ).offset(skip).limit(limit).all()
    
    # Format response
    course_list = []
    for course in courses:
        # Get enrollment statistics
        enrollments = db.query(UserProgress).filter(
            UserProgress.course_id == course.id
        ).all()
        
        active_users = len([e for e in enrollments if e.status == "in_progress"])
        
        course_list.append({
            "id": course.id,
            "title": course.title,
            "slug": course.slug,
            "status": course.status,
            "difficulty_level": course.difficulty_level,
            "category": course.category,
            "author_id": course.author_id,
            "chapter_count": len([c for c in course.chapters if c.is_published]),
            "total_xp": course.total_xp,
            "enrolled_count": course.enrolled_count,
            "completion_count": course.completion_count,
            "average_rating": course.average_rating,
            "active_users": active_users,
            "is_featured": course.is_featured,
            "created_at": course.created_at.isoformat(),
            "updated_at": course.updated_at.isoformat(),
            "published_at": course.published_at.isoformat() if course.published_at else None
        })
    
    return {
        "courses": course_list,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    course_data: CourseCreate,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Course:
    """
    Create a new course.
    """
    # Check if slug already exists
    existing_course = db.query(Course).filter(
        Course.slug == course_data.slug
    ).first()
    
    if existing_course:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course with this slug already exists"
        )
    
    # Create course
    new_course = Course(
        **course_data.dict(exclude={"tags", "prerequisites"}),
        author_id=current_admin.id,
        tags=course_data.tags or [],
        prerequisites=course_data.prerequisites or [],
        status=ContentStatus.DRAFT.value
    )
    
    db.add(new_course)
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.CREATE,
        entity_type="course",
        entity_id=new_course.id,
        details={
            "course_title": new_course.title,
            "course_slug": new_course.slug
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    db.refresh(new_course)
    
    return new_course


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: int,
    db: Session = Depends(get_db)
) -> Course:
    """
    Get detailed information about a specific course.
    """
    course = db.query(Course).filter(
        Course.id == course_id
    ).options(
        joinedload(Course.chapters).joinedload(Chapter.segments)
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    return course


@router.put("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: int,
    course_update: CourseUpdate,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Course:
    """
    Update a course.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Track changes for logging
    changes = {}
    update_data = course_update.dict(exclude_unset=True)
    
    # Update fields
    for field, value in update_data.items():
        if hasattr(course, field) and getattr(course, field) != value:
            changes[field] = {
                "old": getattr(course, field),
                "new": value
            }
            setattr(course, field, value)
    
    # Update timestamp
    course.updated_at = datetime.utcnow()
    
    # Log action
    if changes:
        admin_log = AdminLog.log_action(
            user_id=current_admin.id,
            action=AdminAction.UPDATE,
            entity_type="course",
            entity_id=course_id,
            details={
                "changes": changes
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        db.add(admin_log)
    
    db.commit()
    db.refresh(course)
    
    return course


@router.delete("/{course_id}")
async def delete_course(
    course_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Delete a course (soft delete by setting status to archived).
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Check if course has active enrollments
    active_enrollments = db.query(UserProgress).filter(
        UserProgress.course_id == course_id,
        UserProgress.status == "in_progress"
    ).count()
    
    if active_enrollments > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete course with {active_enrollments} active enrollments"
        )
    
    # Soft delete by archiving
    course.status = ContentStatus.ARCHIVED.value
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.DELETE,
        entity_type="course",
        entity_id=course_id,
        details={
            "course_title": course.title,
            "enrolled_count": course.enrolled_count
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {"message": "Course archived successfully"}


@router.post("/{course_id}/publish")
async def publish_course(
    course_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Publish a course, making it available to users.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.status == ContentStatus.PUBLISHED.value:
        return {"message": "Course is already published", "status": course.status}
    
    # Validate course has at least one published chapter
    published_chapters = db.query(Chapter).filter(
        Chapter.course_id == course_id,
        Chapter.is_published == True
    ).count()
    
    if published_chapters == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course must have at least one published chapter"
        )
    
    # Update course
    course.status = ContentStatus.PUBLISHED.value
    course.published_at = datetime.utcnow()
    course.total_xp = course.calculate_total_xp()
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.PUBLISH,
        entity_type="course",
        entity_id=course_id,
        details={
            "course_title": course.title,
            "chapter_count": published_chapters
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {
        "message": "Course published successfully",
        "status": course.status,
        "published_at": course.published_at.isoformat()
    }


@router.post("/{course_id}/unpublish")
async def unpublish_course(
    course_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Unpublish a course, making it unavailable to users.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.status != ContentStatus.PUBLISHED.value:
        return {"message": "Course is not published", "status": course.status}
    
    # Update course
    course.status = ContentStatus.DRAFT.value
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.UNPUBLISH,
        entity_type="course",
        entity_id=course_id,
        details={
            "course_title": course.title,
            "enrolled_count": course.enrolled_count
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {
        "message": "Course unpublished successfully",
        "status": course.status
    }


@router.get("/{course_id}/analytics", response_model=CourseAnalyticsResponse)
async def get_course_analytics(
    course_id: int,
    period: str = Query("daily", regex="^(hourly|daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get analytics for a specific course.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Get analytics data
    analytics = db.query(CourseAnalytics).filter(
        CourseAnalytics.course_id == course_id,
        CourseAnalytics.period_type == period,
        CourseAnalytics.period_start >= datetime.utcnow() - timedelta(days=days)
    ).order_by(CourseAnalytics.period_start).all()
    
    # Get current statistics
    current_enrollments = db.query(UserProgress).filter(
        UserProgress.course_id == course_id
    ).all()
    
    active_users = len([e for e in current_enrollments if e.status == "in_progress"])
    completed_users = len([e for e in current_enrollments if e.status == "completed"])
    
    # Calculate engagement metrics
    avg_progress = sum(e.progress_percentage for e in current_enrollments) / len(current_enrollments) if current_enrollments else 0
    avg_score = sum(e.average_score for e in current_enrollments) / len(current_enrollments) if current_enrollments else 0
    
    # Format analytics data
    time_series_data = []
    for record in analytics:
        time_series_data.append({
            "period_start": record.period_start.isoformat(),
            "period_end": record.period_end.isoformat(),
            "unique_users": record.unique_users,
            "new_enrollments": record.new_enrollments,
            "completions": record.completions,
            "avg_progress": record.avg_progress,
            "avg_score": record.avg_score,
            "total_attempts": record.total_attempts
        })
    
    return {
        "course": {
            "id": course.id,
            "title": course.title,
            "status": course.status
        },
        "current_stats": {
            "total_enrolled": course.enrolled_count,
            "active_users": active_users,
            "completed_users": completed_users,
            "average_progress": avg_progress,
            "average_score": avg_score,
            "completion_rate": (completed_users / course.enrolled_count * 100) if course.enrolled_count > 0 else 0
        },
        "time_series": time_series_data,
        "period": period,
        "days": days
    }


@router.post("/duplicate/{course_id}", response_model=CourseResponse)
async def duplicate_course(
    course_id: int,
    new_title: str,
    new_slug: str,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Course:
    """
    Duplicate a course with all its chapters and segments.
    """
    # Get original course
    original_course = db.query(Course).filter(Course.id == course_id).first()
    
    if not original_course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Check if new slug exists
    if db.query(Course).filter(Course.slug == new_slug).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course with this slug already exists"
        )
    
    # Create new course
    new_course = Course(
        title=new_title,
        slug=new_slug,
        description=original_course.description,
        short_description=original_course.short_description,
        difficulty_level=original_course.difficulty_level,
        estimated_hours=original_course.estimated_hours,
        prerequisites=original_course.prerequisites,
        tags=original_course.tags,
        category=original_course.category,
        passing_score=original_course.passing_score,
        author_id=current_admin.id,
        status=ContentStatus.DRAFT.value
    )
    
    db.add(new_course)
    db.flush()  # Get the new course ID
    
    # Duplicate chapters
    chapter_mapping = {}  # old_id -> new_id
    
    for original_chapter in original_course.chapters:
        new_chapter = Chapter(
            title=original_chapter.title,
            slug=original_chapter.slug,
            description=original_chapter.description,
            course_id=new_course.id,
            node_id=original_chapter.node_id,
            position_x=original_chapter.position_x,
            position_y=original_chapter.position_y,
            order_index=original_chapter.order_index,
            estimated_minutes=original_chapter.estimated_minutes,
            difficulty_level=original_chapter.difficulty_level,
            passing_score=original_chapter.passing_score,
            is_published=False  # Start as unpublished
        )
        
        db.add(new_chapter)
        db.flush()
        
        chapter_mapping[original_chapter.id] = new_chapter.id
        
        # Duplicate segments
        for original_segment in original_chapter.segments:
            new_segment = Segment(
                title=original_segment.title,
                type=original_segment.type,
                chapter_id=new_chapter.id,
                content=original_segment.content,
                code_template=original_segment.code_template,
                test_cases=original_segment.test_cases,
                expected_output=original_segment.expected_output,
                hints=original_segment.hints,
                solution=original_segment.solution,
                mcq_questions=original_segment.mcq_questions,
                order_index=original_segment.order_index,
                xp_value=original_segment.xp_value,
                max_attempts=original_segment.max_attempts,
                required_score=original_segment.required_score,
                time_limit_seconds=original_segment.time_limit_seconds,
                is_published=False  # Start as unpublished
            )
            
            db.add(new_segment)
    
    # Duplicate chapter paths (after all chapters are created)
    db.flush()
    
    for original_chapter in original_course.chapters:
        for path in original_chapter.outgoing_paths:
            if path.to_chapter_id in chapter_mapping:
                new_path = ChapterPath(
                    from_chapter_id=chapter_mapping[original_chapter.id],
                    to_chapter_id=chapter_mapping[path.to_chapter_id],
                    condition_type=path.condition_type,
                    condition_value=path.condition_value,
                    condition_label=path.condition_label,
                    is_default=path.is_default,
                    order_priority=path.order_priority,
                    path_color=path.path_color,
                    path_style=path.path_style
                )
                db.add(new_path)
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.CREATE,
        entity_type="course",
        entity_id=new_course.id,
        details={
            "action": "course_duplication",
            "original_course_id": course_id,
            "new_course_title": new_title,
            "chapters_duplicated": len(chapter_mapping)
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    db.refresh(new_course)
    
    return new_course


@router.post("/bulk", response_model=BulkOperationResponse)
async def bulk_operation(
    operation: BulkOperation,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Perform bulk operations on multiple courses.
    """
    # Get courses
    courses = db.query(Course).filter(
        Course.id.in_(operation.course_ids)
    ).all()
    
    if len(courses) != len(operation.course_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some courses not found"
        )
    
    # Perform operation
    success_count = 0
    failed_ids = []
    
    for course in courses:
        try:
            if operation.action == "publish":
                if course.status != ContentStatus.PUBLISHED.value:
                    course.status = ContentStatus.PUBLISHED.value
                    course.published_at = datetime.utcnow()
                    success_count += 1
            
            elif operation.action == "unpublish":
                if course.status == ContentStatus.PUBLISHED.value:
                    course.status = ContentStatus.DRAFT.value
                    success_count += 1
            
            elif operation.action == "archive":
                course.status = ContentStatus.ARCHIVED.value
                success_count += 1
            
            elif operation.action == "delete":
                # Check for active enrollments
                active = db.query(UserProgress).filter(
                    UserProgress.course_id == course.id,
                    UserProgress.status == "in_progress"
                ).count()
                
                if active == 0:
                    course.status = ContentStatus.ARCHIVED.value
                    success_count += 1
                else:
                    failed_ids.append(course.id)
            
            elif operation.action == "update_category" and operation.value:
                course.category = operation.value
                success_count += 1
            
            elif operation.action == "update_difficulty" and operation.value:
                course.difficulty_level = operation.value
                success_count += 1
            
            elif operation.action == "toggle_featured":
                course.is_featured = not course.is_featured
                success_count += 1
            
        except Exception:
            failed_ids.append(course.id)
    
    # Log bulk operation
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.BULK_OPERATION,
        entity_type="course",
        entity_id=None,
        details={
            "action": operation.action,
            "course_ids": operation.course_ids,
            "success_count": success_count,
            "failed_ids": failed_ids,
            "value": operation.value
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {
        "action": operation.action,
        "total_courses": len(operation.course_ids),
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "message": f"Bulk {operation.action} completed"
    }


# Import dependencies at the end to avoid circular imports
from app.routers.admin import get_current_admin_user
from app.models.course import ChapterPath