"""
Admin segments router for Spark LMS.

Handles admin-specific segment management including creating
explanations and activities with code execution support.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Body
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func

from app.core.database import get_db
from app.models.user import User
from app.models.course import Course, Chapter, Segment, SegmentType
from app.models.progress import SegmentAttempt, UserProgress
from app.models.admin import AdminLog, AdminAction
from app.schemas.admin import (
    SegmentCreate,
    SegmentUpdate,
    SegmentResponse,
    SegmentListResponse,
    MCQQuestion,
    TestCase,
    SegmentReorder,
    BulkSegmentOperation,
    SegmentPreview
)


router = APIRouter()


@router.get("/chapter/{chapter_id}", response_model=SegmentListResponse)
async def list_segments(
    chapter_id: int,
    include_attempts: bool = Query(False),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    List all segments for a chapter.
    """
    # Verify chapter exists
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # Get segments
    segments = db.query(Segment).filter(
        Segment.chapter_id == chapter_id
    ).order_by(Segment.order_index).all()
    
    # Format segments
    segments_data = []
    for segment in segments:
        segment_data = {
            "id": segment.id,
            "title": segment.title,
            "type": segment.type,
            "order_index": segment.order_index,
            "xp_value": segment.xp_value,
            "max_attempts": segment.max_attempts,
            "required_score": segment.required_score,
            "time_limit_seconds": segment.time_limit_seconds,
            "is_published": segment.is_published,
            "created_at": segment.created_at.isoformat(),
            "updated_at": segment.updated_at.isoformat()
        }
        
        # Add type-specific counts
        if segment.type == SegmentType.EXPLANATION.value:
            segment_data["mcq_count"] = len(segment.mcq_questions or [])
        elif segment.type == SegmentType.ACTIVITY.value:
            segment_data["test_case_count"] = len(segment.test_cases or [])
            segment_data["has_solution"] = segment.solution is not None
        
        # Add attempt statistics if requested
        if include_attempts:
            attempts = db.query(SegmentAttempt).filter(
                SegmentAttempt.segment_id == segment.id
            ).all()
            
            segment_data["attempt_stats"] = {
                "total_attempts": len(attempts),
                "unique_users": len(set(a.user_id for a in attempts)),
                "avg_score": sum(a.score for a in attempts) / len(attempts) if attempts else 0,
                "success_rate": len([a for a in attempts if a.score >= segment.required_score]) / len(attempts) * 100 if attempts else 0
            }
        
        segments_data.append(segment_data)
    
    return {
        "chapter_id": chapter_id,
        "chapter_title": chapter.title,
        "segments": segments_data,
        "total_segments": len(segments),
        "total_xp": sum(s.xp_value for s in segments)
    }


