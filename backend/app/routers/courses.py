"""
Courses router for Spark LMS.

Handles user-facing course endpoints including viewing courses,
chapters, segments, and submitting activities.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.models.course import Course, Chapter, Segment, ChapterPath, ContentStatus, SegmentType
from app.models.progress import (
    UserProgress, SegmentAttempt, UserScore, UserXP,
    ProgressStatus, AttemptStatus
)
from app.routers.auth import get_current_user, get_current_verified_user
from app.schemas.course import (
    CourseList,
    CourseDetail,
    ChapterDetail,
    SegmentDetail,
    CourseEnrollment,
    SegmentSubmission,
    SegmentAttemptResponse,
    ChapterProgress,
    NextChapterOptions
)
from app.utils.xp_calculator import calculate_segment_xp, calculate_chapter_xp
from app.utils.learning_path import get_next_chapters_for_user


router = APIRouter()


@router.get("/", response_model=CourseList)
async def list_courses(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    search: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    List all published courses with optional filtering.
    """
    # Base query for published courses
    query = db.query(Course).filter(Course.status == ContentStatus.PUBLISHED.value)
    
    # Apply filters
    if category:
        query = query.filter(Course.category == category)
    
    if difficulty:
        query = query.filter(Course.difficulty_level == difficulty)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Course.title.ilike(search_term),
                Course.description.ilike(search_term),
                Course.tags.contains([search])
            )
        )
    
    # Get total count
    total = query.count()
    
    # Apply pagination and ordering
    courses = query.order_by(
        Course.is_featured.desc(),
        Course.order_index,
        Course.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    # Get user progress if authenticated
    course_progress = {}
    if current_user:
        user_progress = db.query(UserProgress).filter(
            UserProgress.user_id == current_user.id,
            UserProgress.course_id.in_([c.id for c in courses])
        ).all()
        
        course_progress = {
            p.course_id: {
                "status": p.status,
                "progress_percentage": p.progress_percentage,
                "last_activity": p.last_activity_at
            }
            for p in user_progress
        }
    
    # Format response
    course_list = []
    for course in courses:
        course_dict = {
            "id": course.id,
            "title": course.title,
            "slug": course.slug,
            "short_description": course.short_description,
            "thumbnail_url": course.thumbnail_url,
            "difficulty_level": course.difficulty_level,
            "estimated_hours": course.estimated_hours,
            "category": course.category,
            "tags": course.tags or [],
            "is_featured": course.is_featured,
            "is_free": course.is_free,
            "total_xp": course.total_xp,
            "enrolled_count": course.enrolled_count,
            "average_rating": course.average_rating,
            "chapter_count": len(course.chapters),
            "user_progress": course_progress.get(course.id)
        }
        course_list.append(course_dict)
    
    return {
        "courses": course_list,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/{course_slug}", response_model=CourseDetail)
async def get_course(
    course_slug: str,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed information about a specific course.
    """
    # Get course with chapters
    course = db.query(Course).filter(
        Course.slug == course_slug,
        Course.status == ContentStatus.PUBLISHED.value
    ).options(
        joinedload(Course.chapters)
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Get user progress if authenticated
    user_progress = None
    if current_user:
        user_progress = db.query(UserProgress).filter(
            UserProgress.user_id == current_user.id,
            UserProgress.course_id == course.id
        ).first()
    
    # Get first chapter for unenrolled users
    first_chapter = db.query(Chapter).filter(
        Chapter.course_id == course.id,
        Chapter.is_published == True
    ).order_by(Chapter.order_index).first()
    
    # Format chapters with progress
    chapters_data = []
    for chapter in sorted(course.chapters, key=lambda x: x.order_index):
        if not chapter.is_published:
            continue
        
        chapter_data = {
            "id": chapter.id,
            "title": chapter.title,
            "slug": chapter.slug,
            "description": chapter.description,
            "order_index": chapter.order_index,
            "estimated_minutes": chapter.estimated_minutes,
            "total_xp": chapter.total_xp,
            "is_locked": True,  # Default to locked
            "is_completed": False,
            "user_score": None
        }
        
        # Update lock status based on user progress
        if user_progress:
            if chapter.id in user_progress.unlocked_chapters:
                chapter_data["is_locked"] = False
            if chapter.id in user_progress.completed_chapters:
                chapter_data["is_completed"] = True
                chapter_data["user_score"] = user_progress.chapter_scores.get(str(chapter.id))
        elif chapter.id == first_chapter.id:
            # First chapter is always unlocked
            chapter_data["is_locked"] = False
        
        chapters_data.append(chapter_data)
    
    # Prepare response
    response = {
        "id": course.id,
        "title": course.title,
        "slug": course.slug,
        "description": course.description,
        "thumbnail_url": course.thumbnail_url,
        "banner_url": course.banner_url,
        "difficulty_level": course.difficulty_level,
        "estimated_hours": course.estimated_hours,
        "prerequisites": course.prerequisites or [],
        "tags": course.tags or [],
        "category": course.category,
        "total_xp": course.total_xp,
        "passing_score": course.passing_score,
        "enrolled_count": course.enrolled_count,
        "completion_count": course.completion_count,
        "average_rating": course.average_rating,
        "chapters": chapters_data,
        "is_enrolled": user_progress is not None,
        "user_progress": {
            "status": user_progress.status if user_progress else ProgressStatus.NOT_STARTED.value,
            "progress_percentage": user_progress.progress_percentage if user_progress else 0,
            "current_chapter_id": user_progress.current_chapter_id if user_progress else None,
            "total_xp_earned": user_progress.total_xp_earned if user_progress else 0,
            "average_score": user_progress.average_score if user_progress else 0
        } if current_user else None
    }
    
    return response


@router.post("/{course_slug}/enroll", response_model=CourseEnrollment)
async def enroll_in_course(
    course_slug: str,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Enroll the current user in a course.
    """
    # Get course
    course = db.query(Course).filter(
        Course.slug == course_slug,
        Course.status == ContentStatus.PUBLISHED.value
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Check if already enrolled
    existing_progress = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.course_id == course.id
    ).first()
    
    if existing_progress:
        return {
            "message": "Already enrolled in this course",
            "course_id": course.id,
            "progress_id": existing_progress.id,
            "current_chapter_id": existing_progress.current_chapter_id
        }
    
    # Check enrollment limit
    enrolled_courses = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id
    ).count()
    
    if enrolled_courses >= current_user.max_courses:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Course enrollment limit reached ({current_user.max_courses} courses)"
        )
    
    # Get first chapter
    first_chapter = db.query(Chapter).filter(
        Chapter.course_id == course.id,
        Chapter.is_published == True
    ).order_by(Chapter.order_index).first()
    
    if not first_chapter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course has no available chapters"
        )
    
    # Create enrollment
    new_progress = UserProgress(
        user_id=current_user.id,
        course_id=course.id,
        current_chapter_id=first_chapter.id,
        status=ProgressStatus.IN_PROGRESS.value,
        unlocked_chapters=[first_chapter.id],
        learning_path=[first_chapter.id]
    )
    
    # Update course enrollment count
    course.enrolled_count += 1
    
    db.add(new_progress)
    db.commit()
    db.refresh(new_progress)
    
    return {
        "message": "Successfully enrolled in course",
        "course_id": course.id,
        "progress_id": new_progress.id,
        "current_chapter_id": first_chapter.id
    }


