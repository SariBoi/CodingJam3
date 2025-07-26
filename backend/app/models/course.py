"""
Course models for Spark LMS.

Defines Course, Chapter, Segment, and ChapterPath models for
the learning content structure and dynamic learning paths.
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum
from sqlalchemy import (
    Boolean, Column, Integer, String, DateTime, Text, Float,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, JSON
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.core.database import Base


class DifficultyLevel(str, Enum):
    """Difficulty levels for courses and content."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class SegmentType(str, Enum):
    """Types of segments in a chapter."""
    EXPLANATION = "explanation"
    ACTIVITY = "activity"


class ContentStatus(str, Enum):
    """Status of content items."""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Course(Base):
    """
    Course model representing a complete learning path.
    """
    __tablename__ = "courses"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Basic information
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    short_description: Mapped[str] = mapped_column(String(500), nullable=False)
    
    # Visual elements
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    banner_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Icon class or emoji
    
    # Course metadata
    difficulty_level: Mapped[str] = mapped_column(
        String(20), 
        default=DifficultyLevel.BEGINNER.value,
        nullable=False
    )
    estimated_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    prerequisites: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    
    # Publishing and visibility
    status: Mapped[str] = mapped_column(
        String(20),
        default=ContentStatus.DRAFT.value,
        nullable=False
    )
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_free: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Ordering and organization
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # XP and scoring
    total_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passing_score: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    
    # Statistics
    enrolled_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    # Author information
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    chapters = relationship("Chapter", back_populates="course", cascade="all, delete-orphan")
    user_progress = relationship("UserProgress", back_populates="course", cascade="all, delete-orphan")
    author = relationship("User", backref="authored_courses")
    
    # Table constraints
    __table_args__ = (
        CheckConstraint("passing_score >= 0 AND passing_score <= 100", name="check_passing_score_range"),
        CheckConstraint("total_xp >= 0", name="check_course_xp_positive"),
        CheckConstraint("average_rating >= 0 AND average_rating <= 5", name="check_rating_range"),
        Index("idx_course_status_featured", "status", "is_featured"),
        Index("idx_course_category_status", "category", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<Course(id={self.id}, title='{self.title}', slug='{self.slug}')>"
    
    def calculate_total_xp(self) -> int:
        """Calculate total XP available in the course."""
        total = 0
        for chapter in self.chapters:
            total += chapter.calculate_total_xp()
        return total
    
    def update_statistics(self) -> None:
        """Update course statistics (should be called periodically)."""
        self.total_xp = self.calculate_total_xp()


class Chapter(Base):
    """
    Chapter model representing a unit within a course.
    """
    __tablename__ = "chapters"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Basic information
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Course relationship
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    
    # Node-based workflow position (for admin canvas)
    node_id: Mapped[str] = mapped_column(String(50), nullable=False, default=lambda: str(uuid.uuid4())[:8])
    position_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    position_y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    # Chapter metadata
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    difficulty_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    # XP and scoring
    total_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passing_score: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    
    # Visibility
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    # Relationships
    course = relationship("Course", back_populates="chapters")
    segments = relationship("Segment", back_populates="chapter", cascade="all, delete-orphan")
    
    # Dynamic paths (outgoing connections)
    outgoing_paths = relationship(
        "ChapterPath",
        foreign_keys="ChapterPath.from_chapter_id",
        back_populates="from_chapter",
        cascade="all, delete-orphan"
    )
    
    # Dynamic paths (incoming connections)
    incoming_paths = relationship(
        "ChapterPath",
        foreign_keys="ChapterPath.to_chapter_id",
        back_populates="to_chapter"
    )
    
    # Table constraints
    __table_args__ = (
        UniqueConstraint("course_id", "slug", name="uq_chapter_course_slug"),
        UniqueConstraint("course_id", "node_id", name="uq_chapter_course_node"),
        CheckConstraint("passing_score >= 0 AND passing_score <= 100", name="check_chapter_passing_score"),
        Index("idx_chapter_course_order", "course_id", "order_index"),
    )
    
    def __repr__(self) -> str:
        return f"<Chapter(id={self.id}, title='{self.title}', course_id={self.course_id})>"
    
    def calculate_total_xp(self) -> int:
        """Calculate total XP available in the chapter."""
        return sum(segment.xp_value for segment in self.segments)
    
    def get_next_chapters(self, user_score: Optional[int] = None) -> List["Chapter"]:
        """Get next possible chapters based on user score."""
        next_chapters = []
        for path in self.outgoing_paths:
            if path.evaluate_condition(user_score):
                next_chapters.append(path.to_chapter)
        return next_chapters


class Segment(Base):
    """
    Segment model representing a learning unit within a chapter.
    Can be either an explanation or an activity.
    """
    __tablename__ = "segments"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Basic information
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # explanation or activity
    
    # Chapter relationship
    chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=False)
    
    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)  # Markdown for explanation, instructions for activity
    
    # Activity-specific fields (null for explanations)
    code_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Starting code for activities
    test_cases: Mapped[Optional[List[dict]]] = mapped_column(JSON, nullable=True)  # Test cases for validation
    expected_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hints: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    solution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Multiple choice questions (for explanations)
    mcq_questions: Mapped[Optional[List[dict]]] = mapped_column(JSON, nullable=True)
    
    # Segment metadata
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp_value: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    
    # Requirements
    required_score: Mapped[int] = mapped_column(Integer, default=100, nullable=False)  # Score needed to unlock next
    time_limit_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Visibility
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    # Relationships
    chapter = relationship("Chapter", back_populates="segments")
    attempts = relationship("SegmentAttempt", back_populates="segment", cascade="all, delete-orphan")
    
    # Table constraints
    __table_args__ = (
        CheckConstraint("xp_value >= 0", name="check_segment_xp_positive"),
        CheckConstraint("max_attempts > 0", name="check_max_attempts_positive"),
        CheckConstraint("required_score >= 0 AND required_score <= 100", name="check_segment_required_score"),
        CheckConstraint("type IN ('explanation', 'activity')", name="check_segment_type"),
        Index("idx_segment_chapter_order", "chapter_id", "order_index"),
    )
    
    def __repr__(self) -> str:
        return f"<Segment(id={self.id}, title='{self.title}', type='{self.type}')>"
    
    def calculate_xp_for_attempt(self, attempt_number: int, hints_used: int, solution_viewed: bool) -> int:
        """Calculate XP based on attempt number and help used."""
        xp = self.xp_value
        
        # Reduce XP for multiple attempts
        xp -= int(xp * 0.1 * (attempt_number - 1))
        
        # Reduce XP for hints
        xp -= int(xp * 0.2 * hints_used)
        
        # Reduce XP for viewing solution
        if solution_viewed:
            xp = int(xp * 0.5)
        
        return max(0, xp)


