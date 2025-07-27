"""
Authentication router for Spark LMS.

Handles user registration, login, logout, password reset,
and email verification endpoints.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.database import get_db
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    verify_token,
    create_email_verification_token,
    create_password_reset_token,
    verify_email_token,
    verify_password_reset_token,
    check_password_strength
)
from app.core.config import settings
from app.models.user import User
from app.models.admin import AdminLog
from app.schemas.auth import (
    UserRegister,
    UserLogin,
    Token,
    TokenRefresh,
    PasswordReset,
    PasswordResetRequest,
    EmailVerification,
    PasswordChange,
    UserResponse
)


router = APIRouter()

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


# Dependencies
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user from JWT token.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = verify_token(token)
    if payload is None:
        raise credentials_exception
    
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get current active user.
    """
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def get_current_verified_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """
    Get current verified user.
    """
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email to continue."
        )
    return current_user


# Endpoints
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Register a new user.
    """
    # Check if registration is enabled
    system_settings = db.query(SystemSettings).filter(
        SystemSettings.key == "enable_registration"
    ).first()
    if system_settings and not system_settings.get_typed_value():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User registration is currently disabled"
        )
    
    # Check if user already exists
    existing_user = db.query(User).filter(
        or_(
            User.email == user_data.email,
            User.username == user_data.username
        )
    ).first()
    
    if existing_user:
        if existing_user.email == user_data.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
    
    # Check password strength
    password_check = check_password_strength(user_data.password)
    if not password_check["valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Password does not meet requirements",
                "issues": password_check["issues"]
            }
        )
    
    # Create new user
    new_user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        is_active=True,
        is_verified=False,
        preferred_language=user_data.preferred_language or "en",
        timezone=user_data.timezone or "UTC"
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Send verification email (in background)
    if settings.emails_enabled:
        verification_token = create_email_verification_token(new_user.email)
        # Add email sending task to background
        # background_tasks.add_task(send_verification_email, new_user.email, verification_token)
    
    # Log registration
    admin_log = AdminLog.log_action(
        user_id=new_user.id,
        action=AdminAction.CREATE,
        entity_type="user",
        entity_id=new_user.id,
        details={"action": "user_registration"},
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    db.commit()
    
    return new_user


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    OAuth2 compatible login endpoint.
    """
    # Find user by email or username
    user = db.query(User).filter(
        or_(
            User.email == form_data.username,
            User.username == form_data.username
        )
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(form_data.password, user.hashed_password):
        # Log failed login attempt
        admin_log = AdminLog.log_action(
            user_id=user.id,
            action=AdminAction.LOGIN,
            entity_type="user",
            entity_id=user.id,
            details={"action": "failed_login_attempt"},
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent"),
            success=False,
            error_message="Invalid password"
        )
        db.add(admin_log)
        db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated"
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.username,
        expires_delta=access_token_expires,
        additional_claims={
            "user_id": user.id,
            "email": user.email,
            "is_admin": user.is_admin,
            "is_verified": user.is_verified
        }
    )
    
    # Update last login
    user.last_login_at = datetime.utcnow()
    user.update_streak(datetime.utcnow())
    
    # Log successful login
    admin_log = AdminLog.log_action(
        user_id=user.id,
        action=AdminAction.LOGIN,
        entity_type="user",
        entity_id=user.id,
        details={"action": "successful_login"},
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    db.commit()
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user.to_dict()
    }


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Logout endpoint (mainly for logging purposes).
    """
    # Log logout
    admin_log = AdminLog.log_action(
        user_id=current_user.id,
        action=AdminAction.LOGOUT,
        entity_type="user",
        entity_id=current_user.id,
        details={"action": "user_logout"},
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    db.add(admin_log)
    db.commit()
    
    return {"message": "Successfully logged out"}


@router.post("/refresh", response_model=Token)
async def refresh_token(
    token_data: TokenRefresh,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Refresh access token using existing valid token.
    """
    payload = verify_token(token_data.refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    username: str = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user"
        )
    
    # Create new access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.username,
        expires_delta=access_token_expires,
        additional_claims={
            "user_id": user.id,
            "email": user.email,
            "is_admin": user.is_admin,
            "is_verified": user.is_verified
        }
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user.to_dict()
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get current user information.
    """
    return current_user


@router.post("/verify-email")
async def verify_email(
    verification: EmailVerification,
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Verify user email with verification token.
    """
    email = verify_email_token(verification.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token"
        )
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if user.is_verified:
        return {"message": "Email already verified"}
    
    user.is_verified = True
    user.email_verified_at = datetime.utcnow()
    db.commit()
    
    return {"message": "Email verified successfully"}


@router.post("/request-password-reset")
async def request_password_reset(
    request_data: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Request password reset token.
    """
    user = db.query(User).filter(User.email == request_data.email).first()
    
    # Always return success to prevent email enumeration
    message = "If the email exists, a password reset link has been sent"
    
    if user and user.is_active:
        # Generate reset token
        reset_token = create_password_reset_token(user.email)
        
        # Store token and timestamp
        user.password_reset_token = reset_token
        user.password_reset_at = datetime.utcnow()
        db.commit()
        
        # Send reset email (in background)
        if settings.emails_enabled:
            # background_tasks.add_task(send_password_reset_email, user.email, reset_token)
            pass
    
    return {"message": message}


@router.post("/reset-password")
async def reset_password(
    reset_data: PasswordReset,
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Reset password using reset token.
    """
    email = verify_password_reset_token(reset_data.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check if token matches stored token
    if user.password_reset_token != reset_data.token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token"
        )
    
    # Check password strength
    password_check = check_password_strength(reset_data.new_password)
    if not password_check["valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Password does not meet requirements",
                "issues": password_check["issues"]
            }
        )
    
    # Update password
    user.hashed_password = get_password_hash(reset_data.new_password)
    user.password_reset_token = None
    user.password_reset_at = None
    db.commit()
    
    return {"message": "Password reset successfully"}


@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Change password for authenticated user.
    """
    # Verify current password
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Check password strength
    password_check = check_password_strength(password_data.new_password)
    if not password_check["valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Password does not meet requirements",
                "issues": password_check["issues"]
            }
        )
    
    # Update password
    current_user.hashed_password = get_password_hash(password_data.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}


# Import required schemas and models at the end to avoid circular imports
from app.models.admin import AdminAction, SystemSettings
from app.schemas import auth as schemas