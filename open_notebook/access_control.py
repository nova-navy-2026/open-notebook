"""Navy document access control.

Each indexed document in the navy OpenSearch corpus carries:

* ``document_classification`` (int 0-4) \u2014 see ``CLASSIFICATION_MAP``.
* ``allowed_departments`` (list[str]) \u2014 departments allowed to read the
  document. The reserved value ``"general"`` means "any department".

Each authenticated user carries (from the users directory file):

* ``department`` (str)
* ``clearence`` (int 0-4)  \u2014 spelling matches the navy schema in use.

A user may read a document iff::

    user.clearence       >= document.document_classification
    user.department      in document.allowed_departments
        OR  "general"    in document.allowed_departments

This module is navy-specific: it lives in open-notebook, not in
NOVA-Researcher. open-notebook is responsible for translating the
authenticated user into an OpenSearch filter clause and sending that
clause to NOVA-Researcher via the ``retriever_filter`` field on the
research / opensearch-prefetch payloads.

User directory: JSON file at the path given by ``NAVY_USERS_FILE``
(default: ``./users.json``). Example::

    {
      "m24409": {"email": "borges.rodrigues@marinha.pt",
                 "department": "SI-DAGI", "clearence": 2},
      "m25109": {"email": "ferreira.guerra@marinha.pt",
                 "department": "SI-DITIC", "clearence": 2}
    }
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Classification levels \u2014 higher == more sensitive.
CLASSIFICATION_MAP: Dict[str, int] = {
    "nonclassified": 0,
    "restricted": 1,
    "confidential": 2,
    "secret": 3,
    "topsecret": 4,
}

# Departments listed here in a document's ``allowed_departments`` open
# the document to every department.
WILDCARD_DEPARTMENT = "general"


# ---------------------------------------------------------------------------
# User directory loading (cached per file path + mtime)
# ---------------------------------------------------------------------------
_users_cache_lock = threading.Lock()
_users_cache: Dict[str, tuple] = {}  # path -> (mtime, dict)


def _users_file_path() -> str:
    return os.environ.get("NAVY_USERS_FILE", "users.json")


def load_users(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Load the user directory from a JSON file, with mtime-based caching."""
    path = path or _users_file_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        logger.warning("[navy-acl] users file %r not readable: %s", path, exc)
        return {}

    with _users_cache_lock:
        cached = _users_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("[navy-acl] failed to load %r: %s", path, exc)
            return {}

        if not isinstance(data, dict):
            logger.error("[navy-acl] %r: expected object at top level", path)
            return {}

        _users_cache[path] = (mtime, data)
        return data


def get_user(user_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the user metadata dict, or None when unknown / missing."""
    if not user_id:
        return None
    user = load_users().get(user_id)
    if user is None:
        logger.warning("[navy-acl] unknown user id %r", user_id)
    return user


def get_user_by_email(email: Optional[str]) -> Optional[tuple]:
    """Find a navy user by email. Returns ``(navy_id, user_dict)`` or None."""
    if not email:
        return None
    email_lc = email.strip().lower()
    for navy_id, entry in load_users().items():
        if not isinstance(entry, dict):
            continue
        entry_email = (entry.get("email") or "").strip().lower()
        if entry_email and entry_email == email_lc:
            return navy_id, entry
    return None


def access_enabled() -> bool:
    """Return True when navy access control should be enforced."""
    flag = (os.environ.get("NAVY_ACCESS_CONTROL", "1") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# Filter builder \u2014 produces an OpenSearch ``bool`` clause to be sent to
# NOVA-Researcher as the ``retriever_filter`` field.
# ---------------------------------------------------------------------------
def build_opensearch_filter(
    user_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Return an OpenSearch ``bool`` filter clause for the given user.

    * Returns ``None`` when access control is disabled — NOVA-Researcher
      will then run an unfiltered kNN query.
    * Returns ``None`` when ``user_id`` is ``"__admin__"`` — admins bypass
      ACL entirely and see every document.
    * Returns a fail-closed clause (matches nothing) when ``user_id`` is
      missing or unknown.
    * Otherwise returns the clearance + department clause.
    """
    if not access_enabled():
        return None

    # Admin bypass — no filter applied, all documents visible.
    if user_id == "__admin__":
        return None

    user = get_user(user_id)
    if not user:
        # Fail-closed.
        return {"bool": {"must_not": {"match_all": {}}}}

    try:
        clearance = int(user.get("clearence", 0))
    except (TypeError, ValueError):
        clearance = 0
    department = user.get("department") or ""

    return {
        "bool": {
            "must": [
                {
                    "range": {
                        "document_classification": {"lte": clearance}
                    }
                },
                {
                    "terms": {
                        "allowed_departments": [department, WILDCARD_DEPARTMENT]
                    }
                },
            ]
        }
    }


def is_document_allowed(
    document: Dict[str, Any],
    user_id: Optional[str],
) -> bool:
    """In-memory equivalent of ``build_opensearch_filter`` — useful for
    post-filtering documents that didn't go through OpenSearch."""
    if not access_enabled():
        return True

    # Admin bypass.
    if user_id == "__admin__":
        return True

    user = get_user(user_id)
    if not user:
        return False

    try:
        clearance = int(user.get("clearence", 0))
    except (TypeError, ValueError):
        return False
    department = user.get("department") or ""

    try:
        doc_class = int(document.get("document_classification", 0))
    except (TypeError, ValueError):
        return False
    if doc_class > clearance:
        return False

    allowed: List[str] = list(document.get("allowed_departments") or [])
    if WILDCARD_DEPARTMENT in allowed:
        return True
    return department in allowed


__all__ = [
    "CLASSIFICATION_MAP",
    "WILDCARD_DEPARTMENT",
    "access_enabled",
    "build_opensearch_filter",
    "get_user",
    "get_user_by_email",
    "is_document_allowed",
    "load_users",
]
