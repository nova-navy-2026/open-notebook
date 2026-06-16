import asyncio

from open_notebook.research import researcher_service as svc


def test_research_menu_loads_private_upload_documents(monkeypatch):
    captured = {}

    async def fake_repo_query(query, params):
        captured["query"] = query
        captured["params"] = params
        return [
            {
                "id": "source:owned",
                "title": "Owned upload",
                "full_text": "conteudo operacional relevante",
                "caption": None,
                "file_mime": "text/plain",
            }
        ]

    monkeypatch.setattr(svc, "repo_query", fake_repo_query)

    docs = asyncio.run(
        svc._load_app_upload_documents(
            svc.ResearchRequest(
                query="resumo operacional",
                auth_user_id="user:one",
            )
        )
    )

    assert "FROM source" in captured["query"]
    assert "updated" in captured["query"]
    assert captured["params"]["owner"] == "user:one"
    assert docs[0]["metadata"]["source"] == "source:owned"


def test_notebook_research_loads_only_linked_upload_documents(monkeypatch):
    captured = {}

    async def fake_repo_query(query, params):
        captured["query"] = query
        captured["params"] = params
        return [
            {
                "id": "source:notebook",
                "title": "Notebook upload",
                "full_text": "conteudo do notebook",
                "caption": "descricao visual",
                "file_mime": "application/pdf",
            }
        ]

    monkeypatch.setattr(svc, "repo_query", fake_repo_query)

    docs = asyncio.run(
        svc._load_app_upload_documents(
            svc.ResearchRequest(
                query="faz um resumo",
                notebook_id="notebook:abc",
                auth_user_id="user:one",
            )
        )
    )

    assert "FROM reference" in captured["query"]
    assert captured["params"]["owner"] == "user:one"
    assert str(captured["params"]["notebook_id"]) == "notebook:abc"
    assert docs[0]["metadata"]["source"] == "source:notebook"


def test_accessible_research_documents_use_auth_user_and_acl_user(monkeypatch):
    seen = {}

    async def fake_load_app_upload_documents(request):
        seen["auth_user_id"] = request.auth_user_id
        return [{"page_content": "private", "metadata": {"source": "source:private"}}]

    async def fake_prefetch_opensearch_docs(query, index, max_results, user_id):
        seen["acl_user_id"] = user_id
        return [{"page_content": "navy", "metadata": {"source": "navy:doc"}}]

    monkeypatch.setattr(svc, "_load_app_upload_documents", fake_load_app_upload_documents)
    monkeypatch.setattr(svc, "_prefetch_opensearch_docs", fake_prefetch_opensearch_docs)

    docs = asyncio.run(
        svc._build_accessible_research_documents(
            svc.ResearchRequest(
                query="seguranca",
                user_id="m24409",
                auth_user_id="user:one",
            ),
            "job-test",
        )
    )

    assert seen == {"auth_user_id": "user:one", "acl_user_id": "m24409"}
    assert [doc["metadata"]["source"] for doc in docs] == ["source:private", "navy:doc"]
