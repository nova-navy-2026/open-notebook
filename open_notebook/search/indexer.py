"""
OpenSearch index management and document indexing.

Handles:
- Lazy index creation with auto-detected embedding dimension
- Single-document and bulk indexing
- Deletion by document ID or parent ID
- High-level sync helpers for embedding commands (dual-write)
"""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.config import OPENSEARCH_INDEX
from open_notebook.search import is_opensearch_enabled
from open_notebook.search.client import get_client

# Module-level cache to avoid redundant index-existence checks
_index_exists = False
_index_dimension: Optional[int] = None


def _build_index_mapping(dimension: int) -> Dict[str, Any]:
    """Build the OpenSearch index mapping with k-NN vector support."""
    return {
        "settings": {
            "index": {
                "knn": True,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
        },
        "mappings": {
            "properties": {
                "doc_type": {"type": "keyword"},
                "parent_id": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "standard",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 256},
                    },
                },
                "content": {"type": "text", "analyzer": "standard"},
                "insight_type": {"type": "keyword"},
                "owner": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {
                            "ef_construction": 256,
                            "m": 48,
                        },
                    },
                },
                "chunk_order": {"type": "integer"},
            },
        },
    }


# ---------------------------------------------------------------------------
# Index lifecycle
# ---------------------------------------------------------------------------

async def ensure_index(dimension: int) -> bool:
    """Create the OpenSearch index if it does not exist.

    Returns True if the index is ready, False on error or dimension mismatch.
    """
    global _index_exists, _index_dimension

    if _index_exists and _index_dimension == dimension:
        return True

    try:
        client = await get_client()

        exists = await asyncio.to_thread(
            client.indices.exists, index=OPENSEARCH_INDEX
        )

        if not exists:
            mapping = _build_index_mapping(dimension)
            await asyncio.to_thread(
                client.indices.create,
                index=OPENSEARCH_INDEX,
                body=mapping,
            )
            logger.info(
                f"Created OpenSearch index '{OPENSEARCH_INDEX}' "
                f"(dimension={dimension})"
            )
        else:
            # Verify dimension compatibility
            current_mapping = await asyncio.to_thread(
                client.indices.get_mapping, index=OPENSEARCH_INDEX
            )
            props = (
                current_mapping.get(OPENSEARCH_INDEX, {})
                .get("mappings", {})
                .get("properties", {})
            )
            existing_dim = props.get("embedding", {}).get("dimension")
            if existing_dim and existing_dim != dimension:
                logger.warning(
                    f"OpenSearch index dimension mismatch: "
                    f"index has {existing_dim}, model produces {dimension}. "
                    f"Run the reindex_opensearch command to recreate the index."
                )
                return False

        _index_exists = True
        _index_dimension = dimension
        return True

    except Exception as e:
        logger.error(f"Failed to ensure OpenSearch index: {e}")
        return False


async def delete_index() -> bool:
    """Delete the entire OpenSearch index (used during reindex)."""
    global _index_exists, _index_dimension

    try:
        client = await get_client()
        exists = await asyncio.to_thread(
            client.indices.exists, index=OPENSEARCH_INDEX
        )
        if exists:
            await asyncio.to_thread(
                client.indices.delete, index=OPENSEARCH_INDEX
            )
            logger.info(f"Deleted OpenSearch index '{OPENSEARCH_INDEX}'")

        _index_exists = False
        _index_dimension = None
        return True

    except Exception as e:
        logger.error(f"Failed to delete OpenSearch index: {e}")
        return False


