"""Helpers for generating concise chat conversation titles.

Shared by the notebook chat (``api/routers/chat.py``) and global chat
(``api/routers/global_chat.py``) routers. The frontend creates sessions lazily
on the first message and then asks the backend to turn that first message into a
short, human-readable title (rather than persisting the raw user prompt).
"""

import os
import re
from typing import Optional

import httpx
from loguru import logger

# Placeholder used when a session is created before its first message is sent.
# Never expose the internal record id / timestamp as a title.
DEFAULT_SESSION_TITLE = "Nova conversa"


def _gemma_title_model() -> str:
    raw = os.environ.get("GEMMA_SMART_LLM", "")
    return raw.split(":")[-1] if raw else "google/gemma-4-31B-it"


def clean_title(text: str) -> str:
    """Tidy an LLM-produced title: strip quotes/prefixes, collapse whitespace."""
    title = (text or "").strip()
    # Drop a leading "Title:" / "Título:" style prefix if the model added one.
    title = re.sub(r"^\s*(title|t[íi]tulo)\s*[:\-]\s*", "", title, flags=re.IGNORECASE)
    title = title.strip().strip("\"'“”‘’").strip()
    title = re.sub(r"\s+", " ", title)
    title = title.splitlines()[0].strip() if title else title
    if len(title) > 80:
        title = title[:80].rstrip() + "…"
    return title


def fallback_title(message: str) -> str:
    """Derive a short, human-readable title without an LLM.

    Used when title generation is unavailable. Takes the first few words so the
    title is not simply the verbatim user prompt for longer messages.
    """
    cleaned = re.sub(r"\s+", " ", (message or "").strip())
    if not cleaned:
        return DEFAULT_SESSION_TITLE
    words = cleaned.split(" ")
    title = " ".join(words[:6])
    if len(words) > 6 or len(title) > 60:
        title = title[:60].rstrip() + "…"
    return title[:1].upper() + title[1:] if title else DEFAULT_SESSION_TITLE


async def generate_session_title(message: str) -> Optional[str]:
    """Ask the lightweight Gemma model for a concise conversation title.

    Returns ``None`` if generation is not configured or fails, so callers can
    fall back to :func:`fallback_title`.
    """
    base_url = os.environ.get("GEMMA_BASE_URL", "").rstrip("/")
    if not base_url or not (message or "").strip():
        return None
    prompt = (
        "Generate a short, descriptive title (3 to 6 words) for a chat "
        "conversation that begins with the user message below. Reply with ONLY "
        "the title, written in the same language as the message, with no "
        "surrounding quotes, no trailing punctuation and no 'Title:' prefix.\n\n"
        f"User message:\n{message.strip()[:500]}"
    )
    payload = {
        "model": _gemma_title_model(),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 30,
        "temperature": 0.3,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {os.environ.get('GEMMA_API_KEY', '')}"},
            )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        title = clean_title(text)
        return title or None
    except Exception as e:
        # Show the exception type even when str(e) is empty (httpx ConnectError /
        # ReadTimeout often have blank messages) so the cause is diagnosable.
        logger.warning(
            f"Chat title generation failed ({type(e).__name__}): {e or repr(e)}"
        )
        return None


async def resolve_session_title(message: str) -> str:
    """Generate a title, falling back to a non-verbatim derivation."""
    return await generate_session_title(message) or fallback_title(message)
