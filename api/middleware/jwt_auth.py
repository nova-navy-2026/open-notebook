"""
JWT Authentication Middleware
Verifies JWT tokens and sets user context in requests.
Falls back to password authentication if JWT is not provided.
"""

from typing import Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from loguru import logger

from open_notebook.security.jwt_manager import JWTManager
from open_notebook.utils.encryption import get_secret_from_env


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    JWT Authentication Middleware.
    Verifies JWT tokens in Authorization header and sets user context.
    Falls back to password authentication for backward compatibility.
    """
    
    # Paths that don't require authentication
    EXEMPT_PATHS = [
        "/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/auth/status",
        "/auth/login/local",
        "/auth/me",
        "/auth/verify",
        "/auth/oauth",
    ]
    
    def __init__(self, app, excluded_paths: Optional[list] = None):
        super().__init__(app)
        self.excluded_paths = excluded_paths or self.EXEMPT_PATHS
        self.password = get_secret_from_env("OPEN_NOTEBOOK_PASSWORD")
    
    async def dispatch(self, request: Request, call_next):
        """
        Check authentication: JWT first, then password, then deny.
        """
        
        # Skip auth for exempt paths
        if any(request.url.path.startswith(path) for path in self.excluded_paths):
            return await call_next(request)
        
        # Skip auth for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)
        
        auth_header = request.headers.get("Authorization")
        
        # Try JWT authentication first
        jwt_token = JWTManager.extract_from_header(auth_header)
        
        if jwt_token:
            try:
                # Verify JWT token
                payload = JWTManager.verify_token(jwt_token)
                
                # Set user context in request state
                request.state.user = {
                    "id": payload["user_id"],
                    "email": payload["email"],
                    "roles": payload.get("roles", ["viewer"]),
                    "authenticated_via": "jwt"
                }
                request.state.user_id = payload["user_id"]
                request.state.user_role = payload.get("roles", ["viewer"])[0]
                request.state.user_permissions = payload.get("roles", ["viewer"])
                
                logger.debug(f"✅ JWT auth successful: {payload['email']}")
                
                return await call_next(request)
            
            except Exception as e:
                logger.warning(f"❌ JWT verification failed: {e}")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or expired token"}
                )
        
        # Fall back to password authentication
        if not self.password:
            # No auth method configured, allow access
            logger.debug("ℹ️ No authentication configured, allowing access")
            request.state.user = {"id": "anonymous", "email": "anonymous", "roles": ["viewer"]}
            request.state.user_id = "anonymous"
            request.state.user_role = "viewer"
            return await call_next(request)
        
        # Check password auth header
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        try:
            # Extract bearer token (used as password)
            parts = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                raise ValueError("Invalid authorization header format")
            
            token = parts[1]
            
            # Verify password
            if token == self.password:
                # Password auth successful
                request.state.user = {
                    "id": "password-auth",
                    "email": "password-auth@internal",
                    "roles": ["admin"],
                    "authenticated_via": "password"
                }
                request.state.user_id = "password-auth"
                request.state.user_role = "admin"
                request.state.user_permissions = ["admin"]
                
                logger.debug("✅ Password auth successful")
                
                return await call_next(request)
            else:
                logger.warning("❌ Invalid password")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid credentials"},
                )
        
        except Exception as e:
            logger.error(f"❌ Auth error: {e}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication failed"},
            )
