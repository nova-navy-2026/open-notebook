"""Request-side glue for the "dangerous content" classifier.

Routers call :func:`scan_request_text` to queue a background risk scan for a
piece of user content. The heavy lifting lives in
``open_notebook.safety.risk_classifier``; this module's job is to pull the
actor's identity (app user + navy ACL profile) off the request so a flag can
tell the admin *who* produced the content and at what clearance.

Every helper here is best-effort: risk scanning must never break the flow that
triggered it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request
from loguru import logger

from open_notebook.safety.risk_classifier import classifier_enabled, scan_in_background


def actor_context(request: Optional[Request]) -> Dict[str, Any]:
    """Extract the caller's identity for attribution on a flag.

    Returns the kwargs subset ``scan_request_text`` passes through to the
    classifier. Missing/anonymous identity is fine — the flag is still worth
    recording, just with less attribution.
    """
    if request is None:
        return {}
    try:
        state = request.state
        user = getattr(state, "user", None)
        email = None
        if isinstance(user, dict):
            email = user.get("email")
        elif user is not None:
            email = getattr(user, "email", None)

        departments = getattr(state, "navy_departments", None)
        return {
            "user_id": getattr(state, "user_id", None),
            "user_email": email,
            "navy_user_id": getattr(state, "navy_user_id", None),
            "departments": list(departments) if departments else [],
            "clearance_level": getattr(state, "navy_clearance", None),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[risk] could not read actor context: {e}")
        return {}


def scan_request_text(
    request: Optional[Request],
    content: str,
    content_type: str,
    content_id: str,
    *,
    title: Optional[str] = None,
    notebook_id: Optional[str] = None,
    session_id: Optional[str] = None,
    **overrides: Any,
) -> None:
    """Queue a background risk scan of ``content``. Never raises, never blocks.

    ``overrides`` lets callers supply identity fields directly when they are
    not on the request (e.g. a background/worker path with no Request object).
    """
    if not classifier_enabled():
        return
    if not (content or "").strip():
        return
    try:
        ctx = actor_context(request)
        ctx.update({k: v for k, v in overrides.items() if v is not None})
        scan_in_background(
            content,
            content_type,
            content_id,
            title=title,
            notebook_id=notebook_id,
            session_id=session_id,
            **ctx,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[risk] failed to queue scan for {content_type} {content_id}: {e}")
