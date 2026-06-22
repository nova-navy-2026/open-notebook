"""Domain models and persistence for collaborative notebooks.

Two join tables back collaborative notebooks (see migration 20):

* ``notebook_member`` — one row per (notebook, user). The owner also gets a
  member row (role ``"owner"``) when the notebook is first shared.
* ``notebook_invite`` — pending/processed invitations, either targeting an
  email address or carrying a redeemable link token.

The ``notebook`` column is a SurrealDB ``record<notebook>`` link, so writes go
through explicit ``repo_query`` calls that pass a ``RecordID`` (ObjectModel's
generic save would store a plain string and fail the schema). Reads come back
with record ids already stringified by the repository layer.
"""

from datetime import datetime
from typing import ClassVar, List, Optional

from loguru import logger
from pydantic import field_validator

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel


def _stringify_record(value):
    """Coerce a RecordID (or anything) to its string form."""
    if value is None:
        return None
    return str(value)


def _is_missing_table(exc: Exception) -> bool:
    """True when the error is a SurrealDB 'table does not exist' error.

    Lets collaboration reads fail safe (no memberships) before migration 20 has
    been applied — e.g. during a rolling deploy. Membership-gated access then
    falls back to owner-only, which is the secure default.
    """
    return "does not exist" in str(exc).lower()


class NotebookMember(ObjectModel):
    table_name: ClassVar[str] = "notebook_member"
    nullable_fields: ClassVar[set[str]] = {"added_by"}

    notebook: str
    user_id: str
    email: str
    role: str = "member"
    added_by: Optional[str] = None

    @field_validator("notebook", mode="before")
    @classmethod
    def _parse_notebook(cls, value):
        return _stringify_record(value)


class NotebookInvite(ObjectModel):
    table_name: ClassVar[str] = "notebook_invite"
    nullable_fields: ClassVar[set[str]] = {
        "email",
        "token",
        "accepted_by",
        "expires",
    }

    notebook: str
    invite_type: str = "email"
    email: Optional[str] = None
    token: Optional[str] = None
    status: str = "pending"
    invited_by: str
    accepted_by: Optional[str] = None
    expires: Optional[datetime] = None

    @field_validator("notebook", mode="before")
    @classmethod
    def _parse_notebook(cls, value):
        return _stringify_record(value)


# ---------------------------------------------------------------------------
# notebook_member persistence
# ---------------------------------------------------------------------------
async def create_member(
    notebook_id: str,
    user_id: str,
    email: str,
    role: str = "member",
    added_by: Optional[str] = None,
) -> NotebookMember:
    """Create (or no-op if already present) a membership row."""
    existing = await get_member(notebook_id, user_id)
    if existing:
        return existing
    rows = await repo_query(
        """
        CREATE notebook_member SET
            notebook = $notebook,
            user_id = $user_id,
            email = $email,
            role = $role,
            added_by = $added_by
        """,
        {
            "notebook": ensure_record_id(notebook_id),
            "user_id": user_id,
            "email": email,
            "role": role,
            "added_by": added_by,
        },
    )
    return NotebookMember(**rows[0])


async def get_members(notebook_id: str) -> List[NotebookMember]:
    try:
        rows = await repo_query(
            "SELECT * FROM notebook_member WHERE notebook = $notebook ORDER BY created ASC",
            {"notebook": ensure_record_id(notebook_id)},
        )
    except Exception as e:
        if _is_missing_table(e):
            return []
        raise
    return [NotebookMember(**r) for r in rows]


async def get_member(notebook_id: str, user_id: str) -> Optional[NotebookMember]:
    try:
        rows = await repo_query(
            "SELECT * FROM notebook_member WHERE notebook = $notebook AND user_id = $user_id LIMIT 1",
            {"notebook": ensure_record_id(notebook_id), "user_id": user_id},
        )
    except Exception as e:
        if _is_missing_table(e):
            return None
        raise
    return NotebookMember(**rows[0]) if rows else None


async def delete_member(notebook_id: str, user_id: str) -> None:
    await repo_query(
        "DELETE notebook_member WHERE notebook = $notebook AND user_id = $user_id",
        {"notebook": ensure_record_id(notebook_id), "user_id": user_id},
    )


