"""
Audit logging service and middleware.
Tracks all significant actions for compliance and security.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum
from uuid import uuid4

from fastapi import HTTPException, APIRouter, Query, Depends, Request
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

# Database import - update path based on your setup
# from open_notebook.database.repositories.audit_log_repo import AuditLogRepository


class AuditAction(Enum):
    """Types of actions to audit"""
    
    # Authentication
    LOGIN = "login"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"
    MFA_ENABLED = "mfa_enabled"
    MFA_DISABLED = "mfa_disabled"
    
    # Notebook operations
    NOTEBOOK_CREATED = "notebook_created"
    NOTEBOOK_UPDATED = "notebook_updated"
    NOTEBOOK_DELETED = "notebook_deleted"
    NOTEBOOK_SHARED = "notebook_shared"
    NOTEBOOK_ACCESS_REVOKED = "notebook_access_revoked"
    
    # Source operations
    SOURCE_ADDED = "source_added"
    SOURCE_REMOVED = "source_removed"
    SOURCE_UPDATED = "source_updated"
    SOURCE_REPROCESSED = "source_reprocessed"
    EMBEDDING_REBUILT = "embedding_rebuilt"
    
    # Note operations
    NOTE_CREATED = "note_created"
    NOTE_UPDATED = "note_updated"
    NOTE_DELETED = "note_deleted"
    
    # Admin operations
    USER_CREATED = "user_created"
    USER_DELETED = "user_deleted"
    USER_ROLE_CHANGED = "user_role_changed"
    CREDENTIAL_ADDED = "credential_added"
    CREDENTIAL_DELETED = "credential_deleted"
    CREDENTIAL_TESTED = "credential_tested"
    SETTINGS_CHANGED = "settings_changed"
    BACKUP_CREATED = "backup_created"
    
    # Search & RAG
    SEARCH_EXECUTED = "search_executed"
    RAG_GENERATION = "rag_generation"
    CHAT_INTERACTION = "chat_interaction"


class AuditResourceType(Enum):
    """Types of resources to audit"""
    NOTEBOOK = "notebook"
    SOURCE = "source"
    NOTE = "note"
    USER = "user"
    CREDENTIAL = "credential"
    SETTING = "setting"
    SYSTEM = "system"


class AuditLog:
    """Audit log entry model"""
    
    def __init__(
        self,
        user_id: str,
        action: AuditAction,
        resource_type: AuditResourceType,
        resource_id: Optional[str] = None,
        resource_name: Optional[str] = None,
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.id = str(uuid4())
        self.timestamp = datetime.now(timezone.utc)
        self.user_id = user_id
        self.action = action.value
        self.resource_type = resource_type.value
        self.resource_id = resource_id
        self.resource_name = resource_name
        self.old_value = old_value
        self.new_value = new_value
        self.status = status
        self.error_message = error_message
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.duration_ms = duration_ms
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage"""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "status": self.status,
            "error_message": self.error_message,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class AuditService:
    """Service for audit logging operations. Persists to SurrealDB via AuditLogEntry."""

    def __init__(self):
        logger.info("AuditService initialized (SurrealDB-backed)")

    async def log_action(
        self,
        user_id: str,
        action: AuditAction,
        resource_type: AuditResourceType,
        resource_id: Optional[str] = None,
        resource_name: Optional[str] = None,
        old_value: Optional[Dict] = None,
        new_value: Optional[Dict] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_ms: Optional[float] = None,
        **kwargs
    ) -> AuditLog:
        """Log an action to the audit trail, persisting to SurrealDB."""

        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            old_value=old_value,
            new_value=new_value,
            status=status,
            error_message=error_message,
            ip_address=ip_address,
            user_agent=user_agent,
            duration_ms=duration_ms,
            metadata=kwargs,
        )

        # Persist to SurrealDB
        try:
            from open_notebook.domain.audit_log import AuditLogEntry

            await AuditLogEntry.create_entry(
                user_id=user_id,
                action=action.value,
                resource_type=resource_type.value,
                resource_id=resource_id,
                resource_name=resource_name,
                old_value=old_value,
                new_value=new_value,
                status=status,
                error_message=error_message,
                ip_address=ip_address,
                user_agent=user_agent,
                http_status=kwargs.get("http_status"),
                duration_ms=duration_ms,
                metadata=kwargs,
            )
        except Exception as e:
            # Don't let audit persistence failures break the app
            logger.warning(f"Failed to persist audit log to DB: {e}")

        logger.info(
            f"Audit: {action.value} by {user_id} on {resource_type.value}:{resource_id} - {status}"
        )

        return audit_log

    async def query_logs(
        self,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query audit logs from SurrealDB with filtering."""
        try:
            from open_notebook.domain.audit_log import AuditLogEntry

            return await AuditLogEntry.query(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        except Exception as e:
            logger.error(f"Failed to query audit logs from DB: {e}")
            return []

    async def search_logs(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search audit logs by action or resource name."""
        try:
            from open_notebook.domain.audit_log import AuditLogEntry

            results = await AuditLogEntry.query(action=query, limit=limit)
            if not results:
                results = await AuditLogEntry.query(resource_type=query, limit=limit)
            return results
        except Exception as e:
            logger.error(f"Failed to search audit logs: {e}")
            return []

    async def get_user_activity(self, user_id: str, days: int = 30) -> Dict[str, Any]:
        """Get user's activity summary from SurrealDB."""
        try:
            from open_notebook.domain.audit_log import AuditLogEntry

            return await AuditLogEntry.get_user_activity(user_id, days=days)
        except Exception as e:
            logger.error(f"Failed to get user activity from DB: {e}")
            return {
                "user_id": user_id,
                "period_days": days,
                "total_actions": 0,
                "success_count": 0,
                "failure_count": 0,
                "success_rate": 0,
                "actions_by_type": {},
                "first_action": None,
                "last_action": None,
            }


# Global audit service instance
audit_service = AuditService()


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to automatically log API requests.
    Tracks all POST, PUT, PATCH, DELETE operations.
    """
    
    AUDITED_METHODS = ["POST", "PUT", "PATCH", "DELETE"]
    
    # Routes to skip auditing
    EXCLUDED_PATHS = [
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/auth/verify",  # Verification endpoint, not an audit action
        "/auth/me",      # User profile check, not an audit action
        "/auth/status",  # Status check, not an audit action
    ]
    
    async def dispatch(self, request: Request, call_next):
        """Log API operations"""
        
        import time
        
        start_time = time.time()
        
        # Skip audit for excluded paths
        if any(request.url.path.startswith(path) for path in self.EXCLUDED_PATHS):
            return await call_next(request)
        
        # Only audit these HTTP methods
        if request.method not in self.AUDITED_METHODS:
            return await call_next(request)
        
        # Extract user info
        user_id = getattr(request.state, 'user_id', 'anonymous')
        user_agent = request.headers.get('user-agent', '')
        ip_address = request.client.host if request.client else None
        
        try:
            response = await call_next(request)
            duration = (time.time() - start_time) * 1000  # Convert to milliseconds
            
            # Parse action and resource from URL
            action, resource_type, resource_id = parse_audit_info(request)
            
            # Log successful action
            await audit_service.log_action(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                status="success" if response.status_code < 400 else "failure",
                ip_address=ip_address,
                user_agent=user_agent,
                duration_ms=duration,
                http_status=response.status_code,
            )
            
            return response
        
        except Exception as e:
            # Log failed action
            duration = (time.time() - start_time) * 1000
            action, resource_type, resource_id = parse_audit_info(request)
            
            await audit_service.log_action(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                status="failure",
                error_message=str(e),
                ip_address=ip_address,
                user_agent=user_agent,
                duration_ms=duration,
            )
            
            raise


def parse_audit_info(request: Request) -> tuple:
    """
    Parse HTTP request to extract audit information.
    Returns (action, resource_type, resource_id)
    """
    
    method = request.method
    path = request.url.path
    
    # Map endpoints to actions and resources
    # Example: POST /notebooks -> CREATE, NOTEBOOK
    # DELETE /notebooks/123 -> DELETE, NOTEBOOK, 123
    
    if "/notebooks" in path:
        resource_type = AuditResourceType.NOTEBOOK
        if method == "POST":
            action = AuditAction.NOTEBOOK_CREATED
        elif method == "PUT":
            action = AuditAction.NOTEBOOK_UPDATED
        elif method == "DELETE":
            action = AuditAction.NOTEBOOK_DELETED
        else:
            action = AuditAction.NOTEBOOK_UPDATED
    
    elif "/sources" in path:
        resource_type = AuditResourceType.SOURCE
        if method == "POST":
            action = AuditAction.SOURCE_ADDED
        elif method == "PUT":
            action = AuditAction.SOURCE_UPDATED
        elif method == "DELETE":
            action = AuditAction.SOURCE_REMOVED
        else:
            action = AuditAction.SOURCE_UPDATED
    
    elif "/notes" in path:
        resource_type = AuditResourceType.NOTE
        if method == "POST":
            action = AuditAction.NOTE_CREATED
        elif method == "PUT":
            action = AuditAction.NOTE_UPDATED
        elif method == "DELETE":
            action = AuditAction.NOTE_DELETED
        else:
            action = AuditAction.NOTE_UPDATED
    
    elif "/users" in path:
        resource_type = AuditResourceType.SYSTEM
        if method == "POST":
            action = AuditAction.USER_CREATED
        elif method == "DELETE":
            action = AuditAction.USER_DELETED
        else:
            action = AuditAction.SYSTEM if hasattr(AuditAction, 'SYSTEM') else AuditAction.TOKEN_REFRESH
    
    elif "/auth" in path or "/login" in path:
        resource_type = AuditResourceType.SYSTEM
        if "login" in path:
            action = AuditAction.LOGIN
        elif "logout" in path:
            action = AuditAction.LOGOUT
        elif "refresh" in path:
            action = AuditAction.TOKEN_REFRESH
        else:
            action = AuditAction.TOKEN_REFRESH
    
    elif "/permissions" in path or "/roles" in path:
        resource_type = AuditResourceType.SYSTEM
        action = AuditAction.TOKEN_REFRESH  # Generic system action
    
    else:
        # Unknown endpoint - still track but be generic
        resource_type = AuditResourceType.SYSTEM
        # Use a generic action if SYSTEM exists, else use a legitimate system action
        action = AuditAction.TOKEN_REFRESH  # Better default than NOTEBOOK_CREATED
    
    # Extract resource ID from path (e.g., /notebooks/123 -> 123)
    parts = path.split('/')
    resource_id = parts[-1] if parts[-1] and not parts[-1].startswith('?') else None
    
    return action, resource_type, resource_id


# API Router for audit logs (admin only)
audit_router = APIRouter(prefix="/api/audit", tags=["audit"])


@audit_router.get("/logs")
async def get_audit_logs(
    request: Request,
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
):
    """
    Retrieve audit logs with filtering.
    Requires: Admin role or AUDIT_VIEW permission
    
    Permission check: Enforced via JWT middleware + RBAC
    """
    
    # Permission check: JWT middleware + RBAC enforces admin-only access
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if 'admin' not in user.get('roles', []):
        logger.warning(f"⚠️ Unauthorized audit log access attempt by {user.get('email')}")
        raise HTTPException(status_code=403, detail="Admin access required to view audit logs")
    
    # Parse dates if provided
    start = None
    end = None
    
    if start_date:
        start = datetime.fromisoformat(start_date)
    if end_date:
        end = datetime.fromisoformat(end_date)
    
    logs = await audit_service.query_logs(
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        action=action,
        start_date=start,
        end_date=end,
        limit=limit,
    )
    
    return {
        "total": len(logs),
        "logs": logs,
    }


@audit_router.get("/user/{user_id}/activity")
async def get_user_activity(
    request: Request,
    user_id: str,
    days: int = Query(30, ge=1, le=365),
):
    """
    Get user's activity summary.
    Requires: Admin role (to view other users' activity)
    """
    
    # Permission check
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Users can view their own activity, admins can view anyone
    if user.get('id') != user_id and 'admin' not in user.get('roles', []):
        logger.warning(f"⚠️ Unauthorized activity access attempt by {user.get('email')}")
        raise HTTPException(status_code=403, detail="Cannot view other users' activity")
    
    activity = await audit_service.get_user_activity(user_id, days)
    return activity


@audit_router.get("/search")
async def search_audit_logs(
    request: Request,
    q: str = Query(..., min_length=2),
    limit: int = Query(50, le=100),
):
    """
    Search audit logs by resource name and action.
    Requires: Admin role
    """
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if 'admin' not in user.get('roles', []):
        raise HTTPException(status_code=403, detail="Admin access required")

    logs = await audit_service.search_logs(q, limit)
    return {
        "query": q,
        "total": len(logs),
        "logs": logs,
    }


@audit_router.get("/stats")
async def get_audit_stats(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    """
    Get audit statistics for the specified period.
    Requires: Admin role
    """
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if 'admin' not in user.get('roles', []):
        raise HTTPException(status_code=403, detail="Admin access required")

    activity = await audit_service.get_user_activity("__all__", days)
    return activity
