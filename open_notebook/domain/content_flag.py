"""ContentFlag domain model — the admin's *only* window into user content.

Admin oversight in this deployment is deliberately narrow. The admin does not
get blanket visibility over every user's notebooks, sources or conversations;
instead each piece of user content is classified (see
``open_notebook.safety.risk_classifier``) and only items judged dangerous
produce a ``content_flag`` row, which the admin can then triage.

Backed by the 'content_flag' table in SurrealDB (created in migration 24).
"""

from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from loguru import logger

from open_notebook.database.repository import repo_create, repo_query
from open_notebook.domain.base import ObjectModel

# Risk categories the classifier may assign. Kept in sync with the prompt in
# open_notebook/safety/risk_classifier.py.
RISK_CATEGORIES = (
    "classified_leak",
    "threat_violence",
    "exfiltration_opsec",
    "illegal_misconduct",
)

# Category used when a *user* (not the classifier) reports an assistant answer
# they disliked. It rides the same admin-oversight queue so the admin sees the
# low-rated responses alongside classifier flags, but is filterable/labelled
# distinctly. classifier_model is left null on these rows.
USER_FEEDBACK_CATEGORY = "user_disliked"

SEVERITIES = ("low", "medium", "high")

# The kinds of content that get scanned.
CONTENT_TYPES = ("chat_message", "assistant_message", "source", "note")

# Cap on how much of the offending text is stored/shown. The admin triages from
# the snippet; they are not handed the whole private document.
MAX_EXCERPT_CHARS = 1500


