"""
Navy Corpus Document Listing & Search.

Queries the pre-indexed navy document corpus in OpenSearch
(the same cluster used by NOVA-Researcher) to:
  1. List all unique documents (terms aggregation on doc_id).
  2. Search within selected documents using BM25 text search.
  3. Index newly uploaded documents so they appear alongside the
     pre-indexed corpus.

The navy index uses BAAI/bge-m3 embeddings but we intentionally
use BM25 for chat context retrieval to avoid loading the heavy
embedding model in the open-notebook process.
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.config import NAVY_OPENSEARCH_INDEX
from open_notebook.search.client import get_client


async def list_navy_documents() -> List[Dict[str, Any]]:
    """Return all unique documents in the navy corpus index.

    Each item contains:
        - doc_id: str
        - chunk_count: int  (number of chunks/passages)
    """
    try:
        client = await get_client()

        body: Dict[str, Any] = {
            "size": 0,
            "aggs": {
                "unique_docs": {
                    "terms": {
                        "field": "doc_id",
                        "size": 10000,
                    },
                    "aggs": {
                        "sample_source": {
                            "top_hits": {
                                "size": 1,
                                "_source": ["source", "section_title", "page_start"],
                            }
                        }
                    },
                }
            },
        }

        response = await asyncio.to_thread(
            client.search, index=NAVY_OPENSEARCH_INDEX, body=body
        )

        buckets = response.get("aggregations", {}).get("unique_docs", {}).get("buckets", [])

        documents = []
        for bucket in buckets:
            doc_id = bucket["key"]
            chunk_count = bucket["doc_count"]

            # Extract a sample hit for extra metadata
            sample_hits = bucket.get("sample_source", {}).get("hits", {}).get("hits", [])
            sample = sample_hits[0]["_source"] if sample_hits else {}

            documents.append({
                "doc_id": doc_id,
                "chunk_count": chunk_count,
                "source": sample.get("source", ""),
                "sample_section": sample.get("section_title", ""),
            })

        logger.info(f"Listed {len(documents)} documents from navy corpus index '{NAVY_OPENSEARCH_INDEX}'")
        return documents

    except Exception as e:
        logger.error(f"Failed to list navy documents: {e}")
        raise


async def search_navy_documents(
    query: str,
    doc_ids: Optional[List[str]] = None,
    k: int = 10,
) -> List[Dict[str, Any]]:
    """BM25 text search on the navy corpus, optionally filtered by doc_ids.

    Returns a list of dicts with:
        - doc_id, content, source, section_title, page_start, page_end, score
    """
    try:
        client = await get_client()

        must_clause: List[Dict[str, Any]] = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["content^1", "section_title^2"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            }
        ]

        filter_clause: List[Dict[str, Any]] = []
        if doc_ids:
            filter_clause.append({"terms": {"doc_id": doc_ids}})

        body: Dict[str, Any] = {
            "size": k,
            "query": {
                "bool": {
                    "must": must_clause,
                    "filter": filter_clause,
                }
            },
            "_source": [
                "doc_id",
                "content",
                "source",
                "section_title",
                "page_start",
                "page_end",
            ],
        }

        response = await asyncio.to_thread(
            client.search, index=NAVY_OPENSEARCH_INDEX, body=body
        )

        hits = response.get("hits", {}).get("hits", [])
        results = []
        for hit in hits:
            src = hit.get("_source", {})
            results.append({
                "doc_id": src.get("doc_id", ""),
                "content": src.get("content", ""),
                "source": src.get("source", ""),
                "section_title": src.get("section_title", ""),
                "page_start": src.get("page_start"),
                "page_end": src.get("page_end"),
                "score": hit.get("_score", 0),
            })

        return results

    except Exception as e:
        logger.error(f"Navy document search failed: {e}")
        raise


async def vector_search_navy_documents(
    query: str,
    doc_ids: Optional[List[str]] = None,
    k: int = 5,
    min_score: float = 0.0,
) -> List[Dict[str, Any]]:
    """Semantic kNN search on the navy corpus using BGE-M3 embeddings.

    The navy index stores BAAI/bge-m3 embeddings in the ``embedding`` field.
    The query is embedded with the configured embedding model (which must
    also be BGE-M3 for the vectors to be comparable) and matched against
    those vectors via the OpenSearch k-NN plugin.

    Returns the same fields as :func:`search_navy_documents`.
    """
    try:
        # Lazy import to keep this module importable when the embedding
        # stack (and its model dependencies) is not yet initialised.
        from open_notebook.utils.embedding import generate_embedding

        embedding = await generate_embedding(query)
        if not embedding:
            logger.warning(
                "Navy vector search: empty embedding for query, "
                "falling back to BM25"
            )
            return await search_navy_documents(query, doc_ids=doc_ids, k=k)

        client = await get_client()

        knn_clause: Dict[str, Any] = {
            "vector": embedding,
            "k": max(k, 1),
        }
        if doc_ids:
            knn_clause["filter"] = {"terms": {"doc_id": doc_ids}}

        body: Dict[str, Any] = {
            "size": k,
            "query": {"knn": {"embedding": knn_clause}},
            "_source": [
                "doc_id",
                "content",
                "source",
                "section_title",
                "page_start",
                "page_end",
            ],
        }
        if min_score > 0:
            body["min_score"] = min_score

        response = await asyncio.to_thread(
            client.search, index=NAVY_OPENSEARCH_INDEX, body=body
        )

        hits = response.get("hits", {}).get("hits", [])
        results = []
        for hit in hits:
            src = hit.get("_source", {})
            results.append({
                "doc_id": src.get("doc_id", ""),
                "content": src.get("content", ""),
                "source": src.get("source", ""),
                "section_title": src.get("section_title", ""),
                "page_start": src.get("page_start"),
                "page_end": src.get("page_end"),
                "score": hit.get("_score", 0),
            })
        return results

    except Exception as e:
        logger.error(f"Navy vector search failed, falling back to BM25: {e}")
        return await search_navy_documents(query, doc_ids=doc_ids, k=k)


# ---------------------------------------------------------------------------
# Indexing helpers — write uploaded documents into the navy corpus index
# ---------------------------------------------------------------------------

def _slugify(title: str) -> str:
    """Create a simple doc_id slug from a source title."""
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "_", slug).strip("_")
    return slug or "untitled"


async def navy_index_source(
    source_id: str,
    source_title: str,
    chunks: List[str],
    *,
    embeddings: Optional[List[List[float]]] = None,
) -> int:
    """Index a newly-uploaded source into the navy corpus OpenSearch index.

    Each chunk becomes a document in the navy index with the same schema as
    the pre-indexed corpus:
        doc_id, content, section_title, source, page_start, page_end, embedding

    Parameters
    ----------
    source_id : str
        SurrealDB record id (e.g. ``source:xyz``).
    source_title : str
        Human-readable title of the source.
    chunks : list[str]
        Ordered text chunks produced by the app's chunking pipeline.
    embeddings : list[list[float]], optional
        Pre-computed embeddings (must match chunk count).  When ``None``
        the documents are indexed *without* the embedding field so that
        they are still discoverable via BM25.

    Returns
    -------
    int
        Number of chunks successfully indexed.
    """
    if not chunks:
        return 0

    doc_id = _slugify(source_title)
    client = await get_client()

    # Build bulk request body (NDJSON: action + doc pairs)
    bulk_body = ""
    for idx, chunk in enumerate(chunks):
        action = {"index": {"_index": NAVY_OPENSEARCH_INDEX}}
        doc: Dict[str, Any] = {
            "doc_id": doc_id,
            "content": chunk,
            "section_title": f"Chunk {idx + 1}",
            "source": source_title,
            "page_start": idx + 1,
            "page_end": idx + 1,
        }
        if embeddings and idx < len(embeddings):
            doc["embedding"] = embeddings[idx]

        bulk_body += json.dumps(action) + "\n" + json.dumps(doc) + "\n"

    response = await asyncio.to_thread(
        client.bulk, body=bulk_body, refresh=True,
    )

    errors = response.get("errors", False)
    items = response.get("items", [])
    success_count = sum(
        1
        for item in items
        if item.get("index", {}).get("status", 999) < 300
    )

    if errors:
        failed = [
            item for item in items
            if item.get("index", {}).get("status", 999) >= 300
        ]
        logger.warning(
            f"Navy index: {len(failed)}/{len(items)} chunks failed for "
            f"source '{source_title}' (doc_id={doc_id})"
        )

    logger.info(
        f"Navy index: indexed {success_count}/{len(chunks)} chunks for "
        f"source '{source_title}' (doc_id={doc_id})"
    )
    return success_count


async def navy_delete_source(source_title: str) -> int:
    """Delete all chunks for a source from the navy index (by doc_id slug).

    Returns the number of deleted documents.
    """
    doc_id = _slugify(source_title)
    try:
        client = await get_client()
        body = {"query": {"term": {"doc_id": doc_id}}}
        response = await asyncio.to_thread(
            client.delete_by_query,
            index=NAVY_OPENSEARCH_INDEX,
            body=body,
            refresh=True,
        )
        deleted = response.get("deleted", 0)
        logger.info(
            f"Navy index: deleted {deleted} chunks for doc_id={doc_id}"
        )
        return deleted
    except Exception as e:
        logger.warning(f"Navy index delete failed for doc_id={doc_id}: {e}")
        return 0
