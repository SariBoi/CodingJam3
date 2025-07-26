"""
Progress tracking models for Spark LMS.

Defines UserProgress, SegmentAttempt, UserScore, and UserXP models
for tracking user progress through courses.
"""

from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum
from sqlalchemy import (
    Boolean, Column, Integer, String, DateTime, Text, Float,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, JSON
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class ProgressStatus(str, Enum):
    """Status of user progress in a course or chapter."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    LOCKED = "locked"


class AttemptStatus(str, Enum):
    """Status of a segment attempt."""
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class UserProgress(Base):
    """
    Tracks overall user progress through courses and chapters.
    """
    __tablename__ = "user_progress"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # User and course relationship
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    
    # Current position in course
    current_chapter_id: Mapped[Optional[int]] = mapped_column(
        Integer, 
        ForeignKey("chapters.id"), 
        nullable=True
    )
    current_segment_id: Mapped[Optional[int]] = mapped_column(
        Integer, 
        ForeignKey("segments.id"), 
        nullable=True
    )
    
    # Progress tracking
    status: Mapped[str] = mapped_column(
        String(20),
        default=ProgressStatus.NOT_STARTED.value,
        nullable=False
    )
    progress_percentage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    # Chapter completion tracking
    completed_chapters: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)
    unlocked_chapters: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)
    chapter_scores: Mapped[Dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)  # chapter_id -> score
    
    # Segment completion tracking
    completed_segments: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)
    segment_scores: Mapped[Dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)  # segment_id -> score
    
    # XP and scoring
    total_xp_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    # Time tracking
    total_time_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # in seconds
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Learning path tracking
    learning_path: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)  # Ordered list of chapter IDs taken
    current_path_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Timestamps
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    # Relationships
    user = relationship("User", back_populates="user_progress")
    course = relationship("Course", back_populates="user_progress")
    current_chapter = relationship("Chapter", foreign_keys=[current_chapter_id])
    current_segment = relationship("Segment", foreign_keys=[current_segment_id])
    
    # Table constraints
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_user_course_progress"),
        CheckConstraint("progress_percentage >= 0 AND progress_percentage <= 100", name="check_progress_percentage"),
        CheckConstraint("total_xp_earned >= 0", name="check_progress_xp_positive"),
        Index("idx_user_progress_status", "user_id", "status"),
        Index("idx_course_progress", "course_id", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<UserProgress(user_id={self.user_id}, course_id={self.course_id}, progress={self.progress_percentage}%)>"
    
    def update_progress(self) -> None:
        """Update progress percentage based on completed chapters."""
        if not self.course or not self.course.chapters:
            return
        
        total_chapters = len(self.course.chapters)
        if total_chapters == 0:
            return
        
        self.progress_percentage = (len(self.completed_chapters) / total_chapters) * 100
        
        if self.progress_percentage >= 100:
            self.status = ProgressStatus.COMPLETED.value
            if not self.completed_at:
                self.completed_at = datetime.utcnow()
        elif self.progress_percentage > 0:
            self.status = ProgressStatus.IN_PROGRESS.value
    
    def add_completed_chapter(self, chapter_id: int, score: int) -> None:
        """Mark a chapter as completed and update progress."""
        if chapter_id not in self.completed_chapters:
            self.completed_chapters = self.completed_chapters + [chapter_id]
        
        self.chapter_scores[str(chapter_id)] = score
        self.update_progress()
        self.update_average_score()
    
    def update_average_score(self) -> None:
        """Update average score across all completed chapters."""
        if not self.chapter_scores:
            return
        
        scores = list(self.chapter_scores.values())
        self.average_score = sum(scores) / len(scores)


class SegmentAttempt(Base):
    """
    Records individual attempts at segments.
    """
    __tablename__ = "segment_attempts"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Relationships
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    segment_id: Mapped[int] = mapped_column(Integer, ForeignKey("segments.id"), nullable=False)
    
    # Attempt details
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default=AttemptStatus.IN_PROGRESS.value,
        nullable=False
    )
    
    # For activities: submitted code
    submitted_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # For explanations: MCQ answers
    mcq_answers: Mapped[Optional[List[dict]]] = mapped_column(JSON, nullable=True)
    
    # Results
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Help used
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    solution_viewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Execution results (for activities)
    execution_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    test_results: Mapped[Optional[List[dict]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Time tracking
    time_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # in seconds
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="segment_attempts")
    segment = relationship("Segment", back_populates="attempts")
    
    # Table constraints
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="check_attempt_score"),
        CheckConstraint("xp_earned >= 0", name="check_attempt_xp_positive"),
        CheckConstraint("attempt_number > 0", name="check_attempt_number_positive"),
        Index("idx_user_segment_attempts", "user_id", "segment_id", "attempt_number"),
        Index("idx_segment_attempt_status", "segment_id", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<SegmentAttempt(id={self.id}, user_id={self.user_id}, segment_id={self.segment_id}, attempt={self.attempt_number})>"
    
    def calculate_score(self) -> int:
        """Calculate score based on attempt results."""
        if self.segment.type == "activity":
            # Score based on test results
            if not self.test_results:
                return 0
            
            passed = sum(1 for test in self.test_results if test.get("passed", False))
            total = len(self.test_results)
            return int((passed / total) * 100) if total > 0 else 0
        
        elif self.segment.type == "explanation":
            # Score based on MCQ answers
            if not self.mcq_answers or not self.segment.mcq_questions:
                return 100  # No questions = automatic pass
            
            correct = 0
            for i, answer in enumerate(self.mcq_answers):
                if i < len(self.segment.mcq_questions):
                    question = self.segment.mcq_questions[i]
                    if answer.get("selected") == question.get("correct_answer"):
                        correct += 1
            
            total = len(self.segment.mcq_questions)
            return int((correct / total) * 100) if total > 0 else 0
        
        return 0


class UserScore(Base):
    """
    Stores final scores for completed chapters and segments.
    """
    __tablename__ = "user_scores"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # User relationship
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Content relationship (either chapter or segment)
    chapter_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True)
    segment_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("segments.id"), nullable=True)
    
    # Score details
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    
    # Attempt information
    attempts_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    best_score: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Time information
    total_time_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # in seconds
    achieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    user = relationship("User", back_populates="user_scores")
    chapter = relationship("Chapter", foreign_keys=[chapter_id])
    segment = relationship("Segment", foreign_keys=[segment_id])
    
    # Table constraints
    __table_args__ = (
        CheckConstraint("(chapter_id IS NOT NULL AND segment_id IS NULL) OR (chapter_id IS NULL AND segment_id IS NOT NULL)", 
                       name="check_either_chapter_or_segment"),
        CheckConstraint("score >= 0 AND score <= max_score", name="check_score_range"),
        UniqueConstraint("user_id", "chapter_id", name="uq_user_chapter_score"),
        UniqueConstraint("user_id", "segment_id", name="uq_user_segment_score"),
        Index("idx_user_scores", "user_id", "passed"),
    )
    
    def __repr__(self) -> str:
        content_type = "chapter" if self.chapter_id else "segment"
        content_id = self.chapter_id or self.segment_id
        return f"<UserScore(user_id={self.user_id}, {content_type}_id={content_id}, score={self.score})>"


class UserXP(Base):
    """
    XP transaction history for users.
    """
    __tablename__ = "user_xp"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # User relationship
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    
    # XP details
    xp_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    xp_type: Mapped[str] = mapped_column(String(50), nullable=False)  # segment_completion, chapter_completion, bonus, etc.
    
    # Source of XP
    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True)
    segment_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("segments.id"), nullable=True)
    
    # Description
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Timestamp
    earned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    user = relationship("User", back_populates="user_xp_records")
    course = relationship("Course", foreign_keys=[course_id])
    chapter = relationship("Chapter", foreign_keys=[chapter_id])
    segment = relationship("Segment", foreign_keys=[segment_id])
    
    # Table constraints
    __table_args__ = (
        CheckConstraint("xp_amount != 0", name="check_xp_amount_not_zero"),
        Index("idx_user_xp_earned", "user_id", "earned_at"),
        Index("idx_user_xp_type", "user_id", "xp_type"),
    )
    
    def __repr__(self) -> str:
        return f"<UserXP(user_id={self.user_id}, amount={self.xp_amount}, type='{self.xp_type}')>"
    
    @classmethod
    def create_xp_record(
        cls,
        user_id: int,
        xp_amount: int,
        xp_type: str,
        description: str,
        course_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        segment_id: Optional[int] = None
    ) -> "UserXP":
        """Factory method to create XP records."""
        return cls(
            user_id=user_id,
            xp_amount=xp_amount,
            xp_type=xp_type,
            description=description,
            course_id=course_id,
            chapter_id=chapter_id,
            segment_id=segment_id
        )