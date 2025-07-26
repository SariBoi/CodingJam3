"""
Admin-specific models for Spark LMS.

Defines AdminLog, CourseAnalytics, and SystemSettings models
for administrative features and analytics.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum
from sqlalchemy import (
    Boolean, Column, Integer, String, DateTime, Text, Float,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, JSON
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class AdminAction(str, Enum):
    """Types of admin actions to log."""
    LOGIN = "login"
    LOGOUT = "logout"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    PUBLISH = "publish"
    UNPUBLISH = "unpublish"
    EXPORT = "export"
    IMPORT = "import"
    SETTINGS_CHANGE = "settings_change"
    USER_MANAGEMENT = "user_management"
    BULK_OPERATION = "bulk_operation"


class AnalyticsPeriod(str, Enum):
    """Time periods for analytics aggregation."""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AdminLog(Base):
    """
    Audit log for admin actions.
    """
    __tablename__ = "admin_logs"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # User who performed the action
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Action details
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # course, chapter, segment, user, etc.
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Action metadata
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # Supports IPv6
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Results
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    user = relationship("User", back_populates="admin_logs")
    
    # Table constraints
    __table_args__ = (
        Index("idx_admin_log_user_action", "user_id", "action"),
        Index("idx_admin_log_entity", "entity_type", "entity_id"),
        Index("idx_admin_log_created", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<AdminLog(id={self.id}, user_id={self.user_id}, action='{self.action}', entity='{self.entity_type}')>"
    
    @classmethod
    def log_action(
        cls,
        user_id: int,
        action: str,
        entity_type: str,
        entity_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> "AdminLog":
        """Factory method to create admin log entries."""
        return cls(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message
        )


class CourseAnalytics(Base):
    """
    Analytics data for courses, aggregated periodically.
    """
    __tablename__ = "course_analytics"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Course relationship
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    
    # Time period
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)  # hourly, daily, weekly, monthly
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    # User engagement metrics
    unique_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_enrollments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Progress metrics
    avg_progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_time_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # in seconds
    
    # Segment metrics
    total_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    solutions_viewed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # XP metrics
    total_xp_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_xp_per_user: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    # Chapter-level breakdown
    chapter_stats: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    
    # Segment-level breakdown
    segment_stats: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    
    # Dropout analysis
    dropout_points: Mapped[Dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)  # chapter_id -> dropout_count
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    course = relationship("Course", backref="analytics")
    
    # Table constraints
    __table_args__ = (
        UniqueConstraint("course_id", "period_type", "period_start", name="uq_course_analytics_period"),
        CheckConstraint("period_end > period_start", name="check_period_valid"),
        CheckConstraint("avg_progress >= 0 AND avg_progress <= 100", name="check_avg_progress_range"),
        Index("idx_course_analytics_period", "course_id", "period_type", "period_start"),
    )
    
    def __repr__(self) -> str:
        return f"<CourseAnalytics(course_id={self.course_id}, period='{self.period_type}', start={self.period_start})>"
    
    def calculate_completion_rate(self) -> float:
        """Calculate completion rate for the period."""
        if self.unique_users == 0:
            return 0.0
        return (self.completions / self.unique_users) * 100
    
    def calculate_success_rate(self) -> float:
        """Calculate success rate for attempts."""
        if self.total_attempts == 0:
            return 0.0
        return (self.successful_attempts / self.total_attempts) * 100


class SystemSettings(Base):
    """
    System-wide settings and configuration.
    """
    __tablename__ = "system_settings"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Setting identification
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)  # string, integer, float, boolean, json
    
    # Setting metadata
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # general, email, security, features, etc.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Can non-admins see this?
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # Can admins edit this?
    
    # Validation
    validation_rules: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    default_value: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Audit
    last_modified_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
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
    
    # Table constraints
    __table_args__ = (
        Index("idx_system_settings_category", "category"),
        Index("idx_system_settings_public", "is_public"),
    )
    
    def __repr__(self) -> str:
        return f"<SystemSettings(key='{self.key}', category='{self.category}')>"
    
    def get_typed_value(self) -> Any:
        """Get the value converted to its proper type."""
        if self.value_type == "string":
            return self.value
        elif self.value_type == "integer":
            return int(self.value)
        elif self.value_type == "float":
            return float(self.value)
        elif self.value_type == "boolean":
            return self.value.lower() in ("true", "1", "yes", "on")
        elif self.value_type == "json":
            import json
            return json.loads(self.value)
        return self.value
    
    def set_typed_value(self, value: Any) -> None:
        """Set the value with proper type conversion."""
        if self.value_type == "json":
            import json
            self.value = json.dumps(value)
        else:
            self.value = str(value)
    
    @classmethod
    def get_default_settings(cls) -> List[Dict[str, Any]]:
        """Get default system settings."""
        return [
            # General settings
            {
                "key": "site_name",
                "value": "Spark LMS",
                "value_type": "string",
                "category": "general",
                "description": "The name of the LMS platform",
                "is_public": True,
                "is_editable": True,
                "default_value": "Spark LMS"
            },
            {
                "key": "site_description",
                "value": "Learn by doing - Interactive learning platform",
                "value_type": "string",
                "category": "general",
                "description": "Site description for SEO and branding",
                "is_public": True,
                "is_editable": True,
                "default_value": "Learn by doing - Interactive learning platform"
            },
            {
                "key": "maintenance_mode",
                "value": "false",
                "value_type": "boolean",
                "category": "general",
                "description": "Enable maintenance mode",
                "is_public": True,
                "is_editable": True,
                "default_value": "false"
            },
            
            # Feature flags
            {
                "key": "enable_registration",
                "value": "true",
                "value_type": "boolean",
                "category": "features",
                "description": "Allow new user registrations",
                "is_public": True,
                "is_editable": True,
                "default_value": "true"
            },
            {
                "key": "enable_social_login",
                "value": "false",
                "value_type": "boolean",
                "category": "features",
                "description": "Enable social media login options",
                "is_public": True,
                "is_editable": True,
                "default_value": "false"
            },
            {
                "key": "enable_certificates",
                "value": "true",
                "value_type": "boolean",
                "category": "features",
                "description": "Enable course completion certificates",
                "is_public": True,
                "is_editable": True,
                "default_value": "true"
            },
            
            # Email settings
            {
                "key": "email_notifications_enabled",
                "value": "true",
                "value_type": "boolean",
                "category": "email",
                "description": "Enable email notifications system-wide",
                "is_public": False,
                "is_editable": True,
                "default_value": "true"
            },
            {
                "key": "email_footer_text",
                "value": "© 2024 Spark LMS. All rights reserved.",
                "value_type": "string",
                "category": "email",
                "description": "Footer text for email templates",
                "is_public": False,
                "is_editable": True,
                "default_value": "© 2024 Spark LMS. All rights reserved."
            },
            
            # Security settings
            {
                "key": "password_min_length",
                "value": "8",
                "value_type": "integer",
                "category": "security",
                "description": "Minimum password length",
                "is_public": False,
                "is_editable": True,
                "default_value": "8",
                "validation_rules": {"min": 6, "max": 32}
            },
            {
                "key": "max_login_attempts",
                "value": "5",
                "value_type": "integer",
                "category": "security",
                "description": "Maximum login attempts before lockout",
                "is_public": False,
                "is_editable": True,
                "default_value": "5",
                "validation_rules": {"min": 3, "max": 10}
            },
            {
                "key": "session_timeout_minutes",
                "value": "1440",
                "value_type": "integer",
                "category": "security",
                "description": "Session timeout in minutes",
                "is_public": False,
                "is_editable": True,
                "default_value": "1440",
                "validation_rules": {"min": 15, "max": 10080}
            },
            
            # Analytics settings
            {
                "key": "analytics_retention_days",
                "value": "90",
                "value_type": "integer",
                "category": "analytics",
                "description": "Days to retain analytics data",
                "is_public": False,
                "is_editable": True,
                "default_value": "90",
                "validation_rules": {"min": 30, "max": 365}
            },
            {
                "key": "enable_anonymous_analytics",
                "value": "true",
                "value_type": "boolean",
                "category": "analytics",
                "description": "Collect anonymous usage statistics",
                "is_public": True,
                "is_editable": True,
                "default_value": "true"
            }
        ]