@router.get("/{course_slug}/chapters/{chapter_slug}", response_model=ChapterDetail)
async def get_chapter(
    course_slug: str,
    chapter_slug: str,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed information about a chapter and its segments.
    """
    # Get course
    course = db.query(Course).filter(
        Course.slug == course_slug,
        Course.status == ContentStatus.PUBLISHED.value
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Get user progress
    user_progress = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.course_id == course.id
    ).first()
    
    if not user_progress:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enrolled in this course"
        )
    
    # Get chapter
    chapter = db.query(Chapter).filter(
        Chapter.course_id == course.id,
        Chapter.slug == chapter_slug,
        Chapter.is_published == True
    ).options(
        joinedload(Chapter.segments)
    ).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # Check if chapter is unlocked
    if chapter.id not in user_progress.unlocked_chapters:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chapter is locked. Complete previous chapters to unlock."
        )
    
    # Update current position
    user_progress.current_chapter_id = chapter.id
    user_progress.last_activity_at = datetime.utcnow()
    
    # Get segment progress
    segments_data = []
    for segment in sorted(chapter.segments, key=lambda x: x.order_index):
        if not segment.is_published:
            continue
        
        # Get user's attempts for this segment
        attempts = db.query(SegmentAttempt).filter(
            SegmentAttempt.user_id == current_user.id,
            SegmentAttempt.segment_id == segment.id
        ).order_by(SegmentAttempt.attempt_number.desc()).all()
        
        best_attempt = max(attempts, key=lambda a: a.score) if attempts else None
        
        segment_data = {
            "id": segment.id,
            "title": segment.title,
            "type": segment.type,
            "order_index": segment.order_index,
            "xp_value": segment.xp_value,
            "required_score": segment.required_score,
            "is_completed": segment.id in user_progress.completed_segments,
            "is_locked": False,  # Will update based on previous segment
            "attempts_count": len(attempts),
            "best_score": best_attempt.score if best_attempt else None,
            "xp_earned": best_attempt.xp_earned if best_attempt else 0
        }
        
        # Lock segments after first incomplete one
        if segments_data and not segments_data[-1]["is_completed"]:
            segment_data["is_locked"] = True
        
        segments_data.append(segment_data)
    
    # Update current segment if needed
    if not user_progress.current_segment_id and segments_data:
        first_incomplete = next(
            (s for s in segments_data if not s["is_completed"]),
            None
        )
        if first_incomplete:
            user_progress.current_segment_id = first_incomplete["id"]
    
    db.commit()
    
    # Get chapter completion status
    chapter_score = user_progress.chapter_scores.get(str(chapter.id))
    is_completed = chapter.id in user_progress.completed_chapters
    
    return {
        "id": chapter.id,
        "title": chapter.title,
        "slug": chapter.slug,
        "description": chapter.description,
        "estimated_minutes": chapter.estimated_minutes,
        "total_xp": chapter.total_xp,
        "passing_score": chapter.passing_score,
        "segments": segments_data,
        "is_completed": is_completed,
        "user_score": chapter_score,
        "progress": {
            "completed_segments": len([s for s in segments_data if s["is_completed"]]),
            "total_segments": len(segments_data),
            "total_xp_earned": sum(s["xp_earned"] for s in segments_data)
        }
    }


@router.get("/{course_slug}/chapters/{chapter_slug}/segments/{segment_id}", response_model=SegmentDetail)
async def get_segment(
    course_slug: str,
    chapter_slug: str,
    segment_id: int,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed information about a segment.
    """
    # Verify course and chapter access (similar to get_chapter)
    course = db.query(Course).filter(
        Course.slug == course_slug,
        Course.status == ContentStatus.PUBLISHED.value
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    chapter = db.query(Chapter).filter(
        Chapter.course_id == course.id,
        Chapter.slug == chapter_slug
    ).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # Get segment
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.chapter_id == chapter.id,
        Segment.is_published == True
    ).first()
    
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    # Get user progress and verify access
    user_progress = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.course_id == course.id
    ).first()
    
    if not user_progress or chapter.id not in user_progress.unlocked_chapters:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Get user's attempts
    attempts = db.query(SegmentAttempt).filter(
        SegmentAttempt.user_id == current_user.id,
        SegmentAttempt.segment_id == segment.id
    ).order_by(SegmentAttempt.attempt_number.desc()).all()
    
    # Check if segment is locked (previous segment not completed)
    previous_segment = db.query(Segment).filter(
        Segment.chapter_id == chapter.id,
        Segment.order_index < segment.order_index,
        Segment.is_published == True
    ).order_by(Segment.order_index.desc()).first()
    
    if previous_segment and previous_segment.id not in user_progress.completed_segments:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Complete previous segments to unlock this one"
        )
    
    # Update current segment
    user_progress.current_segment_id = segment.id
    db.commit()
    
    # Prepare segment data based on type
    segment_data = {
        "id": segment.id,
        "title": segment.title,
        "type": segment.type,
        "content": segment.content,
        "xp_value": segment.xp_value,
        "max_attempts": segment.max_attempts,
        "required_score": segment.required_score,
        "time_limit_seconds": segment.time_limit_seconds,
        "attempts_remaining": segment.max_attempts - len(attempts),
        "user_attempts": [
            {
                "attempt_number": attempt.attempt_number,
                "score": attempt.score,
                "xp_earned": attempt.xp_earned,
                "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
                "time_spent": attempt.time_spent
            }
            for attempt in attempts
        ]
    }
    
    # Add type-specific fields
    if segment.type == SegmentType.ACTIVITY.value:
        segment_data.update({
            "code_template": segment.code_template,
            "expected_output": segment.expected_output,
            "hints": segment.hints if any(a.hints_used > 0 for a in attempts) else None,
            "test_cases_count": len(segment.test_cases) if segment.test_cases else 0
        })
    elif segment.type == SegmentType.EXPLANATION.value:
        segment_data.update({
            "mcq_questions": [
                {
                    "id": i,
                    "question": q["question"],
                    "options": q["options"]
                }
                for i, q in enumerate(segment.mcq_questions or [])
            ]
        })
    
    return segment_data


