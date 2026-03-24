"""
Role-Based Access Control (RBAC) middleware and decorators.
Enforces permissions based on user roles.
"""

from enum import Enum
from typing import List, Optional
from functools import wraps

from fastapi import HTTPException, Request, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger


class Role(Enum):
    """User roles"""
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    CUSTOM = "custom"


class Permission(Enum):
    """System permissions"""
    
    # Notebook permissions
    NOTEBOOK_CREATE = "notebook:create"
    NOTEBOOK_READ = "notebook:read"
    NOTEBOOK_UPDATE = "notebook:update"
    NOTEBOOK_DELETE = "notebook:delete"
    NOTEBOOK_SHARE = "notebook:share"
    
    # Source permissions
    SOURCE_CREATE = "source:create"
    SOURCE_READ = "source:read"
    SOURCE_UPDATE = "source:update"
    SOURCE_DELETE = "source:delete"
    
    # Admin permissions
    USER_MANAGE = "user:manage"
    CREDENTIAL_MANAGE = "credential:manage"
    AUDIT_VIEW = "audit:view"
    SETTINGS_MANAGE = "settings:manage"


# Default role permissions mapping
ROLE_PERMISSIONS = {
    Role.ADMIN: [
        # Admin has all permissions
        Permission.NOTEBOOK_CREATE,
        Permission.NOTEBOOK_READ,
        Permission.NOTEBOOK_UPDATE,
        Permission.NOTEBOOK_DELETE,
        Permission.NOTEBOOK_SHARE,
        Permission.SOURCE_CREATE,
        Permission.SOURCE_READ,
        Permission.SOURCE_UPDATE,
        Permission.SOURCE_DELETE,
        Permission.USER_MANAGE,
        Permission.CREDENTIAL_MANAGE,
        Permission.AUDIT_VIEW,
        Permission.SETTINGS_MANAGE,
    ],
    Role.EDITOR: [
        # Editor can create/update but not delete
        Permission.NOTEBOOK_CREATE,
        Permission.NOTEBOOK_READ,
        Permission.NOTEBOOK_UPDATE,
        Permission.NOTEBOOK_SHARE,
        Permission.SOURCE_CREATE,
        Permission.SOURCE_READ,
        Permission.SOURCE_UPDATE,
    ],
    Role.VIEWER: [
        # Viewer is read-only
        Permission.NOTEBOOK_READ,
        Permission.SOURCE_READ,
    ],
    Role.CUSTOM: [
        # Custom roles defined per user
    ]
}


# Route-level permission requirements
ROUTE_PERMISSIONS = {
    "POST:/notebooks": [Role.EDITOR, Role.ADMIN],
    "PUT:/notebooks/{notebook_id}": [Role.EDITOR, Role.ADMIN],
    "DELETE:/notebooks/{notebook_id}": [Role.ADMIN],
    "GET:/notebooks": [Role.VIEWER, Role.EDITOR, Role.ADMIN],
    
    "POST:/sources": [Role.EDITOR, Role.ADMIN],
    "DELETE:/sources/{source_id}": [Role.ADMIN],
    
    "GET:/admin/users": [Role.ADMIN],
    "POST:/admin/users": [Role.ADMIN],
    "DELETE:/admin/users/{user_id}": [Role.ADMIN],
    
    "GET:/audit/logs": [Role.ADMIN],
    "GET:/credentials": [Role.EDITOR, Role.ADMIN],
    "POST:/credentials": [Role.ADMIN],
}


class RBACMiddleware(BaseHTTPMiddleware):
    """
    Role-Based Access Control middleware.
    Enforces permissions based on user roles for each request.
    """
    
    # Paths that don't require authentication/authorization
    # (endpoints handle their own auth/authz)
    EXEMPT_PATHS = [
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    ]
    
    async def dispatch(self, request: Request, call_next):
        """
        Check user role against route permission requirements.
        Only enforces auth for routes with explicit ROUTE_PERMISSIONS entries.
        """
        path = request.url.path
        
        # Skip authorization for exempt paths
        if path == "/" or any(path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)
        
        # Skip CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)
        
        # Build route key for permission check
        route_key = f"{request.method}:{path}"
        required_roles = ROUTE_PERMISSIONS.get(route_key, [])
        
        # If route has no explicit permission requirements, allow through
        if not required_roles:
            return await call_next(request)
        
        # Route requires specific roles - check user authentication
        user = getattr(request.state, 'user', None)
        
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Handle user as dict (from JWT middleware) or object
        if isinstance(user, dict):
            user_roles = user.get('roles', ['viewer'])
            user_id = user.get('id', 'unknown')
        else:
            # Handle as object if needed
            user_roles = getattr(user, 'roles', ['viewer'])
            user_id = getattr(user, 'id', 'unknown')
        
        # Ensure roles is a list
        if isinstance(user_roles, str):
            user_roles = [user_roles]
        
        # Build route key for permission check
        method = request.method
        path = request.url.path
        route_key = f"{method}:{path}"
        
        # Check if route requires specific roles
        required_roles = ROUTE_PERMISSIONS.get(route_key, [])
        
        if required_roles:
            # Convert role strings to Role enums for comparison
            user_role_enums = [
                Role(role) if isinstance(role, str) else role 
                for role in user_roles
                if role
            ]
            
            if not any(role in required_roles for role in user_role_enums):
                logger.warning(
                    f"Access denied for user {user_id} with roles {user_roles} "
                    f"to {method} {path}. Required roles: {[r.value for r in required_roles]}"
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Insufficient permissions. Required role: {[r.value for r in required_roles]}"
                )
        
        return await call_next(request)


