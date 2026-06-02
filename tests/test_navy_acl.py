from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.auth import get_navy_acl_user_id
from open_notebook.access_control import build_opensearch_filter, is_document_allowed
from open_notebook.search import navy_docs


def test_admin_with_navy_identity_uses_navy_acl_identity():
    request = SimpleNamespace(
        state=SimpleNamespace(
            user_permissions=["admin"],
            navy_user_id="m24409",
        )
    )

    assert get_navy_acl_user_id(request) == "m24409"


def test_admin_without_navy_identity_keeps_bootstrap_bypass():
    request = SimpleNamespace(
        state=SimpleNamespace(
            user_permissions=["admin"],
            navy_user_id=None,
        )
    )

    assert get_navy_acl_user_id(request) == "__admin__"


def test_acl_filter_requires_clearance_and_department(monkeypatch):
    monkeypatch.setattr(
        "open_notebook.access_control.load_users",
        lambda: {
            "m1": {
                "department": "OPS",
                "clearence": 2,
            }
        },
    )

    assert build_opensearch_filter("m1") == {
        "bool": {
            "must": [
                {"range": {"document_classification": {"lte": 2}}},
                {"terms": {"allowed_departments": ["OPS", "general"]}},
            ]
        }
    }

    assert is_document_allowed(
        {"document_classification": 2, "allowed_departments": ["OPS"]},
        "m1",
    )
    assert is_document_allowed(
        {"document_classification": 2, "allowed_departments": ["general"]},
        "m1",
    )
    assert not is_document_allowed(
        {"document_classification": 3, "allowed_departments": ["OPS"]},
        "m1",
    )
    assert not is_document_allowed(
        {"document_classification": 1, "allowed_departments": ["ENG"]},
        "m1",
    )


@pytest.mark.asyncio
async def test_navy_vector_fallback_preserves_acl_user(monkeypatch):
    async def fail_embedding(_query):
        raise RuntimeError("embedding service unavailable")

    fallback = AsyncMock(return_value=[])

    monkeypatch.setattr("open_notebook.utils.embedding.generate_embedding", fail_embedding)
    monkeypatch.setattr(navy_docs, "search_navy_documents", fallback)

    await navy_docs.vector_search_navy_documents(
        query="radar procedures",
        doc_ids=["doc-a"],
        k=7,
        user_id="m24409",
    )

    fallback.assert_awaited_once_with(
        "radar procedures",
        doc_ids=["doc-a"],
        k=7,
        user_id="m24409",
    )
