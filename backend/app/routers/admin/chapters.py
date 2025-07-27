"""
Admin chapters router for Spark LMS.

Handles admin-specific chapter management including CRUD operations,
node-based workflow positioning, and dynamic learning paths.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Body
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

from app.core.database import get_db
from app.models.user import User
from app.models.course import Course, Chapter, Segment, ChapterPath, ContentStatus
from app.models.progress import UserProgress
from app.models.admin import AdminLog, AdminAction
from app.schemas.admin import (
    ChapterCreate,
    ChapterUpdate,
    ChapterResponse,
    ChapterListResponse,
    ChapterNodeUpdate,
    ChapterPathCreate,
    ChapterPathUpdate,
    ChapterPathResponse,
    ChapterReorder,
    NodePosition
)


router = APIRouter()


@router.get("/course/{course_id}", response_model=ChapterListResponse)
async def list_chapters(
    course_id: int,
    include_segments: bool = Query(False),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    List all chapters for a course with node positions and paths.
    """
    # Verify course exists
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Get chapters with optional segments
    query = db.query(Chapter).filter(Chapter.course_id == course_id)
    if include_segments:
        query = query.options(joinedload(Chapter.segments))
    
    chapters = query.order_by(Chapter.order_index).all()
    
    # Get all paths for this course
    paths = db.query(ChapterPath).join(
        Chapter, Chapter.id == ChapterPath.from_chapter_id
    ).filter(Chapter.course_id == course_id).all()
    
    # Format chapters
    chapters_data = []
    for chapter in chapters:
        chapter_data = {
            "id": chapter.id,
            "title": chapter.title,
            "slug": chapter.slug,
            "description": chapter.description,
            "node_id": chapter.node_id,
            "position_x": chapter.position_x,
            "position_y": chapter.position_y,
            "order_index": chapter.order_index,
            "estimated_minutes": chapter.estimated_minutes,
            "total_xp": chapter.total_xp,
            "passing_score": chapter.passing_score,
            "is_published": chapter.is_published,
            "is_locked": chapter.is_locked,
            "created_at": chapter.created_at.isoformat(),
            "updated_at": chapter.updated_at.isoformat()
        }
        
        if include_segments:
            chapter_data["segments"] = [
                {
                    "id": segment.id,
                    "title": segment.title,
                    "type": segment.type,
                    "order_index": segment.order_index,
                    "xp_value": segment.xp_value,
                    "is_published": segment.is_published
                }
                for segment in sorted(chapter.segments, key=lambda s: s.order_index)
            ]
        
        chapters_data.append(chapter_data)
    
    # Format paths
    paths_data = []
    for path in paths:
        paths_data.append({
            "id": path.id,
            "from_chapter_id": path.from_chapter_id,
            "to_chapter_id": path.to_chapter_id,
            "condition_type": path.condition_type,
            "condition_value": path.condition_value,
            "condition_label": path.condition_label,
            "is_default": path.is_default,
            "path_color": path.path_color,
            "path_style": path.path_style
        })
    
    return {
        "course_id": course_id,
        "course_title": course.title,
        "chapters": chapters_data,
        "paths": paths_data,
        "total_chapters": len(chapters)
    }


