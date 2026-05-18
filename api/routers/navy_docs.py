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

from api.auth import get_navy_acl_user_id
from open_notebook.search.navy_docs import list_navy_documents, search_navy_documents

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class NavyDocument(BaseModel):
    doc_id: str
    chunk_count: int
    source: str = ""
    sample_section: str = ""


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
