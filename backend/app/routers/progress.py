"""
Progress router for Spark LMS.

Handles user progress tracking, XP management, leaderboards,
and learning statistics endpoints.
"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, desc, extract

from app.core.database import get_db
from app.models.user import User
from app.models.course import Course, Chapter, Segment
from app.models.progress import (
    UserProgress, SegmentAttempt, UserScore, UserXP,
    ProgressStatus
)
from app.routers.auth import get_current_user, get_current_verified_user
from app.schemas.progress import (
    UserProgressOverview,
    CourseProgressDetail,
    XPHistory,
    LeaderboardEntry,
    LearningStats,
    StreakInfo,
    AchievementResponse,
    DailyActivity,
    ProgressUpdate
)


router = APIRouter()


@router.get("/overview", response_model=UserProgressOverview)
async def get_progress_overview(
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get user's overall progress overview across all courses.
    """
    # Get all user progress records
    progress_records = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id
    ).options(
        joinedload(UserProgress.course)
    ).all()
    
    # Calculate statistics
    total_courses = len(progress_records)
    completed_courses = len([p for p in progress_records if p.status == ProgressStatus.COMPLETED.value])
    in_progress_courses = len([p for p in progress_records if p.status == ProgressStatus.IN_PROGRESS.value])
    
    # Get recent XP gains
    recent_xp = db.query(
        func.sum(UserXP.xp_amount)
    ).filter(
        UserXP.user_id == current_user.id,
        UserXP.earned_at >= datetime.utcnow() - timedelta(days=7)
    ).scalar() or 0
    
    # Format course progress
    courses_progress = []
    for progress in progress_records:
        if progress.course:
            courses_progress.append({
                "course_id": progress.course.id,
                "course_title": progress.course.title,
                "course_slug": progress.course.slug,
                "status": progress.status,
                "progress_percentage": progress.progress_percentage,
                "current_chapter_id": progress.current_chapter_id,
                "total_xp_earned": progress.total_xp_earned,
                "average_score": progress.average_score,
                "last_activity": progress.last_activity_at.isoformat() if progress.last_activity_at else None,
                "started_at": progress.started_at.isoformat(),
                "completed_at": progress.completed_at.isoformat() if progress.completed_at else None
            })
    
    # Sort by last activity
    courses_progress.sort(
        key=lambda x: x["last_activity"] or x["started_at"],
        reverse=True
    )
    
    return {
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "total_xp": current_user.total_xp,
            "level": current_user.level,
            "xp_to_next_level": current_user.xp_to_next_level,
            "xp_progress_percentage": current_user.xp_progress_percentage,
            "current_streak": current_user.current_streak,
            "longest_streak": current_user.longest_streak
        },
        "statistics": {
            "total_courses": total_courses,
            "completed_courses": completed_courses,
            "in_progress_courses": in_progress_courses,
            "completion_rate": (completed_courses / total_courses * 100) if total_courses > 0 else 0,
            "recent_xp_gained": recent_xp,
            "total_time_spent": sum(p.total_time_spent for p in progress_records)
        },
        "courses": courses_progress
    }


