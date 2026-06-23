"""
Topic taxonomy for the document-relationship graph.

A single, fixed, *global* taxonomy is applied at the chunk level: every chunk
in the navy corpus is labelled with exactly one ``topic_class`` drawn from this
list. A document then inherits the *union* of its chunks' classes, which is why
a document can belong to several topic clusters at once.

The canonical list lives in ``topic_taxonomy.json`` next to this module so it can
be regenerated (bootstrap) or hand-edited without code changes. The OpenSearch
chunk field is named ``topic_class`` to avoid colliding with the existing
``classification_level`` field (a *security* classification, unrelated to topic).
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

# Name of the keyword field written onto each chunk in the navy index.
TOPIC_CLASS_FIELD = "topic_class"

_TAXONOMY_PATH = Path(__file__).with_name("topic_taxonomy.json")

# Fallback colour for any class id not present in the taxonomy (e.g. stale data
# left over from a previous taxonomy version).
_FALLBACK_COLOR = "#94a3b8"


@lru_cache(maxsize=1)
def _load() -> Dict[str, Any]:
    with _TAXONOMY_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_topic_taxonomy() -> List[Dict[str, str]]:
    """Return the ordered list of topic classes: ``[{id, label, color}, ...]``."""
    return list(_load().get("classes", []))


def get_topic_class_ids() -> List[str]:
    """Return just the class ids, in taxonomy order."""
    return [c["id"] for c in get_topic_taxonomy()]


def get_topic_color_map() -> Dict[str, str]:
    """Map every class id to its display colour (with a grey fallback default)."""
    return {c["id"]: c.get("color", _FALLBACK_COLOR) for c in get_topic_taxonomy()}


def get_topic_label_map() -> Dict[str, str]:
    """Map every class id to its human-readable label."""
    return {c["id"]: c.get("label", c["id"]) for c in get_topic_taxonomy()}


def is_mock_taxonomy() -> bool:
    """True while the taxonomy is still the placeholder/mock list."""
    return _load().get("source") == "mock"
