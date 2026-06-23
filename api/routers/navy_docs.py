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