class ContentFlag(ObjectModel):
    """One piece of user content that the risk classifier judged dangerous."""

    table_name: ClassVar[str] = "content_flag"
    nullable_fields: ClassVar[set[str]] = {
        "notebook_id",
        "session_id",
        "title",
        "excerpt",
        "user_id",
        "user_email",
        "navy_user_id",
        "clearance_level",
        "reason",
        "classifier_model",
        "reviewed_by",
        "reviewed_at",
        "review_note",
        "content_snapshot",
        "conversation_snapshot",
        "original_deleted_at",
    }

    content_type: str
    content_id: str
    notebook_id: Optional[str] = None
    session_id: Optional[str] = None
    title: Optional[str] = None
    excerpt: Optional[str] = None

    user_id: Optional[str] = None
    user_email: Optional[str] = None
    navy_user_id: Optional[str] = None
    departments: List[str] = []
    clearance_level: Optional[int] = None

    categories: List[str] = []
    severity: str = "medium"
    reason: Optional[str] = None
    classifier_model: Optional[str] = None

    status: str = "open"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None

    # Evidence preserved at flag time so the admin keeps it even if the user
    # later deletes the chat session / source / note.
    content_snapshot: Optional[str] = None
    # JSON string: [{"type": "human"|"ai", "content": "..."}, ...]
    conversation_snapshot: Optional[str] = None
    original_deleted: bool = False
    original_deleted_at: Optional[datetime] = None

    @classmethod
    async def record(
        cls,
        content_type: str,
        content_id: str,
        categories: List[str],
        severity: str = "medium",
        reason: Optional[str] = None,
        excerpt: Optional[str] = None,
        title: Optional[str] = None,
        notebook_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        navy_user_id: Optional[str] = None,
        departments: Optional[List[str]] = None,
        clearance_level: Optional[int] = None,
        classifier_model: Optional[str] = None,
        content_snapshot: Optional[str] = None,
        conversation_snapshot: Optional[str] = None,
    ) -> Optional["ContentFlag"]:
        """Persist a flag. Never raises — flagging must not break user flows."""
        try:
            data = {
                "content_type": content_type,
                "content_id": content_id,
                "notebook_id": notebook_id,
                "session_id": session_id,
                "title": title,
                "excerpt": (excerpt or "")[:MAX_EXCERPT_CHARS] or None,
                "user_id": user_id,
                "user_email": user_email,
                "navy_user_id": navy_user_id,
                "departments": list(departments or []),
                "clearance_level": clearance_level,
                "categories": list(categories or []),
                "severity": severity if severity in SEVERITIES else "medium",
                "reason": reason,
                "classifier_model": classifier_model,
                "status": "open",
                # Evidence: kept verbatim so it outlives the original record.
                "content_snapshot": content_snapshot,
                "conversation_snapshot": conversation_snapshot,
                "original_deleted": False,
            }
            clean = {
                k: v
                for k, v in data.items()
                if v is not None or k in cls.nullable_fields
            }
            result = await repo_create("content_flag", clean)
            row = result[0] if isinstance(result, list) else result
            logger.warning(
                f"[risk] flagged {content_type} {content_id} "
                f"categories={categories} severity={severity} user={user_email or user_id}"
            )
            return cls(**row)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[risk] failed to persist content flag: {e}")
            return None

    @classmethod
    async def query(
        cls,
        status: Optional[str] = None,
        content_type: Optional[str] = None,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query flags with filters. Returns dicts for API responses."""
        conditions: List[str] = []
        params: Dict[str, Any] = {"limit": limit, "offset": offset}

        if status:
            conditions.append("status = $status")
            params["status"] = status
        if content_type:
            conditions.append("content_type = $content_type")
            params["content_type"] = content_type
        if severity:
            conditions.append("severity = $severity")
            params["severity"] = severity
        if category:
            conditions.append("$category IN categories")
            params["category"] = category
        if user_id:
            conditions.append("user_id = $user_id")
            params["user_id"] = user_id

        where = " AND ".join(conditions) if conditions else "true"
        q = (
            f"SELECT * FROM content_flag WHERE {where} "
            "ORDER BY created DESC LIMIT $limit START $offset"
        )
        return await repo_query(q, params)

    @classmethod
    async def counts_by_status(cls) -> Dict[str, int]:
        """Return {status: count} for the admin badge/summary."""
        try:
            rows = await repo_query(
                "SELECT status, count() FROM content_flag GROUP BY status"
            )
            return {r["status"]: r["count"] for r in rows if r.get("status")}
        except Exception as e:  # noqa: BLE001
            logger.error(f"[risk] failed to count flags: {e}")
            return {}

    @classmethod
    async def is_flagged(cls, content_type: str, content_id: str) -> bool:
        """True when this exact item already has a flag (dedupe / access check)."""
        rows = await repo_query(
            "SELECT VALUE id FROM content_flag "
            "WHERE content_type = $ct AND content_id = $cid LIMIT 1",
            {"ct": content_type, "cid": content_id},
        )
        return bool(rows)

    @classmethod
    async def flagged_content_ids(cls, content_type: str) -> List[str]:
        """All flagged content ids of a given type.

        This is what grants the admin read access: the admin may open a source
        or note only when it appears here.
        """
        rows = await repo_query(
            "SELECT VALUE content_id FROM content_flag WHERE content_type = $ct",
            {"ct": content_type},
        )
        return [r for r in rows if r]

    @classmethod
    async def mark_original_deleted(
        cls,
        *,
        content_type: Optional[str] = None,
        content_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Tag flags whose underlying record the user just deleted.

        The flag row and its snapshots are deliberately KEPT — deleting the
        chat/source/note must not destroy the admin's evidence. This only
        records that the original is gone, so the viewer can say so.

        Pass either ``content_type``+``content_id`` (source/note) or
        ``session_id`` (a whole conversation, which may hold several flags).
        Returns the number of flags updated. Never raises.
        """
        try:
            if session_id:
                where = "session_id = $sid"
                params: Dict[str, Any] = {"sid": str(session_id)}
            elif content_type and content_id:
                where = "content_type = $ct AND content_id = $cid"
                params = {"ct": content_type, "cid": str(content_id)}
            else:
                return 0

            rows = await repo_query(
                f"UPDATE content_flag SET original_deleted = true, "
                f"original_deleted_at = time::now() WHERE {where} RETURN id",
                params,
            )
            count = len(rows or [])
            if count:
                logger.warning(
                    f"[risk] original content deleted by user; {count} flag(s) "
                    f"retained as evidence ({where} {params})"
                )
            return count
        except Exception as e:  # noqa: BLE001
            logger.error(f"[risk] failed to mark original deleted: {e}")
            return 0

    async def mark_reviewed(
        self, reviewed_by: str, status: str = "reviewed", note: Optional[str] = None
    ) -> None:
        """Record an admin triage decision (``reviewed`` or ``dismissed``)."""
        if status not in ("open", "reviewed", "dismissed"):
            raise ValueError(f"invalid status: {status}")
        self.status = status
        self.reviewed_by = reviewed_by
        self.reviewed_at = datetime.now()
        self.review_note = note
        await self.save()
