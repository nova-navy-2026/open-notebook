"""LLM-backed "dangerous content" classifier.

Every piece of user content (chat messages, assistant replies, uploaded
sources, notes) is passed through :func:`classify_content`. Only content the
model judges dangerous produces a ``content_flag`` row, and those rows are the
*only* user content the admin can see — see
``open_notebook.domain.content_flag``.

Design constraints:

* **Never block the user.** Classification runs out-of-band via
  :func:`scan_in_background`; every failure path is swallowed and logged. A
  classifier outage must degrade to "nothing flagged", not to a broken upload
  or a hung chat.
* **Fail-open on errors, fail-closed on parse.** A transport error means "no
  verdict" (nothing flagged). A malformed model reply is also treated as no
  verdict rather than guessed at, so the admin queue stays trustworthy.
* Uses the same OpenAI-compatible Gemma endpoint as the rest of the app
  (``GEMMA_BASE_URL``), mirroring ``api/chat_title.py``.

Environment:
    RISK_CLASSIFIER_ENABLED   "1" (default) to run; "0" disables all scanning.
    RISK_CLASSIFIER_MODEL     model id (defaults to GEMMA_MODEL).
    RISK_CLASSIFIER_TIMEOUT   seconds per call (default 60).
    RISK_CLASSIFIER_MAX_CHARS how much text is sent (default 6000).
    RISK_MIN_SEVERITY         low|medium|high — minimum severity to store
                              (default "low", i.e. store everything flagged).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from open_notebook.domain.content_flag import (
    MAX_EXCERPT_CHARS,
    RISK_CATEGORIES,
    SEVERITIES,
    ContentFlag,
)

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}

# Evidence snapshots are capped so a huge upload can't bloat the flag row.
# Generous enough to keep the flagged item usable as evidence.
MAX_SNAPSHOT_CHARS = 50_000
MAX_CONVERSATION_SNAPSHOT_CHARS = 200_000

CLASSIFIER_PROMPT = """You are a security review assistant for a Portuguese Navy \
(Marinha) knowledge-management system. You examine user-generated content and \
decide whether it must be escalated to a security administrator.

Flag content ONLY if it clearly falls into one or more of these categories:

- "classified_leak": classified or restricted material appearing where it does \
not belong — classification markings (SECRET, CONFIDENCIAL, RESERVADO, NATO \
SECRET…), or attempts to obtain/expose material above the user's clearance.
- "threat_violence": threats against personnel, ships or facilities; sabotage; \
instructions for weapons, explosives or attacks.
- "exfiltration_opsec": attempts to move sensitive data out of the system, \
sharing of credentials or keys, or insecure disclosure of operational details \
such as ship positions, movements, patrol schedules or force readiness.
- "illegal_misconduct": criminal activity, harassment, or serious violations \
of military policy and conduct.

Do NOT flag ordinary work: routine research, training material, general \
maritime or technical discussion, administrative questions, public information, \
or historical/doctrinal references that carry no live operational risk. When in \
doubt, do NOT flag — a false alarm wastes the administrator's attention and \
needlessly exposes a user's private content.

Reply with ONLY a JSON object, no markdown fence and no commentary:

{{"dangerous": true|false, "categories": [...], "severity": "low"|"medium"|"high", \
"reason": "<one sentence, in European Portuguese>", "excerpt": "<the exact \
offending snippet, max 300 characters, copied verbatim from the content>"}}

If nothing qualifies, reply exactly: {{"dangerous": false}}