@router.get("/courses/{course_id}", response_model=CourseProgressDetail)
async def get_course_progress(
    course_id: int,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed progress for a specific course.
    """
    # Get user progress for the course
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.course_id == course_id
    ).first()
    
    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No progress found for this course"
        )
    
    # Get course details
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Get chapter details with progress
    chapters_data = []
    for chapter in course.chapters:
        if not chapter.is_published:
            continue
        
        # Get segments for the chapter
        segments = db.query(Segment).filter(
            Segment.chapter_id == chapter.id,
            Segment.is_published == True
        ).order_by(Segment.order_index).all()
        
        # Calculate chapter progress
        completed_segments = [s for s in segments if s.id in progress.completed_segments]
        chapter_progress = (len(completed_segments) / len(segments) * 100) if segments else 0
        
        # Get segment details
        segments_data = []
        for segment in segments:
            # Get best attempt
            best_attempt = db.query(SegmentAttempt).filter(
                SegmentAttempt.user_id == current_user.id,
                SegmentAttempt.segment_id == segment.id
            ).order_by(SegmentAttempt.score.desc()).first()
            
            segments_data.append({
                "id": segment.id,
                "title": segment.title,
                "type": segment.type,
                "is_completed": segment.id in progress.completed_segments,
                "best_score": best_attempt.score if best_attempt else None,
                "attempts": db.query(SegmentAttempt).filter(
                    SegmentAttempt.user_id == current_user.id,
                    SegmentAttempt.segment_id == segment.id
                ).count(),
                "xp_earned": best_attempt.xp_earned if best_attempt else 0
            })
        
        chapters_data.append({
            "id": chapter.id,
            "title": chapter.title,
            "slug": chapter.slug,
            "is_unlocked": chapter.id in progress.unlocked_chapters,
            "is_completed": chapter.id in progress.completed_chapters,
            "progress_percentage": chapter_progress,
            "score": progress.chapter_scores.get(str(chapter.id)),
            "segments": segments_data,
            "total_segments": len(segments),
            "completed_segments": len(completed_segments)
        })
    
    # Calculate time spent per chapter
    time_by_chapter = {}
    attempts = db.query(SegmentAttempt).join(Segment).filter(
        SegmentAttempt.user_id == current_user.id,
        Segment.chapter_id.in_([c.id for c in course.chapters])
    ).all()
    
    for attempt in attempts:
        chapter_id = attempt.segment.chapter_id
        if chapter_id not in time_by_chapter:
            time_by_chapter[chapter_id] = 0
        time_by_chapter[chapter_id] += attempt.time_spent
    
    return {
        "course": {
            "id": course.id,
            "title": course.title,
            "total_chapters": len([c for c in course.chapters if c.is_published]),
            "total_xp": course.total_xp
        },
        "progress": {
            "status": progress.status,
            "progress_percentage": progress.progress_percentage,
            "total_xp_earned": progress.total_xp_earned,
            "average_score": progress.average_score,
            "current_chapter_id": progress.current_chapter_id,
            "current_segment_id": progress.current_segment_id,
            "learning_path": progress.learning_path,
            "started_at": progress.started_at.isoformat(),
            "completed_at": progress.completed_at.isoformat() if progress.completed_at else None,
            "last_activity_at": progress.last_activity_at.isoformat() if progress.last_activity_at else None
        },
        "chapters": chapters_data,
        "time_spent_by_chapter": time_by_chapter
    }


@router.get("/xp/history", response_model=XPHistory)
async def get_xp_history(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get user's XP earning history.
    """
    # Calculate date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Get XP records
    xp_records = db.query(UserXP).filter(
        UserXP.user_id == current_user.id,
        UserXP.earned_at >= start_date
    ).order_by(UserXP.earned_at.desc()).all()
    
    # Group by day
    daily_xp = {}
    for record in xp_records:
        day_key = record.earned_at.date().isoformat()
        if day_key not in daily_xp:
            daily_xp[day_key] = {
                "date": day_key,
                "total_xp": 0,
                "activities": []
            }
        
        daily_xp[day_key]["total_xp"] += record.xp_amount
        daily_xp[day_key]["activities"].append({
            "xp_amount": record.xp_amount,
            "xp_type": record.xp_type,
            "description": record.description,
            "earned_at": record.earned_at.isoformat()
        })
    
    # Fill in missing days with zero
    current_date = start_date.date()
    while current_date <= end_date.date():
        day_key = current_date.isoformat()
        if day_key not in daily_xp:
            daily_xp[day_key] = {
                "date": day_key,
                "total_xp": 0,
                "activities": []
            }
        current_date += timedelta(days=1)
    
    # Sort by date
    daily_data = sorted(daily_xp.values(), key=lambda x: x["date"])
    
    # Calculate statistics
    total_xp = sum(record.xp_amount for record in xp_records)
    avg_daily_xp = total_xp / days if days > 0 else 0
    max_daily_xp = max((d["total_xp"] for d in daily_data), default=0)
    
    # Get XP by type
    xp_by_type = {}
    for record in xp_records:
        if record.xp_type not in xp_by_type:
            xp_by_type[record.xp_type] = 0
        xp_by_type[record.xp_type] += record.xp_amount
    
    return {
        "period": {
            "start_date": start_date.date().isoformat(),
            "end_date": end_date.date().isoformat(),
            "days": days
        },
        "statistics": {
            "total_xp": total_xp,
            "average_daily_xp": avg_daily_xp,
            "max_daily_xp": max_daily_xp,
            "days_active": len([d for d in daily_data if d["total_xp"] > 0])
        },
        "daily_breakdown": daily_data,
        "xp_by_type": xp_by_type,
        "recent_activities": [
            {
                "xp_amount": record.xp_amount,
                "xp_type": record.xp_type,
                "description": record.description,
                "course_id": record.course_id,
                "chapter_id": record.chapter_id,
                "segment_id": record.segment_id,
                "earned_at": record.earned_at.isoformat()
            }
            for record in xp_records[:20]  # Last 20 activities
        ]
    }


@router.get("/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(
    period: str = Query("all", regex="^(all|month|week|today)$"),
    limit: int = Query(20, ge=1, le=100),
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get XP leaderboard for specified period.
    """
    # Build query based on period
    query = db.query(
        User.id,
        User.username,
        User.avatar_url,
        User.level
    )
    
    if period == "all":
        # All-time leaderboard
        query = query.add_columns(User.total_xp.label("xp_amount"))
        query = query.order_by(User.total_xp.desc())
    else:
        # Period-based leaderboard
        if period == "today":
            start_date = date.today()
        elif period == "week":
            start_date = date.today() - timedelta(days=7)
        elif period == "month":
            start_date = date.today() - timedelta(days=30)
        
        # Join with XP records and sum
        xp_subquery = db.query(
            UserXP.user_id,
            func.sum(UserXP.xp_amount).label("period_xp")
        ).filter(
            func.date(UserXP.earned_at) >= start_date
        ).group_by(UserXP.user_id).subquery()
        
        query = query.join(
            xp_subquery,
            User.id == xp_subquery.c.user_id
        ).add_columns(xp_subquery.c.period_xp.label("xp_amount"))
        query = query.order_by(xp_subquery.c.period_xp.desc())
    
    # Get top users
    top_users = query.limit(limit).all()
    
    # Find current user's rank if authenticated
    user_rank = None
    if current_user:
        if period == "all":
            # Count users with more XP
            user_rank = db.query(User).filter(
                User.total_xp > current_user.total_xp
            ).count() + 1
        else:
            # Get current user's period XP
            user_period_xp = db.query(
                func.sum(UserXP.xp_amount)
            ).filter(
                UserXP.user_id == current_user.id,
                func.date(UserXP.earned_at) >= start_date
            ).scalar() or 0
            
            # Count users with more period XP
            better_users = db.query(
                UserXP.user_id
            ).filter(
                func.date(UserXP.earned_at) >= start_date
            ).group_by(
                UserXP.user_id
            ).having(
                func.sum(UserXP.xp_amount) > user_period_xp
            ).count()
            
            user_rank = better_users + 1
    
    # Format leaderboard
    leaderboard = []
    for idx, user in enumerate(top_users, 1):
        leaderboard.append({
            "rank": idx,
            "user_id": user.id,
            "username": user.username,
            "avatar_url": user.avatar_url,
            "level": user.level,
            "xp_amount": user.xp_amount or 0,
            "is_current_user": current_user and user.id == current_user.id
        })
    
    # Add current user if not in top list
    if current_user and user_rank and user_rank > limit:
        if period == "all":
            user_xp = current_user.total_xp
        else:
            user_xp = db.query(
                func.sum(UserXP.xp_amount)
            ).filter(
                UserXP.user_id == current_user.id,
                func.date(UserXP.earned_at) >= start_date
            ).scalar() or 0
        
        leaderboard.append({
            "rank": user_rank,
            "user_id": current_user.id,
            "username": current_user.username,
            "avatar_url": current_user.avatar_url,
            "level": current_user.level,
            "xp_amount": user_xp,
            "is_current_user": True
        })
    
    return leaderboard


@router.get("/stats", response_model=LearningStats)
async def get_learning_stats(
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed learning statistics for the user.
    """
    # Get all attempts
    all_attempts = db.query(SegmentAttempt).filter(
        SegmentAttempt.user_id == current_user.id
    ).all()
    
    # Calculate statistics
    total_attempts = len(all_attempts)
    successful_attempts = len([a for a in all_attempts if a.score >= a.segment.required_score])
    
    # Time statistics
    total_time = sum(a.time_spent for a in all_attempts)
    
    # Get favorite course (most time spent)
    time_by_course = {}
    for attempt in all_attempts:
        course_id = attempt.segment.chapter.course_id
        if course_id not in time_by_course:
            time_by_course[course_id] = 0
        time_by_course[course_id] += attempt.time_spent
    
    favorite_course_id = max(time_by_course.items(), key=lambda x: x[1])[0] if time_by_course else None
    favorite_course = None
    if favorite_course_id:
        course = db.query(Course).filter(Course.id == favorite_course_id).first()
        if course:
            favorite_course = {
                "id": course.id,
                "title": course.title,
                "time_spent": time_by_course[favorite_course_id]
            }
    
    # Activity by day of week
    activity_by_dow = {i: 0 for i in range(7)}  # 0=Monday, 6=Sunday
    for attempt in all_attempts:
        dow = attempt.started_at.weekday()
        activity_by_dow[dow] += 1
    
    # Most productive day
    most_productive_dow = max(activity_by_dow.items(), key=lambda x: x[1])[0]
    dow_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # Difficulty breakdown
    difficulty_stats = {
        "beginner": {"attempts": 0, "success_rate": 0},
        "intermediate": {"attempts": 0, "success_rate": 0},
        "advanced": {"attempts": 0, "success_rate": 0},
        "expert": {"attempts": 0, "success_rate": 0}
    }
    
    for attempt in all_attempts:
        difficulty = attempt.segment.chapter.course.difficulty_level
        if difficulty in difficulty_stats:
            difficulty_stats[difficulty]["attempts"] += 1
            if attempt.score >= attempt.segment.required_score:
                difficulty_stats[difficulty]["success_rate"] += 1
    
    # Calculate success rates
    for diff in difficulty_stats:
        if difficulty_stats[diff]["attempts"] > 0:
            difficulty_stats[diff]["success_rate"] = (
                difficulty_stats[diff]["success_rate"] / 
                difficulty_stats[diff]["attempts"] * 100
            )
    
    # Learning velocity (XP per day over last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_xp = db.query(
        func.sum(UserXP.xp_amount)
    ).filter(
        UserXP.user_id == current_user.id,
        UserXP.earned_at >= thirty_days_ago
    ).scalar() or 0
    
    learning_velocity = recent_xp / 30
    
    return {
        "overview": {
            "total_attempts": total_attempts,
            "successful_attempts": successful_attempts,
            "success_rate": (successful_attempts / total_attempts * 100) if total_attempts > 0 else 0,
            "total_time_spent": total_time,
            "average_time_per_attempt": total_time // total_attempts if total_attempts > 0 else 0,
            "total_courses_enrolled": db.query(UserProgress).filter(
                UserProgress.user_id == current_user.id
            ).count(),
            "total_xp_earned": current_user.total_xp,
            "current_level": current_user.level
        },
        "learning_patterns": {
            "most_productive_day": dow_names[most_productive_dow],
            "activity_by_day": {
                dow_names[i]: count 
                for i, count in activity_by_dow.items()
            },
            "favorite_course": favorite_course,
            "learning_velocity": learning_velocity
        },
        "performance_by_difficulty": difficulty_stats,
        "streaks": {
            "current_streak": current_user.current_streak,
            "longest_streak": current_user.longest_streak,
            "last_active_date": current_user.last_active_date.isoformat() if current_user.last_active_date else None
        }
    }


@router.get("/streaks", response_model=StreakInfo)
async def get_streak_info(
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed streak information for the user.
    """
    # Calculate if streak is at risk
    streak_at_risk = False
    if current_user.last_active_date:
        days_since_active = (datetime.utcnow().date() - current_user.last_active_date.date()).days
        streak_at_risk = days_since_active == 1  # Will break tomorrow if no activity
    
    # Get activity calendar (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    daily_activity = db.query(
        func.date(UserXP.earned_at).label("date"),
        func.count(UserXP.id).label("activities")
    ).filter(
        UserXP.user_id == current_user.id,
        UserXP.earned_at >= thirty_days_ago
    ).group_by(
        func.date(UserXP.earned_at)
    ).all()
    
    # Create activity calendar
    activity_calendar = {}
    current_date = thirty_days_ago.date()
    while current_date <= datetime.utcnow().date():
        activity_calendar[current_date.isoformat()] = False
        current_date += timedelta(days=1)
    
    # Mark active days
    for activity in daily_activity:
        activity_calendar[activity.date.isoformat()] = True
    
    # Get streak milestones
    milestones = [
        {"days": 7, "name": "Week Warrior", "achieved": current_user.longest_streak >= 7},
        {"days": 30, "name": "Monthly Master", "achieved": current_user.longest_streak >= 30},
        {"days": 100, "name": "Century Club", "achieved": current_user.longest_streak >= 100},
        {"days": 365, "name": "Year-long Learner", "achieved": current_user.longest_streak >= 365}
    ]
    
    return {
        "current_streak": current_user.current_streak,
        "longest_streak": current_user.longest_streak,
        "last_active_date": current_user.last_active_date.isoformat() if current_user.last_active_date else None,
        "streak_at_risk": streak_at_risk,
        "activity_calendar": activity_calendar,
        "milestones": milestones,
        "days_until_next_milestone": next(
            (m["days"] - current_user.current_streak 
             for m in milestones 
             if m["days"] > current_user.current_streak),
            None
        )
    }


@router.post("/update-position", response_model=ProgressUpdate)
async def update_learning_position(
    course_id: int,
    chapter_id: Optional[int] = None,
    segment_id: Optional[int] = None,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Update user's current position in a course.
    """
    # Get user progress
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.course_id == course_id
    ).first()
    
    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not enrolled in this course"
        )
    
    # Update position
    if chapter_id:
        # Verify chapter is unlocked
        if chapter_id not in progress.unlocked_chapters:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chapter is locked"
            )
        progress.current_chapter_id = chapter_id
    
    if segment_id:
        # Verify segment exists and is accessible
        segment = db.query(Segment).filter(
            Segment.id == segment_id,
            Segment.chapter_id.in_(progress.unlocked_chapters)
        ).first()
        
        if not segment:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Segment is not accessible"
            )
        progress.current_segment_id = segment_id
    
    progress.last_activity_at = datetime.utcnow()
    db.commit()
    
    return {
        "message": "Position updated successfully",
        "current_chapter_id": progress.current_chapter_id,
        "current_segment_id": progress.current_segment_id
    }