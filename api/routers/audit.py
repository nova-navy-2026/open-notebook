"""
Audit logging router for monitoring system activities and user actions.
"""

from fastapi import APIRouter, Request, HTTPException
from loguru import logger

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
async def get_audit_logs(request: Request):
    """
    Get all audit logs.
    Requires admin role.
    """
    try:
        # Check if user is admin
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Return mock audit logs
        # TODO: Implement actual audit log retrieval from database
        return [
            {
                "id": "audit-001",
                "timestamp": "2024-03-23T10:30:00Z",
                "user_id": "admin-user-001",
                "user_email": "admin@open-notebook.local",
                "action": "LOGIN",
                "resource_type": "auth",
                "status": "success",
                "details": {"ip": "127.0.0.1", "method": "local"},
            },
            {
                "id": "audit-002",
                "timestamp": "2024-03-23T10:25:00Z",
                "user_id": "admin-user-001",
                "user_email": "admin@open-notebook.local",
                "action": "USER_CREATED",
                "resource_type": "user",
                "resource_id": "user-123",
                "status": "success",
                "details": {"email": "newuser@example.com", "role": "editor"},
            },
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching audit logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch audit logs")


@router.get("/user/{user_id}/activity")
async def get_user_activity(user_id: str, request: Request):
    """
    Get activity logs for a specific user.
    Users can only view their own activity unless they're admin.
    """
    try:
        current_user = getattr(request.state, "user", None)
        if not current_user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Regular users can only see their own activity
        if current_user.get("id") != user_id and not current_user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Permission denied")
        
        # Return mock user activity logs
        # TODO: Implement actual user activity retrieval from database
        return [
            {
                "id": "audit-user-001",
                "timestamp": "2024-03-23T10:30:00Z",
                "user_id": user_id,
                "user_email": current_user.get("email"),
                "action": "NOTEBOOK_CREATED",
                "resource_type": "notebook",
                "resource_id": "notebook-456",
                "status": "success",
                "details": {"name": "My Research Notes"},
            },
            {
                "id": "audit-user-002",
                "timestamp": "2024-03-23T10:20:00Z",
                "user_id": user_id,
                "user_email": current_user.get("email"),
                "action": "SOURCE_ADDED",
                "resource_type": "source",
                "resource_id": "source-789",
                "status": "success",
                "details": {"file_name": "document.pdf"},
            },
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user activity: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch activity logs")