Content type: {content_type}
--- CONTENT START ---
{content}
--- CONTENT END ---"""


@dataclass
class RiskVerdict:
    """Structured result of a classification pass."""

    dangerous: bool = False
    categories: List[str] = field(default_factory=list)
    severity: str = "medium"
    reason: Optional[str] = None
    excerpt: Optional[str] = None
    model: Optional[str] = None


def classifier_enabled() -> bool:
    """True when risk scanning should run."""
    flag = (os.environ.get("RISK_CLASSIFIER_ENABLED", "1") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    # Without an endpoint there is nothing to call.
    return bool(os.environ.get("GEMMA_BASE_URL", "").strip())


def _model() -> str:
    return os.environ.get("RISK_CLASSIFIER_MODEL") or os.environ.get(
        "GEMMA_MODEL", "google/gemma-4-31B-it"
    )


def _timeout() -> float:
    try:
        return float(os.environ.get("RISK_CLASSIFIER_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def _max_chars() -> int:
    try:
        return int(os.environ.get("RISK_CLASSIFIER_MAX_CHARS", "6000"))
    except ValueError:
        return 6000


def _min_severity() -> str:
    value = (os.environ.get("RISK_MIN_SEVERITY", "low") or "low").strip().lower()
    return value if value in SEVERITIES else "low"


def _parse_verdict(raw: str) -> Optional[RiskVerdict]:
    """Parse the model's JSON reply. Returns None when it can't be trusted."""
    if not raw:
        return None
    text = raw.strip()

    # Models often wrap JSON in a ```json fence despite instructions.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # Otherwise take the outermost {...} span.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start : end + 1]

    try:
        data: Dict[str, Any] = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    if not bool(data.get("dangerous")):
        return RiskVerdict(dangerous=False)

    categories = [
        c for c in (data.get("categories") or []) if c in RISK_CATEGORIES
    ]
    if not categories:
        # Flagged but with no recognisable category — untrustworthy, drop it
        # rather than filing an uncategorised flag.
        return RiskVerdict(dangerous=False)

    severity = str(data.get("severity") or "medium").strip().lower()
    if severity not in SEVERITIES:
        severity = "medium"

    reason = data.get("reason")
    excerpt = data.get("excerpt")
    return RiskVerdict(
        dangerous=True,
        categories=categories,
        severity=severity,
        reason=str(reason)[:500] if reason else None,
        excerpt=str(excerpt)[:MAX_EXCERPT_CHARS] if excerpt else None,
    )


async def classify_content(content: str, content_type: str = "text") -> RiskVerdict:
    """Classify a piece of content. Never raises."""
    if not classifier_enabled():
        return RiskVerdict(dangerous=False)

    text = (content or "").strip()
    if len(text) < 20:
        # Too short to carry meaningful risk; skip the model call.
        return RiskVerdict(dangerous=False)

    base_url = os.environ.get("GEMMA_BASE_URL", "").rstrip("/")
    prompt = CLASSIFIER_PROMPT.format(
        content_type=content_type, content=text[: _max_chars()]
    )
    payload = {
        "model": _model(),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400,
        # Deterministic: the same content should always get the same verdict.
        "temperature": 0.0,
    }
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {os.environ.get('GEMMA_API_KEY', '')}"
                },
            )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        # httpx ConnectError/ReadTimeout often stringify to "", so log the type.
        logger.warning(
            f"[risk] classification call failed ({type(e).__name__}): {e or repr(e)}"
        )
        return RiskVerdict(dangerous=False)

    verdict = _parse_verdict(raw)
    if verdict is None:
        logger.warning(f"[risk] unparseable classifier reply: {str(raw)[:200]!r}")
        return RiskVerdict(dangerous=False)

    verdict.model = _model()
    return verdict


async def _snapshot_conversation(session_id: str) -> Optional[str]:
    """Serialise the conversation so far as JSON, for evidence retention.

    Read at flag time from LangGraph state, because the user may delete the
    session later — at which point that state is gone and the admin would be
    left with only the excerpt. Best-effort: returns None on any failure.
    """
    try:
        import asyncio as _asyncio

        from langchain_core.runnables import RunnableConfig

        from open_notebook.graphs.chat import graph as chat_graph

        state = await _asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": session_id}),
        )
        if not state or not state.values or "messages" not in state.values:
            return None

        messages = [
            {
                "type": getattr(m, "type", "unknown"),
                "content": str(getattr(m, "content", ""))[:MAX_SNAPSHOT_CHARS],
            }
            for m in state.values["messages"]
        ]
        if not messages:
            return None
        return json.dumps(messages, ensure_ascii=False)[:MAX_CONVERSATION_SNAPSHOT_CHARS]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[risk] could not snapshot conversation {session_id}: {e}")
        return None


async def scan_and_flag(
    content: str,
    content_type: str,
    content_id: str,
    *,
    title: Optional[str] = None,
    notebook_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    navy_user_id: Optional[str] = None,
    departments: Optional[List[str]] = None,
    clearance_level: Optional[int] = None,
) -> Optional[ContentFlag]:
    """Classify content and persist a flag when dangerous. Never raises."""
    try:
        verdict = await classify_content(content, content_type=content_type)
        if not verdict.dangerous:
            return None

        if _SEVERITY_RANK.get(verdict.severity, 1) < _SEVERITY_RANK[_min_severity()]:
            logger.debug(
                f"[risk] {content_type} {content_id} flagged {verdict.severity} "
                f"but below RISK_MIN_SEVERITY — not stored"
            )
            return None

        # Fall back to the head of the content when the model gave no snippet,
        # so the admin always has something to triage from.
        excerpt = verdict.excerpt or (content or "")[:MAX_EXCERPT_CHARS]

        # Preserve the evidence now, while it still exists. The user may delete
        # the conversation/source/note later; the flag must survive intact.
        content_snapshot = (content or "")[:MAX_SNAPSHOT_CHARS]
        conversation_snapshot = None
        if content_type in ("chat_message", "assistant_message") and session_id:
            conversation_snapshot = await _snapshot_conversation(session_id)

        return await ContentFlag.record(
            content_type=content_type,
            content_id=content_id,
            categories=verdict.categories,
            severity=verdict.severity,
            reason=verdict.reason,
            excerpt=excerpt,
            title=title,
            notebook_id=notebook_id,
            session_id=session_id,
            user_id=user_id,
            user_email=user_email,
            navy_user_id=navy_user_id,
            departments=departments,
            clearance_level=clearance_level,
            classifier_model=verdict.model,
            content_snapshot=content_snapshot,
            conversation_snapshot=conversation_snapshot,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[risk] scan_and_flag failed for {content_type} {content_id}: {e}")
        return None


def scan_in_background(content: str, content_type: str, content_id: str, **kwargs) -> None:
    """Fire-and-forget wrapper around :func:`scan_and_flag`.

    Chat and upload paths call this so a slow classifier never delays the user.
    The task reference is held until completion so it is not garbage-collected
    mid-flight (asyncio only keeps weak references to running tasks).
    """
    if not classifier_enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("[risk] no running loop — skipping background scan")
        return

    task = loop.create_task(
        scan_and_flag(content, content_type, content_id, **kwargs)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


# Strong references to in-flight background scans.
_BACKGROUND_TASKS: set = set()
