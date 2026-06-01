"""Persistent log of verification failures from the /ask flow.

When the iterative self-check (`verify_answer` node in
`open_notebook.graphs.ask`) detects that the original final answer is not
fully grounded in the sub-answers, the failure is appended here as a JSONL
record. The log is the input signal for the prompt-improvement loop in
`prompt_improver.py`.

This module intentionally avoids any database dependency: it is opt-in
observability, not part of the request path's correctness, and must never
break the user request if writing fails.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.config import DATA_FOLDER

FAILURE_LOG_PATH = os.path.join(DATA_FOLDER, "verify_failures.jsonl")
_LOCK = threading.Lock()


def record_failure(
    question: str,
    original_answer: str,
    revised_answer: Optional[str],
    issues: List[str],
    sub_answers: Optional[List[str]] = None,
) -> None:
    """Append a single verification-failure record. Best-effort: never raises."""
    try:
        os.makedirs(os.path.dirname(FAILURE_LOG_PATH), exist_ok=True)
        record: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "original_answer": original_answer,
            "revised_answer": revised_answer,
            "issues": issues,
        }
        if sub_answers is not None:
            record["sub_answers"] = sub_answers
        line = json.dumps(record, ensure_ascii=False)
        with _LOCK:
            with open(FAILURE_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as e:
        logger.warning(f"Could not persist verify failure: {e}")


def read_failures(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent `limit` failure records (newest last)."""
    if not os.path.exists(FAILURE_LOG_PATH):
        return []
    try:
        with open(FAILURE_LOG_PATH, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        records: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        return records
    except Exception as e:
        logger.warning(f"Could not read verify failure log: {e}")
        return []