def get_role_permissions(role: Role) -> List[Permission]:
    """Get all permissions for a given role"""
    return ROLE_PERMISSIONS.get(role, [])


def permission_required(*required_permissions: Permission):
    """
    Decorator to enforce specific permissions on an endpoint.
    
    Usage:
        @permission_required(Permission.NOTEBOOK_DELETE, Permission.NOTEBOOK_UPDATE)
        async def delete_notebook(notebook_id: str):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            if not request:
                raise HTTPException(status_code=400, detail="Request object required")
            
            user_permissions = getattr(request.state, 'user_permissions', [])
            
            # Check if user has any of the required permissions
            if not any(perm in user_permissions for perm in required_permissions):
                user_id = getattr(request.state, 'user_id', 'unknown')
                logger.warning(
                    f"Permission denied for user {user_id}. "
                    f"Required: {[p.value for p in required_permissions]}"
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied. Required: {[p.value for p in required_permissions]}"
                )
            
            return await func(*args, request=request, **kwargs)
        
        return wrapper
    return decorator


def role_required(*required_roles: Role):
    """
    Decorator to enforce specific roles on an endpoint.
    
    Usage:
        @role_required(Role.ADMIN)
        async def manage_users():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            if not request:
                raise HTTPException(status_code=400, detail="Request object required")
            
            user_role = getattr(request.state, 'user_role', None)
            
            if user_role not in required_roles:
                user_id = getattr(request.state, 'user_id', 'unknown')
                logger.warning(
                    f"Role denied for user {user_id}. "
                    f"Role: {user_role}, Required: {[r.value for r in required_roles]}"
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Role denied. Required: {[r.value for r in required_roles]}"
                )
            
            return await func(*args, request=request, **kwargs)
        
        return wrapper
    return decorator


# Dependency for getting current user
async def get_current_user(request: Request):
    """FastAPI dependency to get current user"""
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# Dependency for checking admin role
async def get_admin_user(request: Request):
    """FastAPI dependency to ensure user is admin"""
    user = getattr(request.state, 'user', None)
    user_role = getattr(request.state, 'user_role', None)
    if user_role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# API Router for role management (admin only)
from fastapi import APIRouter

rbac_router = APIRouter(prefix="/api/admin/roles", tags=["rbac"], dependencies=[Depends(get_admin_user)])


@rbac_router.get("/")
async def list_roles():
    """
    List all available roles and their permissions.
    Returns default system roles (admin, editor, viewer).
    Custom roles would be loaded from database in production.
    
    Example:
    ```
    curl -X GET http://localhost:5055/api/admin/roles/ \
      -H "Authorization: Bearer ADMIN_TOKEN"
    ```
    """
    roles_list = []
    for role, perms in ROLE_PERMISSIONS.items():
        roles_list.append({
            "id": role.value,
            "name": role.name,
            "is_system_role": True,
            "permissions": [p.value for p in perms],
            "description": f"System role: {role.name}"
        })
    
    logger.info(f"✅ Listed {len(roles_list)} roles")
    
    return {
        "roles": roles_list,
        "total": len(roles_list),
        "message": "System roles (custom roles in database)"
    }


@rbac_router.post("/custom")
async def create_custom_role(name: str, permissions: List[str]):
    """
    Create a custom role with specific permissions.
    TODO: Implement database storage
    """
    return {
        "status": "pending",
        "message": "Custom role creation not yet implemented"
    }


@rbac_router.put("/custom/{role_id}")
async def update_custom_role(role_id: str, permissions: List[str]):
    """
    Update a custom role's permissions.
    TODO: Implement database update
    """
    return {
        "status": "pending",
        "message": "Custom role update not yet implemented"
    }


@rbac_router.get("/user/{user_id}")
async def get_user_permissions(user_id: str, request: Request):
    """
    Get a user's current role and permissions.
    
    Returns:
    - user_id: The user identifier
    - roles: List of assigned roles
    - permissions: List of all permissions granted by those roles
    - is_admin: Whether user is admin
    
    Example:
    ```
    curl -X GET http://localhost:5055/api/admin/roles/user/user-123 \
      -H "Authorization: Bearer ADMIN_TOKEN"
    ```
    """
    try:
        # Get requesting admin user
        admin = getattr(request.state, 'user', None)
        if not admin:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        admin_roles = admin.get('roles', [])
        if 'admin' not in admin_roles:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # In production, load user from database
        # For now, return a template response
        
        # Assume user has viewer role if not specified
        user_roles = ["viewer"]  # Would be loaded from database in production
        user_permissions = []
        
        for role_name in user_roles:
            try:
                role = Role[role_name.upper()]
                user_permissions.extend([p.value for p in ROLE_PERMISSIONS.get(role, [])])
            except KeyError:
                pass
        
        # Remove duplicates
        user_permissions = list(set(user_permissions))
        
        logger.info(f"✅ Retrieved permissions for user {user_id}: {len(user_permissions)} permissions")
        
        return {
            "user_id": user_id,
            "roles": user_roles,
            "permissions": user_permissions,
            "is_admin": "admin" in user_roles,
            "message": "Use UserRepository to load actual user from database"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting user permissions: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user permissions")