async def get_user_memberships(user_id: str) -> List[NotebookMember]:
    """All membership rows for a user (used to scope shared content)."""
    try:
        rows = await repo_query(
            "SELECT * FROM notebook_member WHERE user_id = $user_id",
            {"user_id": user_id},
        )
    except Exception as e:
        if _is_missing_table(e):
            return []
        raise
    return [NotebookMember(**r) for r in rows]


async def get_member_notebook_ids(user_id: str) -> List[str]:
    """Ids of every notebook the user is a member of (string form)."""
    try:
        rows = await repo_query(
            "SELECT VALUE notebook FROM notebook_member WHERE user_id = $user_id",
            {"user_id": user_id},
        )
    except Exception as e:
        if _is_missing_table(e):
            return []
        raise
    return [str(r) for r in rows]


# ---------------------------------------------------------------------------
# notebook_invite persistence
# ---------------------------------------------------------------------------
async def create_invite(
    notebook_id: str,
    invited_by: str,
    invite_type: str = "email",
    email: Optional[str] = None,
    token: Optional[str] = None,
    expires: Optional[datetime] = None,
) -> NotebookInvite:
    rows = await repo_query(
        """
        CREATE notebook_invite SET
            notebook = $notebook,
            invite_type = $invite_type,
            email = $email,
            token = $token,
            status = "pending",
            invited_by = $invited_by,
            expires = $expires
        """,
        {
            "notebook": ensure_record_id(notebook_id),
            "invite_type": invite_type,
            "email": email,
            "token": token,
            "invited_by": invited_by,
            "expires": expires,
        },
    )
    return NotebookInvite(**rows[0])


async def get_invite(invite_id: str) -> Optional[NotebookInvite]:
    rows = await repo_query(
        "SELECT * FROM $id", {"id": ensure_record_id(invite_id)}
    )
    return NotebookInvite(**rows[0]) if rows else None


async def get_invite_by_token(token: str) -> Optional[NotebookInvite]:
    rows = await repo_query(
        "SELECT * FROM notebook_invite WHERE token = $token LIMIT 1",
        {"token": token},
    )
    return NotebookInvite(**rows[0]) if rows else None


async def get_notebook_invites(
    notebook_id: str, status: Optional[str] = None
) -> List[NotebookInvite]:
    query = "SELECT * FROM notebook_invite WHERE notebook = $notebook"
    params = {"notebook": ensure_record_id(notebook_id)}
    if status:
        query += " AND status = $status"
        params["status"] = status
    query += " ORDER BY created DESC"
    rows = await repo_query(query, params)
    return [NotebookInvite(**r) for r in rows]


async def get_pending_invites_for_email(email: str) -> List[NotebookInvite]:
    rows = await repo_query(
        """
        SELECT * FROM notebook_invite
        WHERE email = $email AND status = "pending"
        ORDER BY created DESC
        """,
        {"email": email},
    )
    return [NotebookInvite(**r) for r in rows]


async def get_existing_pending_email_invite(
    notebook_id: str, email: str
) -> Optional[NotebookInvite]:
    rows = await repo_query(
        """
        SELECT * FROM notebook_invite
        WHERE notebook = $notebook AND email = $email AND status = "pending"
        LIMIT 1
        """,
        {"notebook": ensure_record_id(notebook_id), "email": email},
    )
    return NotebookInvite(**rows[0]) if rows else None


async def update_invite_status(
    invite_id: str, status: str, accepted_by: Optional[str] = None
) -> None:
    await repo_query(
        "UPDATE $id SET status = $status, accepted_by = $accepted_by, updated = time::now()",
        {
            "id": ensure_record_id(invite_id),
            "status": status,
            "accepted_by": accepted_by,
        },
    )


async def delete_notebook_collaboration(notebook_id: str) -> None:
    """Remove all members and invites for a notebook (called on notebook delete)."""
    try:
        nb = ensure_record_id(notebook_id)
        await repo_query("DELETE notebook_member WHERE notebook = $nb", {"nb": nb})
        await repo_query("DELETE notebook_invite WHERE notebook = $nb", {"nb": nb})
    except Exception as e:  # pragma: no cover - best-effort cleanup
        logger.warning(f"Failed to clean up collaboration rows for {notebook_id}: {e}")
