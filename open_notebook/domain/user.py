"""
User domain model for authentication and RBAC.

Backed by the 'user' table in SurrealDB (created in migration 015,
password_hash added in migration 019).
"""

from datetime import datetime
from typing import ClassVar, List, Optional, Type

import bcrypt
from loguru import logger

from open_notebook.database.repository import repo_query
from open_notebook.domain.base import ObjectModel


class User(ObjectModel):
    """
    User record for authentication and role-based access control.

    Maps to the 'user' SurrealDB table with fields:
      email (unique), name, roles, provider, external_id,
      is_active, created, updated, last_login, password_hash
    """

    table_name: ClassVar[str] = "user"
    nullable_fields: ClassVar[set[str]] = {
        "external_id",
        "last_login",
        "name",
        "password_hash",
    }

    email: str
    name: Optional[str] = None
    roles: List[str] = ["user"]
    provider: str = "local"
    external_id: Optional[str] = None
    is_active: bool = True
    last_login: Optional[datetime] = None
    password_hash: Optional[str] = None

    def set_password(self, plain_password: str) -> None:
        """Hash and store a plain-text password using bcrypt."""
        self.password_hash = bcrypt.hashpw(
            plain_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def verify_password(self, plain_password: str) -> bool:
        """Check a plain-text password against the stored hash."""
        if not self.password_hash:
            return False
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            self.password_hash.encode("utf-8"),
        )

    @classmethod
    async def get_by_email(cls, email: str) -> Optional["User"]:
        """Find a user by email address."""
        results = await repo_query(
            "SELECT * FROM user WHERE email = $email LIMIT 1",
            {"email": email},
        )
        if results:
            return cls(**results[0])
        return None

    @classmethod
    async def get_by_provider(
        cls, provider: str, external_id: str
    ) -> Optional["User"]:
        """Find a user by OAuth provider and external ID."""
        results = await repo_query(
            "SELECT * FROM user WHERE provider = $provider AND external_id = $ext_id LIMIT 1",
            {"provider": provider, "ext_id": external_id},
        )
        if results:
            return cls(**results[0])
        return None

    @classmethod
    async def get_active_users(cls) -> List["User"]:
        """Get all active users."""
        results = await repo_query(
            "SELECT * FROM user WHERE is_active = true ORDER BY created DESC"
        )
        users = []
        for row in results:
            try:
                users.append(cls(**row))
            except Exception as e:
                logger.warning(f"Skipping invalid user row: {e}")
        return users

    async def update_last_login(self) -> None:
        """Record a login timestamp."""
        await repo_query(
            f"UPDATE {self.id} SET last_login = time::now(), updated = time::now()",
        )

    def to_safe_dict(self) -> dict:
        """Return user data safe for API responses (no secrets)."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "roles": self.roles,
            "provider": self.provider,
            "is_active": self.is_active,
            "created": self.created.isoformat() if self.created else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }
