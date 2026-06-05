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
                {"range": {"classification_level": {"lte": 2}}},
                {"terms": {"allowed_entities": ["m1", "OPS", "general"]}},
                {
                    "bool": {
                        "should": [
                            {"term": {"document_status": "active"}},
                            {
                                "bool": {
                                    "must_not": {
                                        "exists": {"field": "document_status"}
                                    }
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
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


def test_acl_filter_supports_new_user_template(monkeypatch):
    monkeypatch.setattr(
        "open_notebook.access_control.load_users",
        lambda: {
            "m24409": {
                "departments": ["SI-DAGI", "COMNAV"],
                "clearance_level": 2,
            }
        },
    )

    flt = build_opensearch_filter("m24409")
    assert flt["bool"]["must"][1] == {
        "terms": {
            "allowed_entities": ["m24409", "SI-DAGI", "COMNAV", "general"]
        }
    }


def test_is_document_allowed_new_template(monkeypatch):
    monkeypatch.setattr(
        "open_notebook.access_control.load_users",
        lambda: {
            "m24409": {
                "departments": ["SI-DAGI"],
                "clearance_level": 2,
            }
        },
    )

    # Departmental document the user belongs to.
    assert is_document_allowed(
        {
            "document_status": "active",
            "access_scope": "departmental",
            "allowed_entities": ["COMNAV", "EMA", "SI-DAGI"],
            "classification_level": 2,
        },
        "m24409",
    )

    # Individual document targeted at this user.
    assert is_document_allowed(
        {
            "document_status": "active",
            "access_scope": "individual",
            "allowed_entities": ["m24409"],
            "classification_level": 2,
        },
        "m24409",
    )

    # General document.
    assert is_document_allowed(
        {
            "document_status": "active",
            "access_scope": "general",
            "allowed_entities": ["general"],
            "classification_level": 1,
        },
        "m24409",
    )

    # Inactive document is hidden even when otherwise accessible.
    assert not is_document_allowed(
        {
            "document_status": "archived",
            "access_scope": "general",
            "allowed_entities": ["general"],
            "classification_level": 1,
        },
        "m24409",
    )

    # Individual document for a different user is hidden.
    assert not is_document_allowed(
        {
            "document_status": "active",
            "access_scope": "individual",
            "allowed_entities": ["m99999"],
            "classification_level": 1,
        },
        "m24409",
    )

    # Over-clearance document is hidden.
    assert not is_document_allowed(
        {
            "document_status": "active",
            "access_scope": "general",
            "allowed_entities": ["general"],
            "classification_level": 4,
        },
        "m24409",
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