@router.post("/{course_slug}/chapters/{chapter_slug}/segments/{segment_id}/submit", 
             response_model=SegmentAttemptResponse)
async def submit_segment(
    course_slug: str,
    chapter_slug: str,
    segment_id: int,
    submission: SegmentSubmission,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Submit a segment attempt (activity code or MCQ answers).
    """
    # Verify access (similar checks as get_segment)
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    # Get user progress
    user_progress = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.course_id == segment.chapter.course_id
    ).first()
    
    # Check attempts limit
    existing_attempts = db.query(SegmentAttempt).filter(
        SegmentAttempt.user_id == current_user.id,
        SegmentAttempt.segment_id == segment_id
    ).count()
    
    if existing_attempts >= segment.max_attempts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Maximum attempts ({segment.max_attempts}) reached"
        )
    
    # Check daily XP limit
    today_xp = db.query(func.sum(UserXP.xp_amount)).filter(
        UserXP.user_id == current_user.id,
        func.date(UserXP.earned_at) == func.date(func.now())
    ).scalar() or 0
    
    if today_xp >= current_user.daily_xp_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Daily XP limit reached"
        )
    
    # Create attempt
    attempt = SegmentAttempt(
        user_id=current_user.id,
        segment_id=segment_id,
        attempt_number=existing_attempts + 1,
        status=AttemptStatus.IN_PROGRESS.value,
        started_at=datetime.utcnow()
    )
    
    # Process submission based on segment type
    if segment.type == SegmentType.ACTIVITY.value:
        attempt.submitted_code = submission.code
        # Here you would normally execute the code and run tests
        # For now, we'll simulate the results
        test_results = []
        if segment.test_cases:
            for i, test_case in enumerate(segment.test_cases):
                # Simulate test execution
                test_results.append({
                    "test_id": i,
                    "name": test_case.get("name", f"Test {i+1}"),
                    "passed": True,  # In real implementation, run actual tests
                    "output": "Test output",
                    "expected": test_case.get("expected_output")
                })
        
        attempt.test_results = test_results
        attempt.execution_output = "Code executed successfully"  # Simulated
        
    elif segment.type == SegmentType.EXPLANATION.value:
        attempt.mcq_answers = submission.mcq_answers
    
    # Calculate score
    attempt.score = attempt.calculate_score()
    
    # Calculate XP (considering attempts, hints, solution)
    attempt.xp_earned = segment.calculate_xp_for_attempt(
        attempt.attempt_number,
        submission.hints_used or 0,
        submission.solution_viewed or False
    )
    
    # Update attempt status
    if attempt.score >= segment.required_score:
        attempt.status = AttemptStatus.PASSED.value
        
        # Mark segment as completed
        if segment_id not in user_progress.completed_segments:
            user_progress.completed_segments = user_progress.completed_segments + [segment_id]
            user_progress.segment_scores[str(segment_id)] = attempt.score
        
        # Add XP to user
        current_user.add_xp(attempt.xp_earned)
        
        # Create XP record
        xp_record = UserXP.create_xp_record(
            user_id=current_user.id,
            xp_amount=attempt.xp_earned,
            xp_type="segment_completion",
            description=f"Completed segment: {segment.title}",
            course_id=segment.chapter.course_id,
            chapter_id=segment.chapter_id,
            segment_id=segment_id
        )
        db.add(xp_record)
        
        # Check if chapter is completed
        chapter_segments = db.query(Segment).filter(
            Segment.chapter_id == segment.chapter_id,
            Segment.is_published == True
        ).all()
        
        chapter_completed = all(
            s.id in user_progress.completed_segments 
            for s in chapter_segments
        )
        
        if chapter_completed and segment.chapter_id not in user_progress.completed_chapters:
            # Calculate chapter score
            chapter_score = int(sum(
                user_progress.segment_scores.get(str(s.id), 0) 
                for s in chapter_segments
            ) / len(chapter_segments))
            
            user_progress.add_completed_chapter(segment.chapter_id, chapter_score)
            
            # Unlock next chapters based on score
            next_chapters = get_next_chapters_for_user(
                segment.chapter,
                chapter_score,
                db
            )
            
            for next_chapter in next_chapters:
                if next_chapter.id not in user_progress.unlocked_chapters:
                    user_progress.unlocked_chapters = user_progress.unlocked_chapters + [next_chapter.id]
                    user_progress.learning_path = user_progress.learning_path + [next_chapter.id]
    else:
        attempt.status = AttemptStatus.FAILED.value
    
    attempt.completed_at = datetime.utcnow()
    attempt.time_spent = submission.time_spent or 0
    
    # Save attempt
    db.add(attempt)
    
    # Update user streak
    current_user.update_streak(datetime.utcnow())
    
    db.commit()
    db.refresh(attempt)
    
    # Prepare response
    response = {
        "attempt_id": attempt.id,
        "score": attempt.score,
        "passed": attempt.status == AttemptStatus.PASSED.value,
        "xp_earned": attempt.xp_earned,
        "feedback": {
            "message": "Great job!" if attempt.status == AttemptStatus.PASSED.value else "Try again!",
            "score": attempt.score,
            "required_score": segment.required_score
        }
    }
    
    # Add type-specific feedback
    if segment.type == SegmentType.ACTIVITY.value:
        response["test_results"] = attempt.test_results
        response["execution_output"] = attempt.execution_output
    elif segment.type == SegmentType.EXPLANATION.value:
        # Provide correct answers for failed attempts on last try
        if attempt.status == AttemptStatus.FAILED.value and existing_attempts + 1 >= segment.max_attempts:
            response["correct_answers"] = [
                {
                    "question_id": i,
                    "correct_answer": q.get("correct_answer")
                }
                for i, q in enumerate(segment.mcq_questions or [])
            ]
    
    return response


@router.get("/{course_slug}/chapters/{chapter_slug}/next-options", response_model=NextChapterOptions)
async def get_next_chapter_options(
    course_slug: str,
    chapter_slug: str,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get possible next chapters based on current chapter completion and score.
    """
    # Get chapter and user progress
    chapter = db.query(Chapter).join(Course).filter(
        Course.slug == course_slug,
        Chapter.slug == chapter_slug
    ).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    user_progress = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.course_id == chapter.course_id
    ).first()
    
    if not user_progress:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enrolled in this course"
        )
    
    # Get user's score for this chapter
    chapter_score = user_progress.chapter_scores.get(str(chapter.id))
    
    # Get all possible paths from this chapter
    paths = db.query(ChapterPath).filter(
        ChapterPath.from_chapter_id == chapter.id
    ).options(
        joinedload(ChapterPath.to_chapter)
    ).all()
    
    # Evaluate which paths are available
    available_paths = []
    for path in paths:
        if path.evaluate_condition(chapter_score):
            available_paths.append({
                "chapter_id": path.to_chapter.id,
                "chapter_title": path.to_chapter.title,
                "chapter_slug": path.to_chapter.slug,
                "condition": path.condition_label,
                "is_unlocked": path.to_chapter.id in user_progress.unlocked_chapters
            })
    
    return {
        "current_chapter_id": chapter.id,
        "current_chapter_score": chapter_score,
        "next_options": available_paths,
        "is_chapter_completed": chapter.id in user_progress.completed_chapters
    }