@router.post("/", response_model=SegmentResponse, status_code=status.HTTP_201_CREATED)
async def create_segment(
    segment_data: SegmentCreate,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Segment:
    """
    Create a new segment in a chapter.
    """
    # Verify chapter exists
    chapter = db.query(Chapter).filter(Chapter.id == segment_data.chapter_id).first()
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # Validate segment type
    if segment_data.type not in [SegmentType.EXPLANATION.value, SegmentType.ACTIVITY.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid segment type"
        )
    
    # Validate type-specific fields
    if segment_data.type == SegmentType.EXPLANATION.value:
        # Validate MCQ questions
        if segment_data.mcq_questions:
            for q in segment_data.mcq_questions:
                if not q.get("question") or not q.get("options") or not q.get("correct_answer"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid MCQ question format"
                    )
                if q["correct_answer"] not in q["options"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Correct answer must be one of the options"
                    )
    
    elif segment_data.type == SegmentType.ACTIVITY.value:
        # Validate test cases
        if segment_data.test_cases:
            for tc in segment_data.test_cases:
                if not tc.get("name") or "expected_output" not in tc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid test case format"
                    )
    
    # Get next order index
    max_order = db.query(func.max(Segment.order_index)).filter(
        Segment.chapter_id == segment_data.chapter_id
    ).scalar() or -1
    
    # Create segment
    new_segment = Segment(
        **segment_data.dict(),
        order_index=max_order + 1,
        is_published=False  # Always start as unpublished
    )
    
    db.add(new_segment)
    
    # Update chapter's total XP
    chapter.total_xp = chapter.calculate_total_xp()
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.CREATE,
        entity_type="segment",
        entity_id=new_segment.id,
        details={
            "segment_title": new_segment.title,
            "segment_type": new_segment.type,
            "chapter_id": segment_data.chapter_id
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    db.refresh(new_segment)
    
    return new_segment


@router.get("/{segment_id}", response_model=SegmentResponse)
async def get_segment(
    segment_id: int,
    db: Session = Depends(get_db)
) -> Segment:
    """
    Get detailed information about a specific segment.
    """
    segment = db.query(Segment).filter(
        Segment.id == segment_id
    ).options(
        joinedload(Segment.chapter),
        joinedload(Segment.attempts)
    ).first()
    
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    return segment


@router.put("/{segment_id}", response_model=SegmentResponse)
async def update_segment(
    segment_id: int,
    segment_update: SegmentUpdate,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Segment:
    """
    Update a segment.
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    # Track changes for logging
    changes = {}
    update_data = segment_update.dict(exclude_unset=True)
    
    # Validate type-specific updates
    if "mcq_questions" in update_data and segment.type == SegmentType.EXPLANATION.value:
        for q in update_data["mcq_questions"]:
            if q["correct_answer"] not in q["options"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Correct answer must be one of the options"
                )
    
    # Update fields
    for field, value in update_data.items():
        if hasattr(segment, field) and getattr(segment, field) != value:
            changes[field] = {
                "old": getattr(segment, field) if not isinstance(getattr(segment, field), (list, dict)) else "...",
                "new": value if not isinstance(value, (list, dict)) else "..."
            }
            setattr(segment, field, value)
    
    # Update timestamp
    segment.updated_at = datetime.utcnow()
    
    # Update chapter's total XP if XP value changed
    if "xp_value" in changes:
        segment.chapter.total_xp = segment.chapter.calculate_total_xp()
    
    # Log action
    if changes:
        admin_log = AdminLog.log_action(
            user_id=current_admin.id,
            action=AdminAction.UPDATE,
            entity_type="segment",
            entity_id=segment_id,
            details={
                "changes": changes
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        db.add(admin_log)
    
    db.commit()
    db.refresh(segment)
    
    return segment


@router.delete("/{segment_id}")
async def delete_segment(
    segment_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Delete a segment.
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    # Check if any users have attempts on this segment
    attempt_count = db.query(SegmentAttempt).filter(
        SegmentAttempt.segment_id == segment_id
    ).count()
    
    if attempt_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete segment with {attempt_count} user attempts"
        )
    
    # Store info for logging
    segment_title = segment.title
    chapter_id = segment.chapter_id
    order_index = segment.order_index
    
    # Delete segment
    db.delete(segment)
    
    # Reorder remaining segments
    remaining_segments = db.query(Segment).filter(
        Segment.chapter_id == chapter_id,
        Segment.order_index > order_index
    ).all()
    
    for remaining in remaining_segments:
        remaining.order_index -= 1
    
    # Update chapter's total XP
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if chapter:
        chapter.total_xp = chapter.calculate_total_xp()
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.DELETE,
        entity_type="segment",
        entity_id=segment_id,
        details={
            "segment_title": segment_title,
            "chapter_id": chapter_id
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {"message": "Segment deleted successfully"}


@router.put("/reorder", response_model=Dict[str, str])
async def reorder_segments(
    reorder_data: SegmentReorder,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Reorder segments within a chapter.
    """
    # Verify all segments belong to the same chapter
    segments = db.query(Segment).filter(
        Segment.id.in_(reorder_data.segment_ids)
    ).all()
    
    if len(segments) != len(reorder_data.segment_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some segments not found"
        )
    
    chapter_ids = set(segment.chapter_id for segment in segments)
    if len(chapter_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All segments must belong to the same chapter"
        )
    
    # Update order indices
    for index, segment_id in enumerate(reorder_data.segment_ids):
        segment = next(s for s in segments if s.id == segment_id)
        segment.order_index = index
        segment.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": "Segments reordered successfully"}


@router.post("/{segment_id}/publish")
async def publish_segment(
    segment_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Publish a segment, making it available in published chapters.
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    if segment.is_published:
        return {"message": "Segment is already published", "is_published": True}
    
    # Validate segment has required content
    if segment.type == SegmentType.ACTIVITY.value:
        if not segment.test_cases or len(segment.test_cases) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Activity segments must have at least one test case"
            )
    
    # Update segment
    segment.is_published = True
    
    # Update chapter's total XP
    segment.chapter.total_xp = segment.chapter.calculate_total_xp()
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.PUBLISH,
        entity_type="segment",
        entity_id=segment_id,
        details={
            "segment_title": segment.title,
            "segment_type": segment.type
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {
        "message": "Segment published successfully",
        "is_published": True,
        "xp_value": segment.xp_value
    }


@router.post("/{segment_id}/unpublish")
async def unpublish_segment(
    segment_id: int,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Unpublish a segment.
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    if not segment.is_published:
        return {"message": "Segment is not published", "is_published": False}
    
    # Update segment
    segment.is_published = False
    
    # Update chapter's total XP
    segment.chapter.total_xp = segment.chapter.calculate_total_xp()
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.UNPUBLISH,
        entity_type="segment",
        entity_id=segment_id,
        details={
            "segment_title": segment.title
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    
    return {
        "message": "Segment unpublished successfully",
        "is_published": False
    }


@router.post("/{segment_id}/duplicate", response_model=SegmentResponse)
async def duplicate_segment(
    segment_id: int,
    new_title: str,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Segment:
    """
    Duplicate a segment within the same chapter.
    """
    # Get original segment
    original_segment = db.query(Segment).filter(Segment.id == segment_id).first()
    
    if not original_segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    # Get next order index
    max_order = db.query(func.max(Segment.order_index)).filter(
        Segment.chapter_id == original_segment.chapter_id
    ).scalar() or -1
    
    # Create new segment
    new_segment = Segment(
        title=new_title,
        type=original_segment.type,
        chapter_id=original_segment.chapter_id,
        content=original_segment.content,
        code_template=original_segment.code_template,
        test_cases=original_segment.test_cases,
        expected_output=original_segment.expected_output,
        hints=original_segment.hints,
        solution=original_segment.solution,
        mcq_questions=original_segment.mcq_questions,
        order_index=max_order + 1,
        xp_value=original_segment.xp_value,
        max_attempts=original_segment.max_attempts,
        required_score=original_segment.required_score,
        time_limit_seconds=original_segment.time_limit_seconds,
        is_published=False  # Start as unpublished
    )
    
    db.add(new_segment)
    
    # Log action
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.CREATE,
        entity_type="segment",
        entity_id=new_segment.id,
        details={
            "action": "segment_duplication",
            "original_segment_id": segment_id,
            "new_segment_title": new_title
        },
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    
    db.commit()
    db.refresh(new_segment)
    
    return new_segment


@router.post("/{segment_id}/preview", response_model=SegmentPreview)
async def preview_segment(
    segment_id: int,
    test_input: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Preview a segment as it would appear to users.
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    preview_data = {
        "id": segment.id,
        "title": segment.title,
        "type": segment.type,
        "content": segment.content,
        "xp_value": segment.xp_value,
        "required_score": segment.required_score
    }
    
    # Add type-specific preview data
    if segment.type == SegmentType.EXPLANATION.value:
        preview_data["mcq_questions"] = [
            {
                "id": i,
                "question": q["question"],
                "options": q["options"]
            }
            for i, q in enumerate(segment.mcq_questions or [])
        ]
    
    elif segment.type == SegmentType.ACTIVITY.value:
        preview_data["code_template"] = segment.code_template
        preview_data["expected_output"] = segment.expected_output
        preview_data["test_cases_count"] = len(segment.test_cases or [])
        
        # If test input provided, simulate test execution
        if test_input and test_input.get("code"):
            # This is where you would normally execute the code
            # For now, return a simulated response
            preview_data["test_results"] = {
                "execution_output": "Simulated output",
                "test_results": [
                    {
                        "name": tc["name"],
                        "passed": True,
                        "output": "Test output"
                    }
                    for tc in (segment.test_cases or [])
                ],
                "score": 100
            }
    
    return preview_data


@router.post("/bulk", response_model=Dict[str, Any])
async def bulk_segment_operation(
    operation: BulkSegmentOperation,
    request: Request,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Perform bulk operations on multiple segments.
    """
    # Get segments
    segments = db.query(Segment).filter(
        Segment.id.in_(operation.segment_ids)
    ).all()
    
    if len(segments) != len(operation.segment_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some segments not found"
        )
    
    # Perform operation
    success_count = 0
    failed_ids = []
    
    for segment in segments:
        try:
            if operation.action == "publish":
                if not segment.is_published:
                    segment.is_published = True
                    success_count += 1
            
            elif operation.action == "unpublish":
                if segment.is_published:
                    segment.is_published = False
                    success_count += 1
            
            elif operation.action == "update_xp" and operation.value:
                segment.xp_value = int(operation.value)
                success_count += 1
            
            elif operation.action == "update_max_attempts" and operation.value:
                segment.max_attempts = int(operation.value)
                success_count += 1
            
            elif operation.action == "update_required_score" and operation.value:
                segment.required_score = int(operation.value)
                success_count += 1
            
        except Exception:
            failed_ids.append(segment.id)
    
    # Update affected chapters' total XP
    affected_chapters = set(s.chapter_id for s in segments)
    for chapter_id in affected_chapters:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if chapter:
            chapter.total_xp = chapter.calculate_total_xp()
    
    # Log bulk operation
    admin_log = AdminLog.log_action(
        user_id=current_admin.id,
        action=AdminAction.BULK_OPERATION,
        entity_type="segment",
        entity_id=None,
        details={
            "action": operation.action,
            "segment_ids": operation.segment_ids,
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
        "total_segments": len(operation.segment_ids),
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "message": f"Bulk {operation.action} completed"
    }


@router.get("/{segment_id}/attempts")
async def get_segment_attempts(
    segment_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get user attempts for a specific segment (for analytics).
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    # Get attempts with user info
    query = db.query(SegmentAttempt).filter(
        SegmentAttempt.segment_id == segment_id
    ).options(joinedload(SegmentAttempt.user))
    
    total = query.count()
    
    attempts = query.order_by(
        SegmentAttempt.started_at.desc()
    ).offset(skip).limit(limit).all()
    
    # Format attempts
    attempts_data = []
    for attempt in attempts:
        attempts_data.append({
            "id": attempt.id,
            "user": {
                "id": attempt.user.id,
                "username": attempt.user.username
            },
            "attempt_number": attempt.attempt_number,
            "status": attempt.status,
            "score": attempt.score,
            "xp_earned": attempt.xp_earned,
            "hints_used": attempt.hints_used,
            "solution_viewed": attempt.solution_viewed,
            "time_spent": attempt.time_spent,
            "started_at": attempt.started_at.isoformat(),
            "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None
        })
    
    # Calculate statistics
    all_attempts = db.query(SegmentAttempt).filter(
        SegmentAttempt.segment_id == segment_id
    ).all()
    
    stats = {
        "total_attempts": len(all_attempts),
        "unique_users": len(set(a.user_id for a in all_attempts)),
        "avg_score": sum(a.score for a in all_attempts) / len(all_attempts) if all_attempts else 0,
        "success_rate": len([a for a in all_attempts if a.score >= segment.required_score]) / len(all_attempts) * 100 if all_attempts else 0,
        "avg_attempts_per_user": len(all_attempts) / len(set(a.user_id for a in all_attempts)) if all_attempts else 0
    }
    
    return {
        "segment": {
            "id": segment.id,
            "title": segment.title,
            "type": segment.type,
            "required_score": segment.required_score
        },
        "attempts": attempts_data,
        "statistics": stats,
        "total": total,
        "skip": skip,
        "limit": limit
    }


# Import dependencies at the end to avoid circular imports
from app.routers.admin import get_current_admin_user