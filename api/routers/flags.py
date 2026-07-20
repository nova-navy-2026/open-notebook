"""Admin router for flagged ("dangerous") user content.

This is the admin's oversight surface. It is deliberately the *only* way an
admin reaches user content: the notebooks/sources listings no longer grant
blanket visibility, so anything not flagged by the risk classifier stays
private to its owner.

All endpoints are admin-only.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel

from api.auth import is_admin
from open_notebook.domain.content_flag import (
    CONTENT_TYPES,
    RISK_CATEGORIES,
    SEVERITIES,
    ContentFlag,
)

router = APIRouter(prefix="/flags", tags=["flags"])


class ReviewRequest(BaseModel):
    """Admin triage decision on a flag."""

    status: str  # reviewed | dismissed | open
    note: Optional[str] = None


def _require_admin(request: Request) -> None:
    """Admin-only gate. 404 rather than 403 so the surface isn't advertised."""
    if not is_admin(request):
        raise HTTPException(status_code=404, detail="Not found")


@router.get("")
async def list_flags(
    request: Request,
    status: Optional[str] = Query(None, description="open | reviewed | dismissed"),
    content_type: Optional[str] = Query(None, description=f"One of {CONTENT_TYPES}"),
    severity: Optional[str] = Query(None, description=f"One of {SEVERITIES}"),
    category: Optional[str] = Query(None, description=f"One of {RISK_CATEGORIES}"),
    user_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List flagged content, newest first."""
    _require_admin(request)
    try:
        flags = await ContentFlag.query(
            status=status,
            content_type=content_type,
            severity=severity,
            category=category,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        return {"flags": flags, "total": len(flags)}
    except Exception as e:
        logger.error(f"Error fetching content flags: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch flags")


@router.get("/summary")
async def flags_summary(request: Request):
    """Counts by status — drives the admin badge."""
    _require_admin(request)
    try:
        counts = await ContentFlag.counts_by_status()
        return {
            "counts": counts,
            "open": counts.get("open", 0),
            "total": sum(counts.values()),
        }
    except Exception as e:
        logger.error(f"Error summarising content flags: {e}")
        raise HTTPException(status_code=500, detail="Failed to summarise flags")


@router.get("/{flag_id}")
async def get_flag(flag_id: str, request: Request):
    """Get one flag, including its stored excerpt."""
    _require_admin(request)
    record_id = flag_id if ":" in flag_id else f"content_flag:{flag_id}"
    try:
        flag = await ContentFlag.get(record_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Flag not found")
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")
    return flag.model_dump()


@router.get("/{flag_id}/conversation")
async def get_flag_conversation(flag_id: str, request: Request):
    """Full conversation behind a flagged chat turn.

    Access is mediated entirely by the flag: the admin can read this
    conversation *because* it was flagged, not because they are an admin. A
    flag on any other content type has no conversation to show.
    """
    _require_admin(request)

    record_id = flag_id if ":" in flag_id else f"content_flag:{flag_id}"
    try:
        flag = await ContentFlag.get(record_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Flag not found")
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")

    if flag.content_type not in ("chat_message", "assistant_message"):
        raise HTTPException(
            status_code=400, detail="This flag is not a chat message"
        )
    if not flag.session_id:
        raise HTTPException(status_code=404, detail="Conversation not available")

    # Prefer the live conversation; fall back to the snapshot taken when the
    # flag was raised. The snapshot is what makes this survive the user
    # deleting their chat.
    messages: list = []
    source = "live"
    title = None

    try:
        import asyncio

        from langchain_core.runnables import RunnableConfig

        from open_notebook.domain.notebook import ChatSession
        from open_notebook.graphs.chat import graph as chat_graph

        session = await ChatSession.get(flag.session_id)
        title = getattr(session, "title", None) if session else None
        state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": flag.session_id}),
        )
        if state and state.values and "messages" in state.values:
            messages = [
                {
                    "type": getattr(msg, "type", "unknown"),
                    "content": getattr(msg, "content", str(msg)),
                }
                for msg in state.values["messages"]
            ]
    except Exception as e:
        logger.warning(
            f"Live conversation unavailable for flag {record_id} "
            f"({type(e).__name__}); falling back to snapshot"
        )

    if not messages and flag.conversation_snapshot:
        try:
            messages = json.loads(flag.conversation_snapshot)
            source = "snapshot"
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Corrupt conversation snapshot on flag {record_id}: {e}")

    return {
        "flag_id": str(flag.id),
        "session_id": flag.session_id,
        "title": title,
        "notebook_id": flag.notebook_id,
        "messages": messages,
        "message_count": len(messages),
        # "snapshot" means the live conversation is gone and this is the
        # preserved copy taken at flag time.
        "source": source,
        "original_deleted": bool(flag.original_deleted),
    }


@router.put("/{flag_id}/review")
async def review_flag(flag_id: str, body: ReviewRequest, request: Request):
    """Record a triage decision (reviewed / dismissed / reopened)."""
    _require_admin(request)

    if body.status not in ("open", "reviewed", "dismissed"):
        raise HTTPException(
            status_code=400,
            detail="status must be one of: open, reviewed, dismissed",
        )

    record_id = flag_id if ":" in flag_id else f"content_flag:{flag_id}"
    try:
        flag = await ContentFlag.get(record_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Flag not found")
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")

    user = getattr(request.state, "user", None)
    reviewer = (
        user.get("email") if isinstance(user, dict) else None
    ) or getattr(request.state, "user_id", "admin")

    try:
        await flag.mark_reviewed(reviewer, status=body.status, note=body.note)
        logger.info(f"Flag {record_id} marked {body.status} by {reviewer}")
        return flag.model_dump()
    except Exception as e:
        logger.error(f"Error reviewing flag {record_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update flag")
