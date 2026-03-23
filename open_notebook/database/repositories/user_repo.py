"""
User Repository for SurrealDB operations.
Handles creating, updating, and querying user records.
"""

from typing import Optional, Dict, Any
from uuid import uuid4
from datetime import datetime
from loguru import logger

from open_notebook.database.db import get_db


class UserRepository:
    """Repository for user operations in SurrealDB"""
    
    async def create(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new user"""
        
        try:
            db = await get_db()
            
            user_id = user_data.get("id", f"user:{uuid4()}")
            
            user = {
                "id": user_id,
                "email": user_data["email"],
                "name": user_data.get("name", ""),
                "roles": user_data.get("roles", ["viewer"]),
                "provider": user_data.get("provider", "local"),
                "external_id": user_data.get("external_id"),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "is_active": True
            }
            
            # Create user in SurrealDB
            query = f"CREATE user SET * = $data"
            result = await db.query(query, {"data": user})
            
            logger.info(f"✅ User created: {user['email']}")
            return user
        
        except Exception as e:
            logger.error(f"❌ Error creating user: {e}")
            raise
    
    async def upsert(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update a user (upsert)"""
        
        try:
            db = await get_db()
            
            email = user_data["email"]
            
            # Check if user exists
            existing = await self.get_by_email(email)
            
            if existing:
                # Update existing user
                return await self.update(existing["id"], user_data)
            else:
                # Create new user
                return await self.create(user_data)
        
        except Exception as e:
            logger.error(f"❌ Error upserting user: {e}")
            raise
    
    async def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        
        try:
            db = await get_db()
            
            query = "SELECT * FROM $table WHERE id = $id"
            result = await db.query(query, {
                "table": "user",
                "id": user_id
            })
            
            if result and len(result) > 0:
                return result[0]
            
            return None
        
        except Exception as e:
            logger.error(f"❌ Error getting user: {e}")
            raise
    
    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email address"""
        
        try:
            db = await get_db()
            
            query = "SELECT * FROM user WHERE email = $email"
            result = await db.query(query, {"email": email.lower()})
            
            if result and len(result) > 0:
                return result[0]
            
            return None
        
        except Exception as e:
            logger.error(f"❌ Error getting user by email: {e}")
            raise
    
    async def update(self, user_id: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a user"""
        
        try:
            db = await get_db()
            
            update_data = {
                k: v for k, v in user_data.items()
                if k not in ["id", "created_at"]
            }
            update_data["updated_at"] = datetime.utcnow().isoformat()
            
            query = f"UPDATE $id SET * = $data"
            result = await db.query(query, {
                "id": user_id,
                "data": update_data
            })
            
            logger.info(f"✅ User updated: {user_id}")
            
            return await self.get(user_id) or {}
        
        except Exception as e:
            logger.error(f"❌ Error updating user: {e}")
            raise
    
    async def set_roles(self, user_id: str, roles: list) -> Dict[str, Any]:
        """Set user roles"""
        
        try:
            db = await get_db()
            
            query = f"UPDATE $id SET roles = $roles"
            await db.query(query, {
                "id": user_id,
                "roles": roles
            })
            
            logger.info(f"✅ User roles updated: {user_id} -> {roles}")
            
            return await self.get(user_id) or {}
        
        except Exception as e:
            logger.error(f"❌ Error setting user roles: {e}")
            raise
    
    async def list_all(self, limit: int = 100) -> list:
        """List all users"""
        
        try:
            db = await get_db()
            
            query = f"SELECT * FROM user LIMIT $limit"
            result = await db.query(query, {"limit": limit})
            
            return result or []
        
        except Exception as e:
            logger.error(f"❌ Error listing users: {e}")
            raise
    
    async def delete(self, user_id: str) -> bool:
        """Delete a user"""
        
        try:
            db = await get_db()
            
            query = "DELETE FROM $id"
            await db.query(query, {"id": user_id})
            
            logger.info(f"✅ User deleted: {user_id}")
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Error deleting user: {e}")
            raise
