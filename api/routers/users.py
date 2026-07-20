"""
User management router for admin operations.
Backed by SurrealDB 'user' table.
"""

from fastapi import APIRouter, Request, HTTPException
from loguru import logger

from open_notebook.domain.user import User

router = APIRouter(prefix="/users", tags=["users"])

# The only roles this deployment recognises. "admin" is the single bootstrap
# account (ADMIN_EMAIL); everyone else is "user".
VALID_ROLES = {"admin", "user"}


@router.get("")
async def list_users(request: Request):
    """
    List all users in the system.
    Requires admin role.
    """
    try:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        users = await User.get_active_users()
        return {
            "users": [u.to_safe_dict() for u in users],
            "total": len(users),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch users")


@router.get("/{user_id}")
async def get_user(user_id: str, request: Request):
    """
    Get a specific user by ID.
    Requires admin role.
    """
    try:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Ensure the ID has the table prefix
        record_id = user_id if ":" in user_id else f"user:{user_id}"
        try:
            db_user = await User.get(record_id)
        except Exception:
            raise HTTPException(status_code=404, detail="User not found")

        return db_user.to_safe_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user")


@router.post("")
async def create_user(request: Request):
    """
    Create a new user.
    Requires admin role.
    """
    try:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        body = await request.json()

        email = body.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        # Check for existing user with same email
        existing = await User.get_by_email(email)
        if existing:
            raise HTTPException(status_code=409, detail="User with this email already exists")

        # Force role to "user" - admin creation via the API is not allowed here.
        # Only the bootstrap admin (ADMIN_EMAIL / ADMIN_PASSWORD) can be an admin.
        new_user = User(
            email=email,
            name=body.get("name"),
            roles=["user"],
            provider=body.get("provider", "local"),
            is_active=True,
        )

        password = body.get("password")
        if password:
            new_user.set_password(password)

        await new_user.save()

        logger.info(f"User created: {email}")
        return new_user.to_safe_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")


@router.put("/{user_id}/roles")
async def update_user_roles(user_id: str, request: Request):
    """
    Update user roles.
    Requires admin role.
    """
    try:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        body = await request.json()
        roles = body.get("roles", ["user"])

        # Only two roles exist: "admin" and "user". Reject anything else so a
        # stale client can't write a role the rest of the system won't honour.
        invalid = [r for r in roles if r not in VALID_ROLES]
        if not roles or invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role(s): {invalid or roles}. Allowed: {sorted(VALID_ROLES)}",
            )

        record_id = user_id if ":" in user_id else f"user:{user_id}"
        try:
            db_user = await User.get(record_id)
        except Exception:
            raise HTTPException(status_code=404, detail="User not found")

        db_user.roles = roles
        await db_user.save()

        logger.info(f"User {user_id} roles updated to {roles}")
        return db_user.to_safe_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user roles: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user roles")


@router.delete("/{user_id}")
async def delete_user(user_id: str, request: Request):
    """
    Delete a user.
    Requires admin role.
    """
    try:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        record_id = user_id if ":" in user_id else f"user:{user_id}"
        try:
            db_user = await User.get(record_id)
        except Exception:
            raise HTTPException(status_code=404, detail="User not found")

        # Don't allow deleting users with admin role (protect last admin)
        if "admin" in db_user.roles:
            # Count remaining admins
            all_users = await User.get_active_users()
            admin_count = sum(1 for u in all_users if "admin" in u.roles)
            if admin_count <= 1:
                raise HTTPException(
                    status_code=403, detail="Cannot delete the last admin user"
                )

        await db_user.delete()
        logger.info(f"User deleted: {user_id}")
        return {"id": user_id, "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user")


