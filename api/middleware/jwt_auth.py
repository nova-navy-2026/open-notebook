"""
JWT Authentication Middleware
Verifies JWT tokens and sets user context in requests.
Falls back to password authentication if JWT is not provided.
"""

import os
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
    
    # Paths that don't require JWT authentication
    # (login/status/refresh endpoints that must work without a valid token)
    EXEMPT_PATHS = [
        "/health",
        "/api/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/auth/status",
        "/api/auth/login",
        "/api/auth/oauth",
        "/api/auth/token/refresh",
        "/api/config",
        "/auth/status",
        "/auth/login",
        "/auth/oauth",
        "/auth/auth/token/refresh",
        # Vision note assets are served as static media; <img>/<video> tags
        # cannot send Authorization headers, so allow unauthenticated GETs.
        "/api/vision/note-asset/",
    ]
    
    def __init__(self, app, excluded_paths: Optional[list] = None):
        super().__init__(app)
        self.excluded_paths = excluded_paths or self.EXEMPT_PATHS
        self.password = get_secret_from_env("OPEN_NOTEBOOK_PASSWORD")
        # Read the anonymous-access flag once at startup (deploy-time config),
        # rather than per request. This keeps the hot path off os.environ.
        self.allow_anonymous = (
            (os.environ.get("ALLOW_ANONYMOUS", "") or "").lower()
            in ("1", "true", "yes")
        )
        # X-Navy-User impersonation (ACL bypass) — off by default; load-test only.
        from api.auth import _allow_navy_user_override

        self.allow_navy_override = _allow_navy_user_override()
    
    async def dispatch(self, request: Request, call_next):
        """
        Check authentication: JWT first, then password, then deny.
        """
        
        # Skip auth for exempt paths
        path = request.url.path
        if path == "/" or any(path.startswith(p) for p in self.excluded_paths):
            return await call_next(request)
        
        # Skip auth for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)
        
        auth_header = request.headers.get("Authorization")
        
        # Try JWT authentication first
        jwt_token = JWTManager.extract_from_header(auth_header)
        
        if jwt_token:
            jwt_verified = False
            try:
                # Verify JWT token
                payload = JWTManager.verify_token(jwt_token)

                # Set user context in request state
                request.state.user = {
                    "id": payload["user_id"],
                    "email": payload["email"],
                    "roles": payload.get("roles", ["user"]),
                    "authenticated_via": "jwt"
                }
                request.state.user_id = payload["user_id"]
                request.state.user_role = payload.get("roles", ["user"])[0]
                request.state.user_permissions = payload.get("roles", ["user"])

                # Navy-specific claims (populated at login from users.json).
                request.state.navy_user_id = payload.get("navy_user_id")
                # New template: list of departments + clearance_level, with
                # backward-compatible fallback to the legacy single-value keys.
                request.state.navy_departments = payload.get("departments") or (
                    [payload["department"]] if payload.get("department") else None
                )
                request.state.navy_clearance = payload.get(
                    "clearance_level", payload.get("clearence")
                )

                logger.debug(f"✅ JWT auth successful: {payload['email']}")
                jwt_verified = True

            except Exception as e:
                # JWT verification failed - try password auth as fallback
                logger.debug(f"JWT verification failed, trying password auth: {e}")

            if jwt_verified:
                # call_next is intentionally outside the try/except so that
                # exceptions from route handlers are NOT mistaken for JWT
                # verification failures and do not trigger a 401.
                return await call_next(request)
        
        # No valid JWT token - try password authentication
        if not self.password:
            # No password configured. Fail-closed by default: deny unauthenticated
            # requests so the API never silently grants anonymous access in
            # production. Set ALLOW_ANONYMOUS=1 to restore the old open-access
            # behaviour (development / single-user only).
            if self.allow_anonymous:
                logger.debug("ℹ️ ALLOW_ANONYMOUS set — allowing unauthenticated access")
                request.state.user = {"id": "anonymous", "email": "anonymous", "roles": ["viewer"]}
                request.state.user_id = "anonymous"
                request.state.user_role = "viewer"
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
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
                # Password auth successful.
                # Allow callers to supply a navy user identity via X-Navy-User
                # so the load test (and other tooling) can exercise the proper
                # OpenSearch ACL filter path without needing a full JWT token.
                # Only honoured AFTER the password is validated AND when
                # explicitly enabled (ALLOW_NAVY_USER_OVERRIDE=1) — it lets the
                # caller impersonate any navy clearance/department. Off in prod.
                request.state.user = {
                    "id": "password-auth",
                    "email": "password-auth@internal",
                    "roles": ["admin"],
                    "authenticated_via": "password"
                }
                request.state.user_id = "password-auth"
                request.state.user_role = "admin"
                request.state.user_permissions = ["admin"]
                if self.allow_navy_override:
                    navy_user_override = request.headers.get("X-Navy-User")
                    if navy_user_override:
                        request.state.navy_user_id = navy_user_override
                
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
