from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from open_notebook.utils.encryption import get_secret_from_env


def get_current_user_id(request: Request) -> str:
    """FastAPI dependency that extracts the authenticated user_id from request state.

    The JWT middleware (or password-auth fallback) sets request.state.user_id
    on every authenticated request. This dependency makes it easy to inject
    the current user into route handlers.

    Returns 'anonymous' when no auth middleware has run (e.g. tests).
    """
    return getattr(request.state, "user_id", "anonymous")


def get_current_navy_user_id(request: Request) -> Optional[str]:
    """FastAPI dependency that returns the navy directory user id (e.g. "m24409").

    Set by the JWT middleware from the ``navy_user_id`` claim, which is in
    turn populated at login time from the navy users.json directory. Returns
    None when the logged-in user has no matching navy entry (e.g. the
    bootstrap admin), in which case access-control filtering will fail-closed
    downstream.
    """
    return getattr(request.state, "navy_user_id", None)


def is_admin(request: Request) -> bool:
    """Return True when the authenticated user carries the ``admin`` role."""
    roles = getattr(request.state, "user_permissions", []) or []
    return "admin" in roles


def assert_owns(resource_owner: Optional[str], request: Request) -> None:
    """Fail-closed per-user ownership check for direct-by-ID access.

    Raises 404 (not 403, to avoid leaking that the resource exists) unless the
    caller owns the resource or is an admin. Resources with no owner
    (``owner is None``) are treated as private to admins — they are NOT public.
    Use this on every GET/PUT/DELETE-by-id and link endpoint so that list
    filtering (which already scopes by owner) cannot be bypassed via a known id.
    """
    if is_admin(request):
        return
    user_id = getattr(request.state, "user_id", "anonymous")
    if resource_owner is None or resource_owner != user_id:
        raise HTTPException(status_code=404, detail="Not found")


def get_navy_acl_user_id(request: Request) -> Optional[str]:
    """FastAPI dependency that returns the navy user id to use for ACL filtering.

    - Users with a navy entry → returns their ``navy_user_id``
      (ACL filter applied via ``build_opensearch_filter``).
    - Admins without a navy entry → returns ``"__admin__"`` so bootstrap
      administration can still inspect the corpus.
    - Regular users without a navy entry → returns ``None``, callers
      fail-closed (empty results).
    """
    roles = getattr(request.state, "user_permissions", []) or []
    navy_id = getattr(request.state, "navy_user_id", None)
    logger.debug(
        f"[navy-acl] resolving user_id: roles={roles!r} navy_user_id={navy_id!r}"
    )
    if navy_id:
        return navy_id
    if "admin" in roles:
        return "__admin__"
    return None


class PasswordAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to check password authentication for all API requests.
    Always active with default password if OPEN_NOTEBOOK_PASSWORD is not set.
    Supports Docker secrets via OPEN_NOTEBOOK_PASSWORD_FILE.
    """

    def __init__(self, app, excluded_paths: Optional[list] = None):
        super().__init__(app)
        self.password = get_secret_from_env("OPEN_NOTEBOOK_PASSWORD")
        self.excluded_paths = excluded_paths or [
            "/",
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    async def dispatch(self, request: Request, call_next):
        # Skip authentication if no password is set
        if not self.password:
            return await call_next(request)

        # Skip authentication for excluded paths (prefix matching)
        if any(request.url.path.startswith(path) for path in self.excluded_paths):
            return await call_next(request)

        # Skip authentication for CORS preflight requests (OPTIONS)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Check authorization header
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Expected format: "Bearer {password}"
        try:
            scheme, credentials = auth_header.split(" ", 1)
            if scheme.lower() != "bearer":
                raise ValueError("Invalid authentication scheme")
        except ValueError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authorization header format"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check password
        if credentials != self.password:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid password"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Password is correct, proceed with the request.
        # Allow callers to supply a navy user identity via X-Navy-User header.
        # This is only honoured AFTER the password has been validated above, so
        # it cannot be abused by unauthenticated clients.  JWT-authenticated
        # requests never reach this point (they bypass the middleware via the
        # JWTAuthMiddleware that runs first).
        navy_user_override = request.headers.get("X-Navy-User")
        if navy_user_override:
            request.state.navy_user_id = navy_user_override

        # Proceed with the request
        response = await call_next(request)
        return response


# Optional: HTTPBearer security scheme for OpenAPI documentation
security = HTTPBearer(auto_error=False)


def check_api_password(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> bool:
    """
    Utility function to check API password.
    Can be used as a dependency in individual routes if needed.
    Supports Docker secrets via OPEN_NOTEBOOK_PASSWORD_FILE.
    Returns True without checking credentials if OPEN_NOTEBOOK_PASSWORD is not configured.
    Raises 401 if credentials are missing or don't match the configured password.
    """
    password = get_secret_from_env("OPEN_NOTEBOOK_PASSWORD")

    # No password configured - skip authentication
    if not password:
        return True

    # No credentials provided
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check password
    if credentials.credentials != password:
        raise HTTPException(
            status_code=401,
            detail="Invalid password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
