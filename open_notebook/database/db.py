"""
Database connection helper for async access to SurrealDB.
Provides get_db() function for easy database access without context managers.
"""

import os
from surrealdb import AsyncSurreal
from loguru import logger


async def get_db():
    """Get an async database connection to SurrealDB"""
    
    try:
        # Get connection URL
        surreal_url = os.getenv("SURREAL_URL") or os.getenv("SURREALDB_URL")
        if not surreal_url:
            address = os.getenv("SURREAL_ADDRESS", "localhost")
            port = os.getenv("SURREAL_PORT", "8000")
            surreal_url = f"ws://{address}:{port}/rpc"
        
        # Create connection
        db = AsyncSurreal(surreal_url)
        
        # Get credentials
        user = os.getenv("SURREAL_USER", "root")
        password = os.getenv("SURREAL_PASSWORD") or os.getenv("SURREAL_PASS", "root")
        namespace = os.getenv("SURREAL_NAMESPACE", "open_notebook")
        database = os.getenv("SURREAL_DATABASE", "open_notebook")
        
        # Connect and authenticate
        await db.connect()
        await db.signin({"user": user, "pass": password})
        await db.use(namespace, database)
        
        return db
    
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {e}")
        raise
