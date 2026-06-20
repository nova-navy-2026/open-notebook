"""
Authentication router: Azure AD (OAuth2) + Local login with bcrypt.
Supports Azure AD and local email/password authentication backed by the
SurrealDB user table. No other OAuth providers are supported.
"""

from datetime import datetime
from typing import Optional
import os
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from loguru import logger

from open_notebook.domain.user import User
from open_notebook.security.jwt_manager import JWTManager
from open_notebook.utils.encryption import get_secret_from_env
from open_notebook.access_control import get_user_by_email as navy_get_user_by_email


def _navy_claims_for_email(email: Optional[str]) -> dict:
    """Return navy-specific JWT claims for the given email, or {}."""
    if not email:
        return {}
    match = navy_get_user_by_email(email)
    if not match:
        return {}
    navy_id, entry = match
    claims: dict = {"navy_user_id": navy_id}

    # Departments: prefer the new list-valued ``departments`` key, fall back
    # to the legacy single-valued ``department`` key.
    departments = entry.get("departments")
    if departments is None and entry.get("department") is not None:
        departments = [entry.get("department")]
    if departments is not None:
        claims["departments"] = departments

    # Clearance: prefer the new ``clearance_level`` key, fall back to the
    # legacy ``clearence`` key.
    clearance = entry.get("clearance_level")
    if clearance is None:
        clearance = entry.get("clearence")
    if clearance is not None:
        claims["clearance_level"] = clearance

    return claims

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Local login request (email + password)"""
    email: str
    password: Optional[str] = None


class TokenResponse(BaseModel):
    """Token response after successful login"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


@router.get("/status")
async def get_auth_status():
    """
    Check if authentication is enabled.
    Returns auth mode and available login methods.
    """
    has_password = bool(get_secret_from_env("OPEN_NOTEBOOK_PASSWORD"))
    has_admin = bool(os.getenv("ADMIN_PASSWORD"))
    has_azure = bool(os.getenv("AZURE_CLIENT_ID"))
    # Only Azure AD and manual (local) login are supported.
    oauth_enabled = has_azure

    # Auth is enabled if ANY authentication method is configured
    auth_enabled = has_password or has_admin or oauth_enabled

    return {
        "auth_enabled": auth_enabled,
        "oauth_enabled": oauth_enabled,
        "has_azure": has_azure,
        "local_login_available": has_password or has_admin,
        "message": "Azure AD and local login available"
    }


@router.post("/login/local")
async def login_local(request: LoginRequest):
    """
    Local email/password login.

    Validates the supplied email and password against the user table
    in SurrealDB (passwords are bcrypt-hashed).

    If no users exist yet, falls back to the env-var admin account
    (ADMIN_EMAIL / ADMIN_PASSWORD) so the first admin can bootstrap
    the system and create proper DB users.
    """

    email = request.email
    provided_password = request.password or ""

    if not email or not provided_password:
        raise HTTPException(status_code=401, detail="Email and password are required")

    try:
        # --- 1. Try database user lookup ---
        user = await User.get_by_email(email)

        if user and user.password_hash and user.is_active:
            if user.verify_password(provided_password):
                await user.update_last_login()

                user_data = user.to_safe_dict()

                # The env-var admin must always carry the admin role in the JWT
                # even if the SurrealDB record was created with a lower role.
                _admin_email = os.getenv("ADMIN_EMAIL")
                if email.lower() == _admin_email.lower():
                    user_data["roles"] = ["admin"]

                navy_claims = _navy_claims_for_email(user_data.get("email"))
                if navy_claims:
                    user_data.update(navy_claims)

                token = JWTManager.create_token(
                    user_id=user_data["id"],
                    email=user_data["email"],
                    roles=user_data["roles"],
                    extra_claims=navy_claims or None,
                )

                logger.info(f"✅ DB user login successful: {email}")

                return TokenResponse(
                    access_token=token,
                    expires_in=JWTManager.EXPIRY_SECONDS,
                    user=user_data,
                )

        # --- 2. Env-var bootstrap fallback (first-run only) ---
        admin_email = os.getenv("ADMIN_EMAIL", "admin@open-notebook.local")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin")

        if (
            email.lower() == admin_email.lower()
            and provided_password == admin_password
        ):
            user_data = {
                "id": "anonymous",
                "email": email,
                "name": "Administrator",
                "roles": ["admin"],
                "provider": "local",
                "is_active": True,
                "created": None,
                "updated": None,
                "last_login": None,
            }
            navy_claims = _navy_claims_for_email(email)
            if navy_claims:
                user_data.update(navy_claims)

            token = JWTManager.create_token(
                user_id=user_data["id"],
                email=user_data["email"],
                roles=user_data["roles"],
                extra_claims=navy_claims or None,
            )

            logger.info(f"✅ Env-var admin login (bootstrap): {email}")

            return TokenResponse(
                access_token=token,
                expires_in=JWTManager.EXPIRY_SECONDS,
                user=user_data,
            )

        # --- 3. No match ---
        logger.warning(f"❌ Failed login attempt for {email}")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")