async def refresh_index() -> bool:
    """Force-refresh the index so recently indexed docs become searchable."""
    try:
        client = await get_client()
        await asyncio.to_thread(
            client.indices.refresh, index=OPENSEARCH_INDEX
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to refresh OpenSearch index: {e}")
        return False


# ---------------------------------------------------------------------------
# Document operations
# ---------------------------------------------------------------------------

async def index_document(
    doc_id: str,
    doc_type: str,
    parent_id: str,
    title: Optional[str],
    content: str,
    embedding: List[float],
    owner: Optional[str] = None,
    insight_type: Optional[str] = None,
    chunk_order: Optional[int] = None,
) -> bool:
    """Index a single document into OpenSearch (upsert by doc_id)."""
    if not is_opensearch_enabled():
        return True

    try:
        dimension = len(embedding)
        if not await ensure_index(dimension):
            return False

        client = await get_client()

        body: Dict[str, Any] = {
            "doc_type": doc_type,
            "parent_id": parent_id,
            "title": title or "",
            "content": content,
            "embedding": embedding,
        }
        if owner:
            body["owner"] = owner
        if insight_type:
            body["insight_type"] = insight_type
        if chunk_order is not None:
            body["chunk_order"] = chunk_order

        await asyncio.to_thread(
            client.index,
            index=OPENSEARCH_INDEX,
            id=doc_id,
            body=body,
            refresh=False,
        )
        return True

    except Exception as e:
        logger.warning(f"Failed to index document {doc_id} into OpenSearch: {e}")
        return False


async def delete_by_parent(parent_id: str) -> bool:
    """Delete all documents that belong to a given parent (source, note)."""
    if not is_opensearch_enabled():
        return True

    try:
        client = await get_client()
        exists = await asyncio.to_thread(
            client.indices.exists, index=OPENSEARCH_INDEX
        )
        if not exists:
            return True

        await asyncio.to_thread(
            client.delete_by_query,
            index=OPENSEARCH_INDEX,
            body={"query": {"term": {"parent_id": parent_id}}},
            refresh=False,
        )
        return True

    except Exception as e:
        logger.warning(
            f"Failed to delete OpenSearch docs for parent {parent_id}: {e}"
        )
        return False


async def delete_document(doc_id: str) -> bool:
    """Delete a single document from OpenSearch."""
    if not is_opensearch_enabled():
        return True

    try:
        client = await get_client()
        await asyncio.to_thread(
            client.delete,
            index=OPENSEARCH_INDEX,
            id=doc_id,
            ignore=[404],
        )
        return True

    except Exception as e:
        logger.warning(f"Failed to delete document {doc_id} from OpenSearch: {e}")
        return False


async def bulk_index(documents: List[Dict[str, Any]]) -> int:
    """Bulk-index documents into OpenSearch.

    Each dict must contain: doc_id, doc_type, parent_id, content, embedding.
    Optional keys: title, owner, insight_type, chunk_order.

    Returns the number of successfully indexed documents.
    """
    if not documents:
        return 0

    if not is_opensearch_enabled():
        return len(documents)

    try:
        dimension = len(documents[0]["embedding"])
        if not await ensure_index(dimension):
            return 0

        client = await get_client()

        # Build bulk request body (action + source pairs)
        actions: List[Any] = []
        for doc in documents:
            actions.append(
                {"index": {"_index": OPENSEARCH_INDEX, "_id": doc["doc_id"]}}
            )
            body: Dict[str, Any] = {
                "doc_type": doc["doc_type"],
                "parent_id": doc["parent_id"],
                "title": doc.get("title", ""),
                "content": doc["content"],
                "embedding": doc["embedding"],
            }
            if doc.get("owner"):
                body["owner"] = doc["owner"]
            if doc.get("insight_type"):
                body["insight_type"] = doc["insight_type"]
            if doc.get("chunk_order") is not None:
                body["chunk_order"] = doc["chunk_order"]
            actions.append(body)

        # Execute in batches of 500 documents (1000 action lines)
        batch_size = 500
        indexed = 0

        for i in range(0, len(actions), batch_size * 2):
            batch = actions[i : i + batch_size * 2]
            result = await asyncio.to_thread(
                client.bulk, body=batch, refresh=False
            )
            if not result.get("errors"):
                indexed += len(batch) // 2
            else:
                for item in result.get("items", []):
                    status = item.get("index", {}).get("status")
                    if status in (200, 201):
                        indexed += 1
                    else:
                        error = item.get("index", {}).get("error", {})
                        logger.warning(f"Bulk index error: {error}")

        return indexed

    except Exception as e:
        logger.error(f"Failed to bulk index into OpenSearch: {e}")
        return 0


# ---------------------------------------------------------------------------
# High-level sync helpers (called by embedding commands for dual-write)
# ---------------------------------------------------------------------------

async def sync_source_embeddings(
    source_id: str,
    source_title: Optional[str],
    chunks: List[Dict[str, Any]],
    owner: Optional[str] = None,
) -> int:
    """Sync source embedding chunks to OpenSearch.

    Deletes old entries for this source, then bulk-indexes the new chunks.
    Each chunk dict should have: id, content, embedding, order.

    Returns the count of successfully indexed documents.
    """
    if not is_opensearch_enabled():
        return 0

    try:
        await delete_by_parent(source_id)

        docs = [
            {
                "doc_id": str(chunk["id"]),
                "doc_type": "source_embedding",
                "parent_id": source_id,
                "title": source_title or "",
                "content": chunk["content"],
                "embedding": chunk["embedding"],
                "owner": owner,
                "chunk_order": chunk.get("order"),
            }
            for chunk in chunks
        ]
        return await bulk_index(docs)

    except Exception as e:
        logger.warning(f"Failed to sync source embeddings to OpenSearch: {e}")
        return 0


async def sync_note(
    note_id: str,
    title: Optional[str],
    content: str,
    embedding: List[float],
    owner: Optional[str] = None,
) -> bool:
    """Sync a note embedding to OpenSearch (upsert)."""
    if not is_opensearch_enabled():
        return True

    return await index_document(
        doc_id=note_id,
        doc_type="note",
        parent_id=note_id,
        title=title,
        content=content,
        embedding=embedding,
        owner=owner,
    )


async def sync_insight(
    insight_id: str,
    source_id: str,
    source_title: Optional[str],
    insight_type: str,
    content: str,
    embedding: List[float],
    owner: Optional[str] = None,
) -> bool:
    """Sync a source insight embedding to OpenSearch (upsert)."""
    if not is_opensearch_enabled():
        return True

    return await index_document(
        doc_id=insight_id,
        doc_type="source_insight",
        parent_id=source_id,
        title=f"{insight_type} - {source_title or ''}",
        content=content,
        embedding=embedding,
        owner=owner,
        insight_type=insight_type,
    )
