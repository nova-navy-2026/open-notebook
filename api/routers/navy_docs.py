"""
Navy Corpus API — browse and search the pre-indexed navy document corpus.

Endpoints:
  GET  /api/navy-docs           — list all unique documents
  POST /api/navy-docs/search    — BM25 search within selected documents
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api.auth import get_navy_acl_user_id, is_admin
from fastapi import Request
from open_notebook.search.navy_docs import (
    build_document_graph,
    get_navy_document_content,
    list_navy_documents,
    search_navy_documents,
)
from open_notebook.search.topics import get_topic_taxonomy

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class NavyDocument(BaseModel):
    doc_id: str
    chunk_count: int
    source: str = ""
    sample_section: str = ""
    # Governance metadata for hierarchical grouping in the UI.
    document_type: str = ""
    document_status: str = ""
    access_scope: str = ""
    classification_level: Optional[int] = None
    creator_department: str = ""


class NavyDocumentListResponse(BaseModel):
    documents: List[NavyDocument]
    total: int


class NavyDocumentContentResponse(BaseModel):
    """Full text + metadata of a single navy document (ACL-checked)."""

    doc_id: str
    title: str
    content: str
    chunk_count: int = 0
    document_type: str = ""
    document_status: str = ""
    access_scope: str = ""
    classification_level: Optional[int] = None
    creator_department: str = ""
    source: str = ""


class NavyDocChatMessage(BaseModel):
    role: str = "human"  # "human" | "ai"
    content: str = ""


class NavyDocChatRequest(BaseModel):
    doc_id: str
    message: str = Field(..., min_length=1)
    history: Optional[List[NavyDocChatMessage]] = None
    model_id: Optional[str] = None


class NavyDocChatResponse(BaseModel):
    answer: str
    used_chunks: int = 0


class NavyDocInsightsResponse(BaseModel):
    doc_id: str
    insights: str = ""


class NavySearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query")
    doc_ids: Optional[List[str]] = Field(None, description="Filter to these doc_ids only")
    k: int = Field(10, ge=1, le=50, description="Number of results")


class NavySearchResult(BaseModel):
    doc_id: str
    content: str
    source: str = ""
    section_title: str = ""
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    score: float = 0.0


class NavySearchResponse(BaseModel):
    results: List[NavySearchResult]
    total: int


# --- Document-relationship graph ------------------------------------------

class TopicClass(BaseModel):
    id: str
    label: str
    color: str = "#94a3b8"


class DocumentGraphRequest(BaseModel):
    doc_ids: List[str] = Field(
        ..., description="Documents to include in the relationship graph"
    )


class GraphDocumentClass(BaseModel):
    cls: str = Field(..., alias="class")
    count: int

    model_config = {"populate_by_name": True}


class GraphDocumentNode(BaseModel):
    id: str
    label: str
    chunk_count: int
    classes: List[GraphDocumentClass]


class GraphTopicNode(BaseModel):
    id: str
    label: str
    color: str
    doc_count: int
    chunk_count: int


class BipartiteEdge(BaseModel):
    source: str
    topic: str
    weight: int


class SimilarityEdge(BaseModel):
    source: str
    target: str
    weight: float
    shared: List[str]


class DocumentGraphResponse(BaseModel):
    documents: List[GraphDocumentNode]
    topics: List[GraphTopicNode]
    edges_bipartite: List[BipartiteEdge]
    edges_similarity: List[SimilarityEdge]


class ClassifyRequest(BaseModel):
    mode: str = Field("mock", description="'mock' (deterministic) or 'real' (LLM)")
    overwrite: bool = Field(True, description="Re-classify chunks that already have a class")


class ClassifyResponse(BaseModel):
    command_id: str
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/navy-docs", response_model=NavyDocumentListResponse)
async def get_navy_documents(
    user_id: Optional[str] = Depends(get_navy_acl_user_id),
):
    """List all unique documents in the navy corpus the current user can access.

    Admins see all documents. Regular users are ACL-filtered by clearance +
    department. Callers with no navy identity get an empty list (fail-closed).
    """
    # Fail-closed for authenticated users with no navy identity.
    if user_id is None:
        return NavyDocumentListResponse(documents=[], total=0)
    try:
        documents = await list_navy_documents(user_id=user_id)
        return NavyDocumentListResponse(
            documents=[NavyDocument(**d) for d in documents],
            total=len(documents),
        )
    except Exception as e:
        logger.error(f"Error listing navy documents: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing navy documents: {e}")


@router.get("/navy-docs/content", response_model=NavyDocumentContentResponse)
async def get_navy_doc_content(
    doc_id: str,
    user_id: Optional[str] = Depends(get_navy_acl_user_id),
):
    """Return one navy document's full text + metadata, ACL-checked.

    404 when the document doesn't exist OR the caller may not read it
    (fail-closed for users with no navy identity).
    """
    if user_id is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        doc = await get_navy_document_content(doc_id=doc_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Error fetching navy document content for {doc_id!r}: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching document: {e}")
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return NavyDocumentContentResponse(**doc)


@router.post("/navy-docs/chat", response_model=NavyDocChatResponse)
async def navy_doc_chat(
    request: NavyDocChatRequest,
    user_id: Optional[str] = Depends(get_navy_acl_user_id),
):
    """Answer a question about a SINGLE navy document (RAG over that doc only).

    ACL-enforced: retrieval is scoped to ``doc_id`` AND the user's clearance +
    departments (``search_navy_documents`` applies ``build_opensearch_filter``),
    so a user who may not read the document gets no excerpts → the model can't
    surface its content. Fail-closed for users with no navy identity.
    """
    if user_id is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        # Retrieve the most relevant chunks, restricted to this document and the
        # caller's access profile (clearance + department).
        results = await search_navy_documents(
            query=request.message,
            doc_ids=[request.doc_id],
            k=8,
            user_id=user_id,
        )

        context = "\n\n".join(
            f"[{r.get('section_title') or 'excerpt'}]\n{r.get('content', '')}"
            for r in results
            if r.get("content")
        )

        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
        )
        from open_notebook.ai.provision import provision_langchain_model
        from open_notebook.utils.text_utils import extract_text_content

        system = (
            "You are answering questions about ONE specific document. Use ONLY "
            "the excerpts below — do not use outside knowledge. If the answer is "
            "not in them, say you could not find it in this document. Reply in "
            "the same language as the user's question.\n\n"
            "Document excerpts:\n"
            f"{context if context else '(no relevant excerpts found)'}"
        )
        messages = [SystemMessage(content=system)]
        for m in (request.history or [])[-10:]:
            text = (m.content or "").strip()
            if not text:
                continue
            if (m.role or "").lower() in ("ai", "assistant"):
                messages.append(AIMessage(content=text))
            else:
                messages.append(HumanMessage(content=text))
        messages.append(HumanMessage(content=request.message))

        model = await provision_langchain_model(
            system + request.message, request.model_id, "chat", max_tokens=2048
        )
        ai = await model.ainvoke(messages)
        answer = extract_text_content(getattr(ai, "content", "")) or ""
        return NavyDocChatResponse(answer=answer, used_chunks=len(results))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Navy doc chat failed for {request.doc_id!r}: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")


@router.get("/navy-docs/insights", response_model=NavyDocInsightsResponse)
async def navy_doc_insights(
    doc_id: str,
    user_id: Optional[str] = Depends(get_navy_acl_user_id),
):
    """Generate concise AI insights for one navy document (ACL-checked).

    Generated on demand from the document's text (no copy/Source is created).
    404 when the caller may not read the document.
    """
    if user_id is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        doc = await get_navy_document_content(doc_id=doc_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Error fetching navy document for insights {doc_id!r}: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching document: {e}")
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    content = (doc.get("content") or "").strip()
    if not content:
        return NavyDocInsightsResponse(doc_id=doc_id, insights="")

    # Cap the prompt size; the model auto-upgrades to large-context above 105k
    # tokens, but capping keeps insights fast/cheap.
    excerpt = content[:30000]
    prompt = (
        "Analyse the following document and produce concise, useful insights "
        "in the same language as the document. Use Markdown with these parts:\n"
        "1. A 2-3 sentence summary.\n"
        "2. 4-7 key points as bullets.\n"
        "3. Notable entities / dates / references, if any.\n\n"
        f"Document:\n{excerpt}"
    )

    try:
        from langchain_core.messages import HumanMessage
        from open_notebook.ai.provision import provision_langchain_model
        from open_notebook.utils.text_utils import extract_text_content

        model = await provision_langchain_model(
            excerpt, None, "transformation", max_tokens=1500
        )
        ai = await model.ainvoke([HumanMessage(content=prompt)])
        insights = extract_text_content(getattr(ai, "content", "")) or ""
        return NavyDocInsightsResponse(doc_id=doc_id, insights=insights)
    except Exception as e:
        logger.error(f"Navy doc insights failed for {doc_id!r}: {e}")
        raise HTTPException(status_code=500, detail=f"Insights failed: {e}")


@router.post("/navy-docs/search", response_model=NavySearchResponse)
async def search_navy_docs(
    request: NavySearchRequest,
    user_id: Optional[str] = Depends(get_navy_acl_user_id),
):
    """Search the navy corpus with BM25, ACL-filtered for the current user.

    Admins see all documents. Regular users are ACL-filtered by clearance +
    department. Callers with no navy identity get no results (fail-closed).
    """
    if user_id is None:
        return NavySearchResponse(results=[], total=0)
    try:
        results = await search_navy_documents(
            query=request.query,
            doc_ids=request.doc_ids,
            k=request.k,
            user_id=user_id,
        )
        return NavySearchResponse(
            results=[NavySearchResult(**r) for r in results],
            total=len(results),
        )
    except Exception as e:
        logger.error(f"Error searching navy documents: {e}")
        raise HTTPException(status_code=500, detail=f"Error searching navy documents: {e}")


@router.get("/navy-docs/topics", response_model=List[TopicClass])
async def get_topics():
    """Return the fixed, global topic taxonomy used by the relationship graph."""
    return [TopicClass(**c) for c in get_topic_taxonomy()]


@router.post("/navy-docs/graph", response_model=DocumentGraphResponse)
async def document_graph(
    request: DocumentGraphRequest,
    user_id: Optional[str] = Depends(get_navy_acl_user_id),
):
    """Build the topic-clustered relationship graph for a set of documents.

    ACL-filtered for the current user. Callers with no navy identity get an
    empty graph (fail-closed).
    """
    if user_id is None or not request.doc_ids:
        return DocumentGraphResponse(
            documents=[], topics=[], edges_bipartite=[], edges_similarity=[]
        )
    try:
        graph = await build_document_graph(request.doc_ids, user_id=user_id)
        return DocumentGraphResponse(
            documents=[GraphDocumentNode(**d) for d in graph["documents"]],
            topics=[GraphTopicNode(**t) for t in graph["topics"]],
            edges_bipartite=[BipartiteEdge(**e) for e in graph["edges_bipartite"]],
            edges_similarity=[SimilarityEdge(**e) for e in graph["edges_similarity"]],
        )
    except Exception as e:
        logger.error(f"Error building document graph: {e}")
        raise HTTPException(status_code=500, detail=f"Error building document graph: {e}")


@router.post("/navy-docs/classify", response_model=ClassifyResponse)
async def classify_navy_topics(request: Request, body: ClassifyRequest):
    """Start a background job to (re)classify navy chunks into the taxonomy.

    Admin-only: this rewrites the ``topic_class`` field across the corpus.
    ``mode='mock'`` assigns deterministic placeholder classes (fast, no LLM);
    ``mode='real'`` runs the LLM classification (the canonical pass).
    """
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin privileges required.")

    if body.mode not in ("mock", "real"):
        raise HTTPException(status_code=400, detail="mode must be 'mock' or 'real'.")

    try:
        from api.command_service import CommandService
        import commands.topic_classification_commands  # noqa: F401

        command_id = await CommandService.submit_command_job(
            "open_notebook",
            "classify_topics",
            {"mode": body.mode, "overwrite": body.overwrite},
        )
        logger.info(f"Submitted classify_topics command ({body.mode}): {command_id}")
        return ClassifyResponse(
            command_id=command_id,
            message=f"Topic classification ({body.mode}) started in the background.",
        )
    except Exception as e:
        logger.error(f"Failed to start topic classification: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start classification: {e}")
