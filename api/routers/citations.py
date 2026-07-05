"""
Citations API — temporary materialization of cited OpenSearch documents.

Backs the citation viewer side panel: clicking a navy-corpus citation
materializes the reconstructed document (with highlight offsets) into the
``cited_document`` SurrealDB table; closing the panel deletes it again.

Endpoints:
  POST   /api/citations/materialize — reconstruct + upsert a cited document
  GET    /api/citations/{record_id} — refetch a materialized document
  DELETE /api/citations/{record_id} — remove it (panel closed)
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from api.auth import get_current_user_id, get_navy_acl_user_id
from api.citations_service import (
    delete_cited_document,
    get_cited_document,
    materialize_citation,
)
from open_notebook.domain.cited_document import CitedDocument

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class MaterializeCitationRequest(BaseModel):
    ref: str = Field(
        ...,
        description=(
            "Citation ref: 'navy:{doc_id}', 'navy:{doc_id}:p{page}' or "
            "'opensearch://{index}/{chunk_id}'"
        ),
    )
    chunk_id: Optional[str] = Field(
        None, description="Exact cited chunk for chunk-precise highlighting"
    )
    snippet: Optional[str] = Field(
        None, description="Verbatim cited text (e.g. a search-result match)"
    )


class CitationHighlight(BaseModel):
    start: int
    end: int


class CitedDocumentResponse(BaseModel):
    id: str
    doc_id: str
    title: str
    full_text: str
    highlights: List[CitationHighlight] = []
    segments: List[Dict[str, Any]] = []
    document_type: Optional[str] = None
    document_status: Optional[str] = None
    access_scope: Optional[str] = None
    classification_level: Optional[int] = None
    creator_department: Optional[str] = None
    source: Optional[str] = None


def _to_response(record: CitedDocument) -> CitedDocumentResponse:
    return CitedDocumentResponse(
        id=str(record.id),
        doc_id=record.doc_id,
        title=record.title,
        full_text=record.full_text,
        highlights=[CitationHighlight(**h) for h in (record.highlights or [])],
        segments=record.segments or [],
        document_type=record.document_type,
        document_status=record.document_status,
        access_scope=record.access_scope,
        classification_level=record.classification_level,
        creator_department=record.creator_department,
        source=record.source,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/citations/materialize", response_model=CitedDocumentResponse)
async def materialize(
    payload: MaterializeCitationRequest,
    user_id: str = Depends(get_current_user_id),
    navy_acl_user_id: Optional[str] = Depends(get_navy_acl_user_id),
) -> CitedDocumentResponse:
    """Reconstruct a cited OpenSearch document and store it temporarily."""
    record = await materialize_citation(
        ref=payload.ref,
        chunk_id=payload.chunk_id,
        snippet=payload.snippet,
        owner=user_id,
        acl_user_id=navy_acl_user_id,
    )
    return _to_response(record)


@router.get("/citations/{record_id}", response_model=CitedDocumentResponse)
async def get_citation(
    record_id: str,
    user_id: str = Depends(get_current_user_id),
) -> CitedDocumentResponse:
    """Refetch a materialized cited document (ownership-checked)."""
    record = await get_cited_document(record_id, owner=user_id)
    return _to_response(record)


@router.delete("/citations/{record_id}", status_code=204)
async def delete_citation(
    record_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Delete a materialized cited document (the panel was closed)."""
    await delete_cited_document(record_id, owner=user_id)
    return Response(status_code=204)
