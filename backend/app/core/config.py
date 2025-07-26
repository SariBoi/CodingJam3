"""
Configuration settings for Spark LMS backend.

Uses Pydantic settings management for environment variables and configuration.
"""

from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator
import secrets


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    """
    
    # API Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Spark LMS"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "A learning management system inspired by brilliant.org and exercism.io"
    
    # Security
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # Database
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/spark_lms"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # Admin settings
    FIRST_ADMIN_EMAIL: str = "admin@spark-lms.com"
    FIRST_ADMIN_PASSWORD: str = "admin123"
    FIRST_ADMIN_USERNAME: str = "admin"
    
    # Course settings
    MIN_PASSING_SCORE: int = 70  # Minimum score to pass a chapter
    MAX_ATTEMPTS_PER_SEGMENT: int = 5
    XP_REDUCTION_PER_ATTEMPT: float = 0.1  # 10% reduction per attempt
    XP_REDUCTION_PER_HINT: float = 0.2  # 20% reduction per hint
    XP_REDUCTION_FOR_SOLUTION: float = 0.5  # 50% reduction for viewing solution
    
    # File upload settings
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS: List[str] = ["png", "jpg", "jpeg", "gif", "pdf", "md", "txt"]
    
    # Email settings (optional features)
    SMTP_TLS: bool = True
    SMTP_PORT: Optional[int] = None
    SMTP_HOST: Optional[str] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAILS_FROM_EMAIL: Optional[str] = None
    EMAILS_FROM_NAME: Optional[str] = None
    
    # Development settings
    DEBUG: bool = False
    TESTING: bool = False
    
    # Pyodide settings for code execution
    PYODIDE_CDN_URL: str = "https://cdn.jsdelivr.net/pyodide/v0.24.1/full/"
    CODE_EXECUTION_TIMEOUT: int = 10  # seconds
    
    # Redis settings (for future caching)
    REDIS_URL: Optional[str] = None
    
    # Analytics settings
    ENABLE_ANALYTICS: bool = True
    ANALYTICS_RETENTION_DAYS: int = 90
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )
    
    @property
    def emails_enabled(self) -> bool:
        """Check if email configuration is complete."""
        return bool(
            self.SMTP_HOST 
            and self.SMTP_PORT 
            and self.EMAILS_FROM_EMAIL
        )
    
    @property
    def database_url_asyncpg(self) -> str:
        """Get async database URL for asyncpg."""
        return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")


# Create global settings instance
settings = Settings()