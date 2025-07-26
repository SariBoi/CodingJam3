"""
Security utilities for Spark LMS.

Handles password hashing, JWT token creation/verification, and authentication.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import ValidationError

from .config import settings


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.
    
    Args:
        plain_password: The plain text password to verify
        hashed_password: The hashed password to compare against
        
    Returns:
        bool: True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.
    
    Args:
        password: The plain text password to hash
        
    Returns:
        str: The hashed password
    """
    return pwd_context.hash(password)


def create_access_token(
    subject: str | Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
    additional_claims: Optional[Dict[str, Any]] = None
) -> str:
    """
    Create a JWT access token.
    
    Args:
        subject: The subject of the token (usually user ID or username)
        expires_delta: Optional custom expiration time
        additional_claims: Optional additional claims to include in the token
        
    Returns:
        str: The encoded JWT token
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {"exp": expire}
    
    # Handle subject
    if isinstance(subject, str):
        to_encode["sub"] = subject
    elif isinstance(subject, dict):
        to_encode.update(subject)
    
    # Add additional claims if provided
    if additional_claims:
        to_encode.update(additional_claims)
    
    # Add issued at time
    to_encode["iat"] = datetime.utcnow()
    
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.SECRET_KEY, 
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT token.
    
    Args:
        token: The JWT token to verify
        
    Returns:
        Optional[Dict[str, Any]]: The decoded token payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def create_email_verification_token(email: str) -> str:
    """
    Create a token for email verification.
    
    Args:
        email: The email address to verify
        
    Returns:
        str: The verification token
    """
    expires_delta = timedelta(hours=24)  # Email verification expires in 24 hours
    return create_access_token(
        subject=email,
        expires_delta=expires_delta,
        additional_claims={"type": "email_verification"}
    )


def create_password_reset_token(email: str) -> str:
    """
    Create a token for password reset.
    
    Args:
        email: The email address for password reset
        
    Returns:
        str: The password reset token
    """
    expires_delta = timedelta(hours=1)  # Password reset expires in 1 hour
    return create_access_token(
        subject=email,
        expires_delta=expires_delta,
        additional_claims={"type": "password_reset"}
    )


def verify_email_token(token: str) -> Optional[str]:
    """
    Verify an email verification token.
    
    Args:
        token: The token to verify
        
    Returns:
        Optional[str]: The email address if valid, None otherwise
    """
    payload = verify_token(token)
    if payload and payload.get("type") == "email_verification":
        return payload.get("sub")
    return None


def verify_password_reset_token(token: str) -> Optional[str]:
    """
    Verify a password reset token.
    
    Args:
        token: The token to verify
        
    Returns:
        Optional[str]: The email address if valid, None otherwise
    """
    payload = verify_token(token)
    if payload and payload.get("type") == "password_reset":
        return payload.get("sub")
    return None


def generate_temp_password() -> str:
    """
    Generate a temporary password for new users.
    
    Returns:
        str: A temporary password
    """
    import secrets
    import string
    
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for _ in range(12))
    return password


def check_password_strength(password: str) -> Dict[str, Any]:
    """
    Check password strength and return feedback.
    
    Args:
        password: The password to check
        
    Returns:
        Dict[str, Any]: Strength assessment and suggestions
    """
    issues = []
    strength = "weak"
    
    if len(password) < 8:
        issues.append("Password should be at least 8 characters long")
    
    if not any(c.isupper() for c in password):
        issues.append("Password should contain at least one uppercase letter")
    
    if not any(c.islower() for c in password):
        issues.append("Password should contain at least one lowercase letter")
    
    if not any(c.isdigit() for c in password):
        issues.append("Password should contain at least one number")
    
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        issues.append("Password should contain at least one special character")
    
    if len(issues) == 0:
        strength = "strong"
    elif len(issues) <= 2:
        strength = "medium"
    
    return {
        "strength": strength,
        "issues": issues,
        "valid": len(issues) == 0
    }