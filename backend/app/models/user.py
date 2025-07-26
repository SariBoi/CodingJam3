"""
User model for Spark LMS.

Defines the User table with authentication fields, profile information,
and relationships to progress tracking.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Boolean, Column, Integer, String, DateTime, Text, 
    UniqueConstraint, Index, CheckConstraint
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class User(Base):
    """
    User model for authentication and profile management.
    """
    __tablename__ = "users"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Authentication fields
    email: Mapped[str] = mapped_column(
        String(255), 
        unique=True, 
        index=True, 
        nullable=False
    )
    username: Mapped[str] = mapped_column(
        String(50), 
        unique=True, 
        index=True, 
        nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Profile fields
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Status fields
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # XP and level tracking
    total_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    # Streak tracking
    current_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_active_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Preferences
    preferred_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
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
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Password reset tracking
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Account limits and quotas
    max_courses: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    daily_xp_limit: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    
    # Relationships
    user_progress = relationship("UserProgress", back_populates="user", cascade="all, delete-orphan")
    segment_attempts = relationship("SegmentAttempt", back_populates="user", cascade="all, delete-orphan")
    user_scores = relationship("UserScore", back_populates="user", cascade="all, delete-orphan")
    user_xp_records = relationship("UserXP", back_populates="user", cascade="all, delete-orphan")
    admin_logs = relationship("AdminLog", back_populates="user", cascade="all, delete-orphan")
    
    # Table constraints
    __table_args__ = (
        CheckConstraint("total_xp >= 0", name="check_xp_positive"),
        CheckConstraint("level >= 1", name="check_level_positive"),
        CheckConstraint("current_streak >= 0", name="check_streak_positive"),
        CheckConstraint("longest_streak >= current_streak", name="check_longest_streak"),
        Index("idx_user_email_active", "email", "is_active"),
        Index("idx_user_username_active", "username", "is_active"),
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}')>"
    
    @property
    def display_name(self) -> str:
        """Get user's display name (full name or username)."""
        return self.full_name or self.username
    
    @property
    def is_premium(self) -> bool:
        """Check if user has premium features (based on level or admin status)."""
        return self.is_admin or self.level >= 10
    
    @property
    def xp_to_next_level(self) -> int:
        """Calculate XP needed for next level."""
        # Simple formula: next_level_xp = level * 100
        return self.level * 100
    
    @property
    def xp_progress_percentage(self) -> float:
        """Calculate progress percentage to next level."""
        current_level_xp = (self.level - 1) * 100
        xp_in_current_level = self.total_xp - current_level_xp
        return (xp_in_current_level / self.xp_to_next_level) * 100
    
    def update_level(self) -> None:
        """Update user level based on total XP."""
        # Simple level calculation: level = (total_xp // 100) + 1
        new_level = (self.total_xp // 100) + 1
        if new_level != self.level:
            self.level = new_level
    
    def add_xp(self, amount: int) -> None:
        """Add XP and update level if necessary."""
        self.total_xp += amount
        self.update_level()
    
    def update_streak(self, activity_date: datetime) -> None:
        """Update user's learning streak."""
        if not self.last_active_date:
            # First activity
            self.current_streak = 1
            self.longest_streak = 1
        else:
            days_diff = (activity_date.date() - self.last_active_date.date()).days
            
            if days_diff == 0:
                # Same day activity, no change
                pass
            elif days_diff == 1:
                # Consecutive day, increment streak
                self.current_streak += 1
                if self.current_streak > self.longest_streak:
                    self.longest_streak = self.current_streak
            else:
                # Streak broken
                self.current_streak = 1
        
        self.last_active_date = activity_date
    
    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Convert user to dictionary representation."""
        data = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "bio": self.bio,
            "avatar_url": self.avatar_url,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "is_verified": self.is_verified,
            "total_xp": self.total_xp,
            "level": self.level,
            "current_streak": self.current_streak,
            "longest_streak": self.longest_streak,
            "preferred_language": self.preferred_language,
            "timezone": self.timezone,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }
        
        if include_sensitive:
            data.update({
                "email_notifications": self.email_notifications,
                "max_courses": self.max_courses,
                "daily_xp_limit": self.daily_xp_limit,
                "email_verified_at": self.email_verified_at.isoformat() if self.email_verified_at else None,
            })
        
        return data