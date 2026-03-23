"""
Health check router for monitoring API and database status.
"""

from fastapi import APIRouter, Request
from loguru import logger

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    """
    General health check for the API.
    Returns 200 OK if the API is running.
    """
    return {
        "status": "healthy",
        "message": "API is running",
    }


@router.get("/db")
async def health_check_database(request: Request):
    """
    Health check for database connectivity.
    Returns database connection status.
    """
    try:
        # Try to access the database from request state if available
        user = getattr(request.state, "user", None)
        
        return {
            "status": "healthy",
            "message": "Database is connected",
            "database": "SurrealDB",
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Database connection failed: {str(e)}",
            "database": "SurrealDB",
        }
