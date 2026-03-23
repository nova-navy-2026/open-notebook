"""
JWT Token Manager for OAuth and local authentication.
Handles token creation, verification, and refresh.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import os
import jwt
from loguru import logger


class JWTManager:
    """Manages JWT token creation and verification"""
    
    SECRET = os.getenv("JWT_SECRET", "change-me-in-production-with-secret-key")
    ALGORITHM = "HS256"
    EXPIRY_SECONDS = int(os.getenv("JWT_EXPIRY_SECONDS", "3600"))
    
    @staticmethod
    def create_token(
        user_id: str,
        email: str,
        roles: list = None,
        expires_in: Optional[int] = None
    ) -> str:
        """Create a JWT token with user claims"""
        
        if not roles:
            roles = ["viewer"]
        
        expires_in = expires_in or JWTManager.EXPIRY_SECONDS
        
        now = datetime.utcnow()
        exp_time = now + timedelta(seconds=expires_in)
        
        payload = {
            "sub": email,  # Subject (unique identifier)
            "user_id": user_id,
            "email": email,
            "roles": roles,
            "exp": int(exp_time.timestamp()),  # Unix timestamp as integer
            "iat": int(now.timestamp()),       # Unix timestamp as integer
        }
        
        try:
            token = jwt.encode(
                payload,
                JWTManager.SECRET,
                algorithm=JWTManager.ALGORITHM
            )
            logger.info(f"JWT created for user {email}")
            return token
        except Exception as e:
            logger.error(f"Failed to create JWT: {e}")
            raise
    
    @staticmethod
    def verify_token(token: str) -> Dict[str, Any]:
        """Verify and decode a JWT token"""
        
        try:
            payload = jwt.decode(
                token,
                JWTManager.SECRET,
                algorithms=[JWTManager.ALGORITHM]
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            raise
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            raise
    
    @staticmethod
    def refresh_token(token: str) -> str:
        """Create a new token from an existing token"""
        
        try:
            payload = JWTManager.verify_token(token)
            
            # Create new token with same claims but new expiry
            return JWTManager.create_token(
                user_id=payload["user_id"],
                email=payload["email"],
                roles=payload.get("roles", ["viewer"])
            )
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            raise
    
    @staticmethod
    def extract_from_header(auth_header: Optional[str]) -> Optional[str]:
        """Extract JWT from Authorization header (Bearer scheme)"""
        
        if not auth_header:
            return None
        
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        
        return None