@router.post("/logout")
async def logout(request: Request, response: Response):
    """
    Logout user and clear session.
    Removes authentication cookies.
    
    Example:
    ```
    curl -X POST http://localhost:5055/auth/logout \\
      -H "Authorization: Bearer YOUR_JWT_TOKEN"
    ```
    """
    try:
        user_id = getattr(request.state, 'user_id', 'unknown')
        
        # Clear auth cookies
        response.delete_cookie("access_token")
        response.delete_cookie("refresh_token")
        
        logger.info(f"✅ User logged out: {user_id}")
        
        return {"status": "logged_out", "message": "Successfully logged out"}
    except Exception as e:
        logger.error(f"❌ Logout error: {e}")
        raise HTTPException(status_code=500, detail="Logout failed")


@router.post("/token/refresh")
async def refresh_token(request: Request):
    """
    Refresh an expiring or expired JWT token.
    Returns a new token with same user data and roles.
    
    Requires valid token in Authorization header.
    
    Example:
    ```
    curl -X POST http://localhost:5055/auth/token/refresh \\
      -H "Authorization: Bearer YOUR_JWT_TOKEN"
    ```
    """
    
    try:
        # Extract JWT from Authorization header
        auth_header = request.headers.get("Authorization")
        token = JWTManager.extract_from_header(auth_header)
        
        if not token:
            raise HTTPException(status_code=401, detail="No token provided")
        
        # Refresh: decode expired token and issue new one
        result = JWTManager.refresh_token(token)
        new_token = result["token"]
        payload = result["payload"]
        
        logger.info(f"✅ Token refreshed for user {payload['email']}")
        
        return TokenResponse(
            access_token=new_token,
            expires_in=JWTManager.EXPIRY_SECONDS,
            user={
                "id": payload["user_id"],
                "email": payload["email"],
                "roles": payload.get("roles", ["viewer"])
            }
        )
    except Exception as e:
        logger.error(f"❌ Token refresh error: {e}")
        raise HTTPException(status_code=401, detail="Token refresh failed")


@router.get("/me")
async def get_current_user(request: Request):
    """
    Get current authenticated user information.
    
    Requires valid JWT in Authorization header.
    
    Example:
    ```
    curl -X GET http://localhost:5055/auth/me \\
      -H "Authorization: Bearer YOUR_JWT_TOKEN"
    ```
    """
    
    try:
        # First try to get user from request.state (set by middleware)
        user = getattr(request.state, 'user', None)
        if user and user.get("id") != "anonymous":
            _admin_email = os.getenv("ADMIN_EMAIL", "admin@open-notebook.local")
            if (user.get("email") or "").lower() == _admin_email.lower():
                user = {**user, "roles": ["admin"]}
            logger.debug(f"✅ User from middleware: {user}")
            return user
        
        # If not in state, extract and verify JWT directly
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Missing authorization header")
        
        token = JWTManager.extract_from_header(auth_header)
        if not token:
            raise HTTPException(status_code=401, detail="Invalid authorization header format")
        
        # Verify the token
        payload = JWTManager.verify_token(token)

        # Try to fetch full user profile from DB
        db_user = await User.get_by_email(payload["email"])
        if db_user:
            user_data = db_user.to_safe_dict()
            user_data["authenticated_via"] = "jwt"
        else:
            user_data = {
                "id": payload["user_id"],
                "email": payload["email"],
                "name": payload.get("name"),
                "roles": payload.get("roles", ["viewer"]),
                "authenticated_via": "jwt",
            }

        # Force admin role for the configured ADMIN_EMAIL — the DB-stored
        # roles may say "user" but the admin email is always admin.
        _admin_email = os.getenv("ADMIN_EMAIL", "admin@open-notebook.local")
        if payload.get("email", "").lower() == _admin_email.lower():
            user_data["roles"] = ["admin"]

        logger.info(f"✅ /me endpoint: User authenticated: {payload['email']} roles={user_data.get('roles')}")
        return user_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get user error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


