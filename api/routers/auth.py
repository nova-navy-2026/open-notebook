"""
Authentication router: OAuth2 + Local Admin Account.
Supports Azure AD, Google, and local email-based authentication.
"""

from datetime import datetime
from typing import Optional
import os
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from loguru import logger

from open_notebook.security.jwt_manager import JWTManager
from open_notebook.utils.encryption import get_secret_from_env

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
    auth_enabled = bool(get_secret_from_env("OPEN_NOTEBOOK_PASSWORD"))
    oauth_enabled = os.getenv("OAUTH_ENABLED", "false").lower() == "true"

    return {
        "auth_enabled": auth_enabled,
        "oauth_enabled": oauth_enabled,
        "has_azure": bool(os.getenv("AZURE_CLIENT_ID")),
        "has_google": bool(os.getenv("GOOGLE_CLIENT_ID")),
        "local_login_available": True,  # Always available in dev
        "message": "Multiple authentication methods available"
    }


@router.post("/login/local")
async def login_local(request: LoginRequest):
    """
    Local email-based login for development and admin access.
    
    Default admin credentials:
    - Email: admin@open-notebook.local
    - Password: (from ADMIN_PASSWORD env var, default: 'admin')
    
    ⚠️ FOR DEVELOPMENT ONLY - Use OAuth for production
    
    Example:
    ```
    curl -X POST http://localhost:5055/auth/login/local \\
      -H "Content-Type: application/json" \\
      -d '{"email": "admin@open-notebook.local", "password": "admin"}'
    ```
    """
    
    email = request.email
    provided_password = request.password or ""
    
    # Get admin credentials from environment
    admin_email = os.getenv("ADMIN_EMAIL", "admin@open-notebook.local")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin")
    
    try:
        # Check if credentials match admin account
        if email.lower() == admin_email.lower() and provided_password == admin_password:
            # Admin login successful
            user_data = {
                "id": "admin-user-001",
                "email": email,
                "name": "Administrator",
                "roles": ["admin"],
                "provider": "local"
            }
            
            # Generate JWT token
            token = JWTManager.create_token(
                user_id=user_data["id"],
                email=user_data["email"],
                roles=user_data["roles"]
            )
            
            logger.info(f"✅ Local admin login successful: {email}")
            
            return TokenResponse(
                access_token=token,
                expires_in=JWTManager.EXPIRY_SECONDS,
                user=user_data
            )
        else:
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
        
        # Verify and create new token
        new_token = JWTManager.refresh_token(token)
        
        # Get original token claims
        payload = JWTManager.verify_token(token)
        
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
        
        user_data = {
            "id": payload["user_id"],
            "email": payload["email"],
            "roles": payload.get("roles", ["viewer"]),
            "authenticated_via": "jwt"
        }
        
        logger.info(f"✅ /me endpoint: User authenticated: {payload['email']}")
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
        },
        "google": {
            "enabled": bool(os.getenv("GOOGLE_CLIENT_ID")),
            "name": "Google OAuth",
            "docs": "https://developers.google.com/identity/protocols/oauth2"
        },
        "github": {
            "enabled": bool(os.getenv("GITHUB_CLIENT_ID")),
            "name": "GitHub OAuth",
            "docs": "https://docs.github.com/en/developers/apps"
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


@router.post("/oauth/google/init")
async def google_oauth_init():
    """
    Initialize Google OAuth login flow.
    Returns authorization URL for Google login.
    
    Required environment variables:
    - GOOGLE_CLIENT_ID
    - GOOGLE_REDIRECT_URI
    """
    
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    
    if not google_client_id:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID environment variable."
        )
    
    google_redirect_uri = os.getenv(
        "GOOGLE_REDIRECT_URI",
        "http://localhost:5055/auth/oauth/google/callback"
    )
    
    state = secrets.token_urlsafe(32)
    
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={google_client_id}&"
        f"redirect_uri={google_redirect_uri}&"
        f"response_type=code&"
        f"scope=openid%20profile%20email&"
        f"state={state}"
    )
    
    logger.info("✅ Google OAuth initialization requested")
    
    return {
        "provider": "google",
        "auth_url": auth_url,
        "state": state,
        "message": "Redirect user to auth_url to log in with Google"
    }


@router.get("/oauth/google/callback")
async def google_oauth_callback(
    code: str = None,
    state: str = None,
    error: str = None
):
    """
    Handle Google OAuth callback.
    
    TODO: Implement token exchange with Google token endpoint
    """
    
    if error:
        logger.error(f"❌ Google OAuth error: {error}")
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code received from Google")
    
    try:
        # TODO: Exchange code for token with Google
        
        logger.warning("⚠️ Google OAuth token exchange not yet implemented")
        
        return {
            "status": "pending",
            "message": "Google OAuth token exchange not yet implemented",
            "help": "For development, use: POST /auth/login/local with admin account"
        }
    except Exception as e:
        logger.error(f"❌ Google OAuth callback error: {e}")
        raise HTTPException(status_code=500, detail="OAuth callback failed")