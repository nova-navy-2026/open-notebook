"""Navy document access control.

Each authenticated user carries (from the users directory file)::

    {
      "m24409": {"email": "borges.rodrigues@marinha.pt",
                 "departments": ["SI-DAGI"], "clearance_level": 2}
    }

* ``departments`` (list[str]) \u2014 the units/entities the user belongs to.
  The legacy single-value ``department`` (str) key is still accepted.
* ``clearance_level`` (int 0-4) \u2014 the user's clearance. The legacy
  ``clearence`` key is still accepted.

Each document carries the richer navy template::

    {
      "document_status": "active",
      "access_scope": "general" | "departmental" | "individual",
      "allowed_entities": ["COMNAV", "EMA", "SI-DAGI"] | ["m24409"] | ["general"],
      "classification_level": 2,
      ...
    }

A user may read a document iff::

    user.clearance_level  >= document.classification_level
    document.document_status == "active"
    AND ( "general"        in document.allowed_entities
          OR user_id       in document.allowed_entities   # individual docs
          OR any department in document.allowed_entities ) # departmental docs

IMPORTANT: index field names:
    The navy OpenSearch corpus uses the richer template documented above:
    ``classification_level``, ``allowed_entities``, ``document_status``,
    ``access_scope`` and ``creator_department``. The live OpenSearch filter
    queries those field names directly and fails closed for unknown users.

This module is navy-specific: it lives in open-notebook, not in
NOVA-Researcher. open-notebook is responsible for translating the
authenticated user into an OpenSearch filter clause and sending that
clause to NOVA-Researcher via the ``retriever_filter`` field on the
research / opensearch-prefetch payloads.

User directory: JSON file at the path given by ``NAVY_USERS_FILE``
(default: ``./users.json``).
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

# The reserved entity that opens a document to every department/user.
WILDCARD_DEPARTMENT = "general"

# Documents whose status is anything other than this are treated as expired /
# archived and filtered out.
ACTIVE_STATUS = "active"

# ---------------------------------------------------------------------------
# OpenSearch index field names.
#
# The navy corpus has been reindexed to the richer template, so the live
# filter queries the new field names below. (The legacy names
# ``allowed_departments`` / ``document_classification`` are no longer present
# in the index.) ``is_document_allowed`` still understands both key sets for
# any in-memory documents that predate the reindex.
# ---------------------------------------------------------------------------
ENTITY_FIELD = "allowed_entities"
CLASSIFICATION_FIELD = "classification_level"
STATUS_FIELD = "document_status"
ACCESS_SCOPE_FIELD = "access_scope"
CREATOR_DEPARTMENT_FIELD = "creator_department"


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
# User-field normalization (new template + legacy fallback)
# ---------------------------------------------------------------------------
def user_departments(user: Dict[str, Any]) -> List[str]:
    """Return the user's departments as a list.

    Accepts the new ``departments`` (list) key and falls back to the legacy
    ``department`` (single string) key.
    """
    depts = user.get("departments")
    if isinstance(depts, (list, tuple, set)):
        return [str(d) for d in depts if d]
    if isinstance(depts, str) and depts:
        return [depts]
    single = user.get("department")
    return [str(single)] if single else []


def user_clearance(user: Dict[str, Any]) -> int:
    """Return the user's clearance level.

    Accepts the new ``clearance_level`` key and falls back to the legacy
    ``clearence`` key. Defaults to 0 on missing/invalid values.
    """
    raw = user.get("clearance_level")
    if raw is None:
        raw = user.get("clearence", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _document_classification(document: Dict[str, Any]) -> Optional[int]:
    """Read a document's classification, supporting old and new key names."""
    raw = document.get("classification_level")
    if raw is None:
        raw = document.get("document_classification", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _document_entities(document: Dict[str, Any]) -> List[str]:
    """Read a document's allowed entities, supporting old and new key names."""
    allowed = document.get("allowed_entities")
    if allowed is None:
        allowed = document.get("allowed_departments")
    return list(allowed or [])


def _document_is_active(document: Dict[str, Any]) -> bool:
    """Return True when the document is active."""
    status = document.get("document_status")
    return str(status or "").strip().lower() == ACTIVE_STATUS


def _document_creator_department(document: Dict[str, Any]) -> Optional[str]:
    raw = document.get("creator_department")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


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
    * Returns a fail-closed clause (matches nothing) when ``user_id`` is
      missing, unknown, or ``"__admin__"``.
    * Otherwise returns the clearance + department clause.

    NOTE: ``"__admin__"`` deliberately fails CLOSED. Admins have no blanket
    access to user content, and the navy corpus is read-only material the risk
    classifier never scans — so there is nothing in it an admin is entitled to
    see. (This was an unfiltered bypass before 2026-07-20.)
    """
    if not access_enabled():
        return None

    user = get_user(user_id)
    if not user:
        # Fail-closed.
        return {"bool": {"must_not": {"match_all": {}}}}

    clearance = user_clearance(user)
    departments = user_departments(user)

    return build_opensearch_filter_for_profile(
        clearance, departments, extra_entities=[user_id]
    )


def build_opensearch_filter_for_profile(
    clearance: int,
    departments: List[str],
    extra_entities: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build an OpenSearch ``bool`` filter clause for a given access profile.

    This is the profile-level core shared by per-user filtering
    (``build_opensearch_filter``) and collaborative-notebook filtering
    (``open_notebook.collaboration.effective_navy_filter``), which passes the
    notebook's *effective* (most-restrictive) clearance + intersected
    departments.

    * ``clearance`` — max classification level the profile may read.
    * ``departments`` — departmental entities the profile may match.
    * ``extra_entities`` — additional allowed entities (e.g. an individual
      navy user id, so personal documents stay visible to that user). Omitted
      for collaborative notebooks, which have no single owning individual.
    """
    departments = list(departments or [])
    # Entities the profile is allowed to match:
    #   - each department → departmental documents,
    #   - any extra entities (e.g. the user's own navy id → individual docs),
    #   - the "general" wildcard → general documents.
    entities = [*(extra_entities or []), *departments, WILDCARD_DEPARTMENT]
    access_should: List[Dict[str, Any]] = [
        {"terms": {ENTITY_FIELD: entities}},
        {"term": {ACCESS_SCOPE_FIELD: WILDCARD_DEPARTMENT}},
    ]
    if departments:
        # Current corpus rows may carry the department in creator_department
        # instead of repeating it in allowed_entities.
        access_should.append({"terms": {CREATOR_DEPARTMENT_FIELD: departments}})

    return {
        "bool": {
            "must": [
                {"range": {CLASSIFICATION_FIELD: {"lte": clearance}}},
                {
                    "bool": {
                        "should": access_should,
                        "minimum_should_match": 1,
                    }
                },
                {"term": {STATUS_FIELD: ACTIVE_STATUS}},
            ]
        }
    }


def is_document_allowed(
    document: Dict[str, Any],
    user_id: Optional[str],
) -> bool:
    """In-memory equivalent of ``build_opensearch_filter`` — useful for
    post-filtering documents that didn't go through OpenSearch.

    Understands both the legacy keys (``document_classification`` /
    ``allowed_departments``) and the new template keys (``classification_level``
    / ``allowed_entities`` / ``document_status`` / ``access_scope``).
    """
    if not access_enabled():
        return True

    # No admin bypass: "__admin__" is not a known user, so it falls through to
    # the fail-closed branch below. See build_opensearch_filter.
    user = get_user(user_id)
    if not user:
        return False

    # Expired/archived documents are never visible.
    if not _document_is_active(document):
        return False

    clearance = user_clearance(user)
    doc_class = _document_classification(document)
    if doc_class is None or doc_class > clearance:
        return False

    allowed = _document_entities(document)
    if WILDCARD_DEPARTMENT in allowed:
        return True
    if user_id in allowed:  # individual documents
        return True
    departments = user_departments(user)
    if any(dept in allowed for dept in departments):
        return True
    creator_department = _document_creator_department(document)
    if creator_department and creator_department in departments:
        return True
    return str(document.get("access_scope", "")).strip().lower() == WILDCARD_DEPARTMENT


__all__ = [
    "CLASSIFICATION_MAP",
    "WILDCARD_DEPARTMENT",
    "ACTIVE_STATUS",
    "ENTITY_FIELD",
    "CLASSIFICATION_FIELD",
    "STATUS_FIELD",
    "ACCESS_SCOPE_FIELD",
    "CREATOR_DEPARTMENT_FIELD",
    "access_enabled",
    "build_opensearch_filter",
    "build_opensearch_filter_for_profile",
    "get_user",
    "get_user_by_email",
    "is_document_allowed",
    "load_users",
    "user_clearance",
    "user_departments",
]
