"""
JWT Token Manager for OAuth and local authentication.
Handles token creation, verification, and refresh.
"""

from typing import Optional, Dict, Any
import os
import time
import jwt
from loguru import logger


class JWTManager:
    """Manages JWT token creation and verification"""
    
    SECRET = os.getenv("JWT_SECRET", "change-me-in-production-with-secret-key")
    ALGORITHM = "HS256"
    EXPIRY_SECONDS = int(os.getenv("JWT_EXPIRY_SECONDS", "3600"))
    # Absolute session lifetime: once a session is this old (counted from the
    # original login, not the last refresh), the token can no longer be
    # refreshed and the user must log in again. 0 disables the cap (default,
    # = current behaviour). Set e.g. 43200 (12h) in production so revoked /
    # offboarded accounts cannot keep refreshing access indefinitely.
    MAX_SESSION_SECONDS = int(os.getenv("JWT_MAX_SESSION_SECONDS", "0"))
    
    @staticmethod
    def create_token(
        user_id: str,
        email: str,
        roles: list = None,
        expires_in: Optional[int] = None,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a JWT token with user claims.

        ``extra_claims`` is merged into the payload (after the standard
        fields, so it cannot overwrite ``sub``/``user_id``/``email``/
        ``roles``/``exp``/``iat``). Use it for app-specific claims such
        as the navy user id / department / clearance.
        """
        
        if not roles:
            roles = ["user"]
        
        expires_in = expires_in or JWTManager.EXPIRY_SECONDS

        now_ts = int(time.time())
        exp_ts = now_ts + expires_in

        payload: Dict[str, Any] = {}
        if extra_claims:
            payload.update(
                {k: v for k, v in extra_claims.items() if v is not None}
            )
        payload.update({
            "sub": email,  # Subject (unique identifier)
            "user_id": user_id,
            "email": email,
            "roles": roles,
            "exp": exp_ts,
            "iat": now_ts,
        })
        # Original login time, preserved across refreshes (a non-standard claim,
        # so refresh_token carries it forward). Used to enforce an absolute
        # session lifetime independent of the per-token expiry.
        payload.setdefault("auth_time", now_ts)
        
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
    def refresh_token(token: str) -> Dict[str, Any]:
        """Create a new token from an existing (possibly expired) token.
        Returns dict with 'token' and 'payload' keys."""
        
        try:
            # Decode WITHOUT verifying expiration so expired tokens can be refreshed
            payload = jwt.decode(
                token,
                JWTManager.SECRET,
                algorithms=[JWTManager.ALGORITHM],
                options={"verify_exp": False}
            )

            # Enforce the absolute session lifetime: past the cap, refresh is
            # refused and the user must re-authenticate. Counts from the original
            # login (auth_time), falling back to iat for tokens minted before
            # this claim existed.
            max_age = JWTManager.MAX_SESSION_SECONDS
            if max_age > 0:
                started = payload.get("auth_time") or payload.get("iat")
                if started and (int(time.time()) - int(started)) > max_age:
                    logger.warning("Token refresh refused: session exceeded max lifetime")
                    raise jwt.InvalidTokenError(
                        "Session expired; please log in again"
                    )

            # Create new token with same claims but new expiry, including
            # any app-specific extra claims (e.g. navy_user_id).
            standard_keys = {"sub", "user_id", "email", "roles", "exp", "iat"}
            extra_claims = {
                k: v for k, v in payload.items() if k not in standard_keys
            }
            new_token = JWTManager.create_token(
                user_id=payload["user_id"],
                email=payload["email"],
                roles=payload.get("roles", ["user"]),
                extra_claims=extra_claims or None,
            )
            return {"token": new_token, "payload": payload}
        except jwt.InvalidTokenError as e:
            logger.error(f"Token refresh failed: {e}")
            raise
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