@router.post("/verify")
async def verify_token_endpoint(request: Request):
    """
    Verify a JWT token without making an authenticated request.
    
    Extracts token from Authorization header: "Bearer <token>"
    
    Returns:
    - valid: true/false
    - user_id: user identifier
    - email: user email
    - roles: list of roles
    - exp: token expiration timestamp
    
    Example:
    ```
    curl -X POST http://localhost:5055/api/auth/verify \\
      -H "Authorization: Bearer YOUR_JWT_TOKEN" \\
      -H "Content-Type: application/json"
    ```
    """
    
    try:
        # Extract JWT from Authorization header
        auth_header = request.headers.get("Authorization")
        token = JWTManager.extract_from_header(auth_header)
        
        if not token:
            raise HTTPException(status_code=401, detail="No token provided")
        
        payload = JWTManager.verify_token(token)
        
        logger.info(f"✅ Token verified for {payload['email']}")
        
        return {
            "valid": True,
            "user_id": payload["user_id"],
            "email": payload["email"],
            "roles": payload.get("roles", ["viewer"]),
            "exp": payload["exp"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"❌ Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ============================================================
# OAuth Provider Endpoints
# ============================================================

@router.get("/oauth/providers")
async def list_oauth_providers():
    """
    List available OAuth providers with their configuration status.
    
    Example:
    ```
    curl -X GET http://localhost:5055/auth/oauth/providers
    ```
    """
    
    providers = {
        "azure": {
            "enabled": bool(os.getenv("AZURE_CLIENT_ID")),
            "name": "Microsoft Azure AD",
            "docs": "https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app"
        }
    }
    
    return {
        "providers": providers,
        "local_login": True,
        "message": "Setup OAuth providers by setting environment variables"
    }


@router.post("/oauth/azure/init")
async def azure_oauth_init():
    """
    Initialize Azure OAuth login flow.
    Returns authorization URL to redirect user to.
    
    Required environment variables:
    - AZURE_CLIENT_ID
    - AZURE_CLIENT_SECRET
    - AZURE_AUTHORITY
    - AZURE_REDIRECT_URI
    
    Example:
    ```
    curl -X POST http://localhost:5055/auth/oauth/azure/init
    ```
    """
    
    azure_client_id = os.getenv("AZURE_CLIENT_ID")
    
    if not azure_client_id:
        raise HTTPException(
            status_code=400,
            detail="Azure OAuth not configured. Set AZURE_CLIENT_ID environment variable."
        )
    
    azure_authority = os.getenv(
        "AZURE_AUTHORITY",
        "https://login.microsoftonline.com/common"
    )
    azure_redirect_uri = os.getenv(
        "AZURE_REDIRECT_URI",
        "http://localhost:5055/auth/oauth/azure/callback"
    )
    
    # Generate CSRF state parameter
    state = secrets.token_urlsafe(32)
    
    # Build authorization URL
    auth_url = (
        f"{azure_authority}/oauth2/v2.0/authorize?"
        f"client_id={azure_client_id}&"
        f"redirect_uri={azure_redirect_uri}&"
        f"response_type=code&"
        f"scope=openid%20profile%20email&"
        f"state={state}"
    )
    
    logger.info("✅ Azure OAuth initialization requested")
    
    return {
        "provider": "azure",
        "auth_url": auth_url,
        "state": state,
        "message": "Redirect user to auth_url to log in with Azure"
    }


@router.get("/oauth/azure/callback")
async def azure_oauth_callback(
    code: str = None,
    state: str = None,
    error: str = None
):
    """
    Handle Azure OAuth callback (redirect from Azure AD).
    Exchanges authorization code for user token and creates JWT.
    
    TODO: Implement token exchange with Azure token endpoint
    """
    
    if error:
        logger.error(f"❌ Azure OAuth error: {error}")
        raise HTTPException(
            status_code=400,
            detail=f"OAuth error: {error}"
        )
    
    if not code:
        raise HTTPException(
            status_code=400,
            detail="No authorization code received from Azure"
        )
    
    try:
        # TODO: Exchange code for token
        # 1. Call Azure token endpoint with code
        # 2. Parse response to get access token
        # 3. Call Azure /me endpoint with access token
        # 4. Create local user and JWT
        # 5. Redirect to frontend with JWT
        
        logger.warning("⚠️ Azure OAuth token exchange not yet implemented")
        
        return {
            "status": "pending",
            "message": "Azure OAuth token exchange not yet implemented",
            "help": "For development, use: POST /auth/login/local with admin account",
            "example_credentials": {
                "email": "admin@open-notebook.local",
                "password": "admin (from ADMIN_PASSWORD env var)"
            }
        }
    except Exception as e:
        logger.error(f"❌ Azure OAuth callback error: {e}")
        raise HTTPException(status_code=500, detail="OAuth callback failed")


