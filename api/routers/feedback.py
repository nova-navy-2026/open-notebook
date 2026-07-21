"""User feedback on assistant answers.

When a user marks an answer as "not helpful" (they didn't like it), we record a
row in the same ``content_flag`` table the admin already triages, tagged with
the ``user_disliked`` category. This gives the admin a single oversight queue
that now also surfaces low-rated responses, without granting any broader access.

Unlike the flags router (admin-only), this endpoint is available to any
authenticated user — they can only report their own conversation turns.
"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import BaseModel, Field

from api.auth import get_current_user_id
from api.risk_scan import actor_context
from open_notebook.domain.content_flag import (
    MAX_EXCERPT_CHARS,
    USER_FEEDBACK_CATEGORY,
    ContentFlag,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


class ResponseFeedbackRequest(BaseModel):
    assistant_content: str = Field(..., description="The assistant answer the user disliked")
    user_question: Optional[str] = Field(
        None, description="The user message that prompted the answer (for context)"
    )
    comment: Optional[str] = Field(None, description="Optional free-text reason")
    session_id: Optional[str] = Field(None, description="Chat session id, if any")
    notebook_id: Optional[str] = Field(None, description="Notebook id, if a notebook chat")
    surface: Optional[str] = Field(
        None, description="Where it happened: notebook_chat | global_chat | source_chat"
    )


class ResponseFeedbackResponse(BaseModel):
    ok: bool
    flag_id: Optional[str] = None


@router.post("/response", response_model=ResponseFeedbackResponse)
async def report_disliked_response(
    body: ResponseFeedbackRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """Record that the current user disliked an assistant answer."""
    content = (body.assistant_content or "").strip()
    if not content:
        return ResponseFeedbackResponse(ok=False)

    # Preserve the exchange so the admin can see what was disliked even if the
    # user later deletes the conversation.
    snapshot = []
    if body.user_question:
        snapshot.append({"type": "human", "content": body.user_question})
    snapshot.append({"type": "ai", "content": content})

    identity = actor_context(request)
    surface = body.surface or "chat"

    flag = await ContentFlag.record(
        content_type="assistant_message",
        content_id=f"feedback:{uuid.uuid4().hex}",
        categories=[USER_FEEDBACK_CATEGORY],
        severity="low",
        reason=(body.comment or "User marked this response as not helpful."),
        excerpt=content[:MAX_EXCERPT_CHARS],
        title=f"Disliked response ({surface})",
        notebook_id=body.notebook_id,
        session_id=body.session_id,
        conversation_snapshot=json.dumps(snapshot, ensure_ascii=False),
        **identity,
    )
    if flag is None:
        logger.warning("[feedback] failed to persist user response feedback")
        return ResponseFeedbackResponse(ok=False)
    return ResponseFeedbackResponse(ok=True, flag_id=getattr(flag, "id", None))
