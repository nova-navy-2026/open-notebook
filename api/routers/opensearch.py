"""
OpenSearch management API endpoints.

Provides:
- POST /api/opensearch/reindex  — bulk-reindex from SurrealDB to OpenSearch
- GET  /api/opensearch/status   — check OpenSearch health and index stats
"""

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api.command_service import CommandService
from open_notebook.search import is_opensearch_enabled

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ReindexRequest(BaseModel):
    delete_existing: bool = Field(
        True,
        description="Delete and recreate the OpenSearch index before reindexing",
    )


class ReindexResponse(BaseModel):
    command_id: str
    message: str


class OpenSearchStatus(BaseModel):
    enabled: bool
    healthy: bool = False
    version: str = ""
    index_exists: bool = False
    doc_count: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/reindex", response_model=ReindexResponse)
async def reindex_opensearch(request: ReindexRequest):
    """Start a background job to reindex all SurrealDB embeddings into OpenSearch."""
    if not is_opensearch_enabled():
        raise HTTPException(
            status_code=400,
            detail=(
                "OpenSearch is not enabled. "
                "Set SEARCH_BACKEND=opensearch in your environment."
            ),
        )

    try:
        # Ensure command module is imported
        import commands.opensearch_commands  # noqa: F401

        command_id = await CommandService.submit_command_job(
            "open_notebook",
            "reindex_opensearch",
            {"delete_existing": request.delete_existing},
        )

        logger.info(f"Submitted reindex_opensearch command: {command_id}")

        return ReindexResponse(
            command_id=command_id,
            message="OpenSearch reindex started in the background.",
        )

    except Exception as e:
        logger.error(f"Failed to start OpenSearch reindex: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start reindex: {str(e)}",
        )


@router.get("/status", response_model=OpenSearchStatus)
async def opensearch_status():
    """Check OpenSearch connectivity and index statistics."""
    if not is_opensearch_enabled():
        return OpenSearchStatus(enabled=False)

    try:
        import asyncio

        from open_notebook.config import OPENSEARCH_INDEX
        from open_notebook.search.client import get_client

        client = await get_client()

        # Health check
        info = await asyncio.to_thread(client.info)
        version = info.get("version", {}).get("number", "unknown")

        # Check index
        index_exists = await asyncio.to_thread(
            client.indices.exists, index=OPENSEARCH_INDEX
        )

        doc_count = 0
        if index_exists:
            stats = await asyncio.to_thread(
                client.count, index=OPENSEARCH_INDEX
            )
            doc_count = stats.get("count", 0)

        return OpenSearchStatus(
            enabled=True,
            healthy=True,
            version=version,
            index_exists=index_exists,
            doc_count=doc_count,
        )

    except Exception as e:
        logger.warning(f"OpenSearch status check failed: {e}")
        return OpenSearchStatus(
            enabled=True,
            healthy=False,
            error=str(e),
        )
