"""
Database configuration and session management for Spark LMS.

Sets up SQLAlchemy engine, session factory, and base model.
"""

from typing import Generator, Optional
from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import logging

from .config import settings


# Configure logging
logger = logging.getLogger(__name__)


# SQLAlchemy metadata conventions for better constraint naming
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

metadata = MetaData(naming_convention=convention)


# Create engine based on environment
if settings.TESTING:
    # Use in-memory SQLite for testing
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    # Use PostgreSQL for development/production
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,  # Verify connections before using
        pool_size=10,        # Number of connections to maintain
        max_overflow=20,     # Maximum overflow connections
        echo=settings.DEBUG, # Log SQL statements if in debug mode
    )


# Session factory
SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine
)


# Base class for models
Base = declarative_base(metadata=metadata)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency to get database session.
    
    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(db: Session) -> None:
    """
    Initialize database with required data.
    
    This function should be called on first startup to create
    the default admin user and any other required initial data.
    
    Args:
        db: Database session
    """
    from app.models.user import User
    from app.core.security import get_password_hash
    
    # Check if admin user exists
    admin_user = db.query(User).filter(
        User.email == settings.FIRST_ADMIN_EMAIL
    ).first()
    
    if not admin_user:
        # Create admin user
        admin_user = User(
            email=settings.FIRST_ADMIN_EMAIL,
            username=settings.FIRST_ADMIN_USERNAME,
            hashed_password=get_password_hash(settings.FIRST_ADMIN_PASSWORD),
            is_active=True,
            is_admin=True,
            is_verified=True
        )
        db.add(admin_user)
        db.commit()
        logger.info(f"Admin user created: {settings.FIRST_ADMIN_EMAIL}")
    
    # Add any other initial data here
    # For example: default courses, sample content, etc.


def check_database_connection() -> bool:
    """
    Check if database is accessible.
    
    Returns:
        bool: True if database is accessible, False otherwise
    """
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


class DatabaseManager:
    """
    Database manager for handling database operations.
    """
    
    @staticmethod
    def create_all_tables():
        """Create all database tables."""
        Base.metadata.create_all(bind=engine)
        logger.info("All database tables created successfully")
    
    @staticmethod
    def drop_all_tables():
        """Drop all database tables. USE WITH CAUTION!"""
        Base.metadata.drop_all(bind=engine)
        logger.warning("All database tables dropped")
    
    @staticmethod
    def reset_database():
        """Reset database by dropping and recreating all tables."""
        DatabaseManager.drop_all_tables()
        DatabaseManager.create_all_tables()
        
        # Initialize with default data
        db = SessionLocal()
        try:
            init_db(db)
            logger.info("Database reset completed")
        finally:
            db.close()
    
    @staticmethod
    def backup_database(backup_path: str) -> bool:
        """
        Create a backup of the database.
        
        Args:
            backup_path: Path where backup should be saved
            
        Returns:
            bool: True if backup successful, False otherwise
        """
        # This is a placeholder - implement based on your database type
        # For PostgreSQL, you might use pg_dump
        # For SQLite, you might copy the database file
        logger.warning("Database backup not implemented")
        return False
    
    @staticmethod
    def get_table_stats() -> dict:
        """
        Get statistics about database tables.
        
        Returns:
            dict: Statistics about each table
        """
        stats = {}
        db = SessionLocal()
        try:
            # Import models to ensure they're registered
            from app.models import User, Course, Chapter, Segment, UserProgress
            
            models = [User, Course, Chapter, Segment, UserProgress]
            
            for model in models:
                count = db.query(model).count()
                stats[model.__tablename__] = {
                    "count": count,
                    "model": model.__name__
                }
            
            return stats
        finally:
            db.close()


# Async support (for future use)
try:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    
    # Async engine
    async_engine = create_async_engine(
        settings.database_url_asyncpg,
        echo=settings.DEBUG,
        future=True
    )
    
    # Async session factory
    AsyncSessionLocal = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    async def get_async_db() -> AsyncSession:
        """Get async database session."""
        async with AsyncSessionLocal() as session:
            yield session
            
except ImportError:
    # Async support not available
    async_engine = None
    AsyncSessionLocal = None
    get_async_db = None
    logger.info("Async database support not available")