class ChapterPath(Base):
    """
    Dynamic learning path connections between chapters.
    Supports conditional branching based on user performance.
    """
    __tablename__ = "chapter_paths"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Connection
    from_chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=False)
    to_chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=False)
    
    # Condition for this path
    condition_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # "score_gt", "score_lt", "score_eq", "default"
    condition_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # The score threshold
    condition_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Display label like "score > 70"
    
    # Path metadata
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    order_priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # For ordering multiple paths
    
    # Visual properties for admin canvas
    path_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)  # Hex color
    path_style: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # solid, dashed, etc.
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    from_chapter = relationship("Chapter", foreign_keys=[from_chapter_id], back_populates="outgoing_paths")
    to_chapter = relationship("Chapter", foreign_keys=[to_chapter_id], back_populates="incoming_paths")
    
    # Table constraints
    __table_args__ = (
        UniqueConstraint("from_chapter_id", "to_chapter_id", "condition_type", "condition_value", 
                        name="uq_chapter_path_condition"),
        CheckConstraint("from_chapter_id != to_chapter_id", name="check_no_self_loop"),
        Index("idx_chapter_path_from", "from_chapter_id"),
        Index("idx_chapter_path_to", "to_chapter_id"),
    )
    
    def __repr__(self) -> str:
        return f"<ChapterPath(from={self.from_chapter_id}, to={self.to_chapter_id}, condition='{self.condition_label}')>"
    
    def evaluate_condition(self, user_score: Optional[int]) -> bool:
        """Evaluate if this path should be taken based on user score."""
        if self.is_default or not self.condition_type:
            return True
        
        if user_score is None:
            return False
        
        if self.condition_type == "score_gt":
            return user_score > self.condition_value
        elif self.condition_type == "score_lt":
            return user_score < self.condition_value
        elif self.condition_type == "score_eq":
            return user_score == self.condition_value
        elif self.condition_type == "score_gte":
            return user_score >= self.condition_value
        elif self.condition_type == "score_lte":
            return user_score <= self.condition_value
        
        return False