@router.post("/", response_model=ChapterResponse, status_code=status.HTTP_201_CREATED)
async def create_chapter(
    chapter_data: ChapterCreate,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Chapter:
    """
    Create a new chapter in a course.
    """
    # Verify course exists
    course = db.query(Course).filter(Course.id == chapter_data.course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Check if slug already exists in course
    existing_chapter = db.query(Chapter).filter(
        Chapter.course_id == chapter_data.course_id,
        Chapter.slug == chapter_data.slug
    ).first()
    
    if existing_chapter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chapter with this slug already exists in the course"
        )
    
    # Get next order index
    max_order = db.query(func.max(Chapter.order_index)).filter(
        Chapter.course_id == chapter_data.course_id
    ).scalar() or -1
    
    # Create chapter
    new_chapter = Chapter(
        **chapter_data.dict(exclude={"position_x", "position_y"}),
        order_index=max_order + 1,
        position_x=chapter_data.position_x or 100.0,
        position_y=chapter_data.position_y or 100.0,
        is_published=False  # Always start as unpublished
    )
    
    db.add(new_chapter)
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.CREATE,
        entity_type="chapter",
        entity_id=new_chapter.id,
        details={
            "chapter_title": new_chapter.title,
            "course_id": chapter_data.course_id
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    db.refresh(new_chapter)
    
    return new_chapter


@router.get("/{chapter_id}", response_model=ChapterResponse)
async def get_chapter(
    chapter_id: int,
    db: Session = Depends(get_db)
) -> Chapter:
    """
    Get detailed information about a specific chapter.
    """
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id
    ).options(
        joinedload(Chapter.segments),
        joinedload(Chapter.outgoing_paths),
        joinedload(Chapter.incoming_paths)
    ).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    return chapter


@router.put("/{chapter_id}", response_model=ChapterResponse)
async def update_chapter(
    chapter_id: int,
    chapter_update: ChapterUpdate,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Chapter:
    """
    Update a chapter.
    """
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # Track changes for logging
    changes = {}
    update_data = chapter_update.dict(exclude_unset=True)
    
    # Update fields
    for field, value in update_data.items():
        if hasattr(chapter, field) and getattr(chapter, field) != value:
            changes[field] = {
                "old": getattr(chapter, field),
                "new": value
            }
            setattr(chapter, field, value)
    
    # Update timestamp
    chapter.updated_at = datetime.utcnow()
    
    # Update chapter total XP
    chapter.total_xp = chapter.calculate_total_xp()
    
    # Log action
    if changes:
        admin_log = AdminLog.log_action(
            user_id=current_admin.id,
            action=AdminAction.UPDATE,
            entity_type="chapter",
            entity_id=chapter_id,
            details={
                "changes": changes
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        db.add(admin_log)
    
    db.commit()
    db.refresh(chapter)
    
    return chapter


@router.delete("/{chapter_id}")
async def delete_chapter(
    chapter_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Delete a chapter and all its segments.
    """
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # Check if any users have progress in this chapter
    users_with_progress = db.query(UserProgress).filter(
        or_(
            UserProgress.current_chapter_id == chapter_id,
            UserProgress.completed_chapters.contains([chapter_id]),
            UserProgress.unlocked_chapters.contains([chapter_id])
        )
    ).count()
    
    if users_with_progress > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete chapter with {users_with_progress} users having progress"
        )
    
    # Store info for logging
    chapter_title = chapter.title
    course_id = chapter.course_id
    segment_count = len(chapter.segments)
    
    # Delete chapter (cascades to segments and paths)
    db.delete(chapter)
    
    # Reorder remaining chapters
    remaining_chapters = db.query(Chapter).filter(
        Chapter.course_id == course_id,
        Chapter.order_index > chapter.order_index
    ).all()
    
    for remaining in remaining_chapters:
        remaining.order_index -= 1
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.DELETE,
        entity_type="chapter",
        entity_id=chapter_id,
        details={
            "chapter_title": chapter_title,
            "course_id": course_id,
            "segments_deleted": segment_count
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {"message": "Chapter deleted successfully"}


@router.put("/{chapter_id}/position", response_model=ChapterResponse)
async def update_chapter_position(
    chapter_id: int,
    position: NodePosition,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Chapter:
    """
    Update chapter's position on the node canvas.
    """
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # Update position
    chapter.position_x = position.x
    chapter.position_y = position.y
    chapter.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(chapter)
    
    return chapter


@router.put("/reorder", response_model=Dict[str, str])
async def reorder_chapters(
    reorder_data: ChapterReorder,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Reorder chapters within a course.
    """
    # Verify all chapters belong to the same course
    chapters = db.query(Chapter).filter(
        Chapter.id.in_(reorder_data.chapter_ids)
    ).all()
    
    if len(chapters) != len(reorder_data.chapter_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some chapters not found"
        )
    
    course_ids = set(chapter.course_id for chapter in chapters)
    if len(course_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All chapters must belong to the same course"
        )
    
    # Update order indices
    for index, chapter_id in enumerate(reorder_data.chapter_ids):
        chapter = next(c for c in chapters if c.id == chapter_id)
        chapter.order_index = index
        chapter.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": "Chapters reordered successfully"}


@router.post("/{chapter_id}/publish")
async def publish_chapter(
    chapter_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Publish a chapter, making it available in published courses.
    """
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    if chapter.is_published:
        return {"message": "Chapter is already published", "is_published": True}
    
    # Validate chapter has at least one published segment
    published_segments = db.query(Segment).filter(
        Segment.chapter_id == chapter_id,
        Segment.is_published == True
    ).count()
    
    if published_segments == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chapter must have at least one published segment"
        )
    
    # Update chapter
    chapter.is_published = True
    chapter.total_xp = chapter.calculate_total_xp()
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.PUBLISH,
        entity_type="chapter",
        entity_id=chapter_id,
        details={
            "chapter_title": chapter.title,
            "segment_count": published_segments
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {
        "message": "Chapter published successfully",
        "is_published": True,
        "total_xp": chapter.total_xp
    }


# Chapter Path Management
@router.post("/paths", response_model=ChapterPathResponse, status_code=status.HTTP_201_CREATED)
async def create_chapter_path(
    path_data: ChapterPathCreate,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> ChapterPath:
    """
    Create a path between two chapters with optional conditions.
    """
    # Verify chapters exist and belong to same course
    from_chapter = db.query(Chapter).filter(Chapter.id == path_data.from_chapter_id).first()
    to_chapter = db.query(Chapter).filter(Chapter.id == path_data.to_chapter_id).first()
    
    if not from_chapter or not to_chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both chapters not found"
        )
    
    if from_chapter.course_id != to_chapter.course_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chapters must belong to the same course"
        )
    
    # Check if path already exists
    existing_path = db.query(ChapterPath).filter(
        ChapterPath.from_chapter_id == path_data.from_chapter_id,
        ChapterPath.to_chapter_id == path_data.to_chapter_id,
        ChapterPath.condition_type == path_data.condition_type,
        ChapterPath.condition_value == path_data.condition_value
    ).first()
    
    if existing_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This path already exists"
        )
    
    # Create condition label
    condition_label = None
    if path_data.condition_type:
        if path_data.condition_type == "score_gt":
            condition_label = f"score > {path_data.condition_value}"
        elif path_data.condition_type == "score_lt":
            condition_label = f"score < {path_data.condition_value}"
        elif path_data.condition_type == "score_gte":
            condition_label = f"score ≥ {path_data.condition_value}"
        elif path_data.condition_type == "score_lte":
            condition_label = f"score ≤ {path_data.condition_value}"
        elif path_data.condition_type == "score_eq":
            condition_label = f"score = {path_data.condition_value}"
    
    # Create path
    new_path = ChapterPath(
        **path_data.dict(),
        condition_label=condition_label or path_data.condition_label
    )
    
    db.add(new_path)
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.CREATE,
        entity_type="chapter_path",
        entity_id=new_path.id,
        details={
            "from_chapter": from_chapter.title,
            "to_chapter": to_chapter.title,
            "condition": condition_label
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    db.refresh(new_path)
    
    return new_path


@router.put("/paths/{path_id}", response_model=ChapterPathResponse)
async def update_chapter_path(
    path_id: int,
    path_update: ChapterPathUpdate,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> ChapterPath:
    """
    Update a chapter path's conditions or styling.
    """
    path = db.query(ChapterPath).filter(ChapterPath.id == path_id).first()
    
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Path not found"
        )
    
    # Update fields
    update_data = path_update.dict(exclude_unset=True)
    
    # Update condition label if condition changed
    if "condition_type" in update_data or "condition_value" in update_data:
        condition_type = update_data.get("condition_type", path.condition_type)
        condition_value = update_data.get("condition_value", path.condition_value)
        
        if condition_type:
            if condition_type == "score_gt":
                path.condition_label = f"score > {condition_value}"
            elif condition_type == "score_lt":
                path.condition_label = f"score < {condition_value}"
            elif condition_type == "score_gte":
                path.condition_label = f"score ≥ {condition_value}"
            elif condition_type == "score_lte":
                path.condition_label = f"score ≤ {condition_value}"
            elif condition_type == "score_eq":
                path.condition_label = f"score = {condition_value}"
    
    # Update other fields
    for field, value in update_data.items():
        if hasattr(path, field):
            setattr(path, field, value)
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.UPDATE,
        entity_type="chapter_path",
        entity_id=path_id,
        details={
            "changes": update_data
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    db.refresh(path)
    
    return path


@router.delete("/paths/{path_id}")
async def delete_chapter_path(
    path_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Delete a chapter path.
    """
    path = db.query(ChapterPath).filter(ChapterPath.id == path_id).first()
    
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Path not found"
        )
    
    # Store info for logging
    from_chapter = path.from_chapter
    to_chapter = path.to_chapter
    
    # Delete path
    db.delete(path)
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.DELETE,
        entity_type="chapter_path",
        entity_id=path_id,
        details={
            "from_chapter": from_chapter.title if from_chapter else None,
            "to_chapter": to_chapter.title if to_chapter else None,
            "condition": path.condition_label
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {"message": "Path deleted successfully"}


@router.post("/batch-update-positions")
async def batch_update_positions(
    positions: List[Dict[str, Any]] = Body(...),
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Batch update multiple chapter positions at once.
    """
    updated_count = 0
    
    for pos in positions:
        chapter = db.query(Chapter).filter(Chapter.id == pos["id"]).first()
        if chapter:
            chapter.position_x = pos["x"]
            chapter.position_y = pos["y"]
            chapter.updated_at = datetime.utcnow()
            updated_count += 1
    
    db.commit()
    
    return {
        "message": f"Updated {updated_count} chapter positions",
        "updated_count": updated_count
    }


# Import dependencies at the end to avoid circular imports
from app.routers.admin import get_current_admin_user
from sqlalchemy import func