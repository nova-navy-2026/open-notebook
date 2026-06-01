"""Structured JSONL logging for chat-agent routing and tool calls."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

from loguru import logger

_WRITE_LOCK = threading.Lock()


def _enabled() -> bool:
    return os.environ.get("CHAT_AGENT_TOOL_LOG_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
    }


def _log_path() -> Path:
    explicit = os.environ.get("CHAT_AGENT_TOOL_LOG_FILE")
    if explicit:
        return Path(explicit).expanduser()
    directory = Path(os.environ.get("CHAT_AGENT_TOOL_LOG_DIR", "data/logs"))
    return directory / "chat_agent_tool_calls.jsonl"


def chat_agent_tool_log_path() -> Path:
    """Return the path where structured chat-agent events are appended."""
    return _log_path()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    """Make best-effort JSON-safe values without losing useful diagnostics."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(exclude_none=True))
    return str(value)


def _compact(event: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _jsonable(value) for key, value in event.items() if value is not None}


def build_chat_agent_event(
    *,
    source: str,
    user_id: Optional[str],
    surface: str,
    agent: str,
    event: str,
    status: str,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    notebook_id: Optional[str] = None,
    model_id: Optional[str] = None,
    message_preview: Optional[str] = None,
    file: Optional[Mapping[str, Any]] = None,
    duration_ms: Optional[int] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    return _compact(
        {
            "schema_version": 1,
            "event_id": uuid4().hex,
            "timestamp": _now_iso(),
            "source": source,
            "user_id": user_id or "anonymous",
            "surface": surface,
            "run_id": run_id,
            "session_id": session_id,
            "notebook_id": notebook_id,
            "model_id": model_id,
            "agent": agent,
            "event": event,
            "status": status,
            "message_preview": message_preview,
            "file": file,
            "duration_ms": duration_ms,
            "details": details or {},
        }
    )


def _append_jsonl(event: Mapping[str, Any]) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")


async def write_chat_agent_event(event: Mapping[str, Any]) -> bool:
    """Append one event to JSONL.

    Logging must never break chat execution, so failures are swallowed after a
    warning and reported as False.
    """
    if not _enabled():
        return False
    try:
        _append_jsonl(event)
        return True
    except Exception as exc:
        logger.warning("Failed to write structured chat-agent log: {}", exc)
        return False
