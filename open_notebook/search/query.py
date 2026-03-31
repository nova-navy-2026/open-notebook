"""
OpenSearch search query implementations.

Provides text (BM25), vector (k-NN), and hybrid (RRF) search,
returning results in the same format as SurrealDB fn::text_search
and fn::vector_search so the rest of the app is unaffected.

Result format (per item):
    {id, parent_id, title, similarity, relevance, matches}
"""

import asyncio
from typing import Any, Dict, List

from loguru import logger

from open_notebook.config import OPENSEARCH_INDEX
from open_notebook.search.client import get_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_type_filter(
    source: bool, note: bool
) -> List[Dict[str, Any]]:
    """Build a doc_type terms filter clause."""
    types: List[str] = []
    if source:
        types.extend(["source_embedding", "source_insight"])
    if note:
        types.append("note")
    if not types:
        return []
    return [{"terms": {"doc_type": types}}]


def _normalize_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert raw OpenSearch hits to the SurrealDB result format."""
    results = []
    for hit in hits:
        src = hit.get("_source", {})
        score = hit.get("_score", 0)
        results.append(
            {
                "id": hit.get("_id", ""),
                "parent_id": src.get("parent_id", ""),
                "title": src.get("title", ""),
                "similarity": score,
                "relevance": score,
                "matches": [src.get("content", "")],
            }
        )
    return results


def _deduplicate_by_parent(
    results: List[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """Group by (id, parent_id) keeping the highest score.

    Mirrors the ``GROUP BY id, parent_id, title`` in SurrealDB's
    ``fn::vector_search``.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for r in results:
        key = f"{r['id']}_{r['parent_id']}"
        if key not in seen or r.get("similarity", 0) > seen[key].get("similarity", 0):
            seen[key] = r
    deduped = sorted(
        seen.values(), key=lambda x: x.get("similarity", 0), reverse=True
    )
    return deduped[:limit]


# ---------------------------------------------------------------------------
# Text search (BM25)
# ---------------------------------------------------------------------------

async def opensearch_text_search(
    keyword: str,
    results: int = 100,
    source: bool = True,
    note: bool = True,
) -> List[Dict[str, Any]]:
    """BM25 full-text search on *content* and *title* fields.

    Returns results in the SurrealDB ``fn::text_search`` format.
    """
    try:
        client = await get_client()
        filters = _build_type_filter(source, note)

        body: Dict[str, Any] = {
            "size": results * 3,  # over-fetch for deduplication
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": keyword,
                                "fields": ["title^2", "content"],
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "_source": [
                "doc_type",
                "parent_id",
                "title",
                "content",
                "insight_type",
            ],
        }

        response = await asyncio.to_thread(
            client.search, index=OPENSEARCH_INDEX, body=body
        )
        hits = response.get("hits", {}).get("hits", [])
        normalized = _normalize_hits(hits)
        return _deduplicate_by_parent(normalized, results)

    except Exception as e:
        logger.error(f"OpenSearch text search failed: {e}")
        raise


# ---------------------------------------------------------------------------
# Vector search (k-NN)
# ---------------------------------------------------------------------------

async def opensearch_vector_search(
    embedding: List[float],
    results: int = 100,
    source: bool = True,
    note: bool = True,
    min_score: float = 0.2,
) -> List[Dict[str, Any]]:
    """Approximate nearest-neighbour search using the k-NN plugin.

    Returns results in the SurrealDB ``fn::vector_search`` format.
    """
    try:
        client = await get_client()
        filters = _build_type_filter(source, note)

        # k-NN 'k' must be <= 10000 and >= 1
        k_value = min(max(results * 3, 1), 10000)

        body: Dict[str, Any] = {
            "size": results * 3,
            "query": {
                "bool": {
                    "must": [
                        {
                            "knn": {
                                "embedding": {
                                    "vector": embedding,
                                    "k": k_value,
                                }
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "min_score": min_score,
            "_source": [
                "doc_type",
                "parent_id",
                "title",
                "content",
                "insight_type",
            ],
        }

        response = await asyncio.to_thread(
            client.search, index=OPENSEARCH_INDEX, body=body
        )
        hits = response.get("hits", {}).get("hits", [])
        normalized = _normalize_hits(hits)
        return _deduplicate_by_parent(normalized, results)

    except Exception as e:
        logger.error(f"OpenSearch vector search failed: {e}")
        raise


# ---------------------------------------------------------------------------
# Hybrid search (BM25 + k-NN via Reciprocal Rank Fusion)
# ---------------------------------------------------------------------------

async def opensearch_hybrid_search(
    keyword: str,
    embedding: List[float],
    results: int = 100,
    source: bool = True,
    note: bool = True,
    min_score: float = 0.2,
    bm25_weight: float = 0.3,
    vector_weight: float = 0.7,
) -> List[Dict[str, Any]]:
    """Run BM25 and k-NN in parallel, merge via Reciprocal Rank Fusion.

    RRF produces a single ranked list that benefits from both lexical
    matching and semantic similarity.

    Returns results in the SurrealDB search-result format.
    """
    try:
        # Run both searches concurrently
        text_task = opensearch_text_search(keyword, results, source, note)
        vector_task = opensearch_vector_search(
            embedding, results, source, note, min_score
        )
        text_results, vector_results = await asyncio.gather(
            text_task, vector_task, return_exceptions=True
        )

        # Handle partial failures gracefully
        if isinstance(text_results, Exception):
            logger.warning(f"Hybrid search: BM25 leg failed: {text_results}")
            text_results = []
        if isinstance(vector_results, Exception):
            logger.warning(f"Hybrid search: k-NN leg failed: {vector_results}")
            vector_results = []

        if not text_results and not vector_results:
            return []
        if not text_results:
            return vector_results  # type: ignore[return-value]
        if not vector_results:
            return text_results  # type: ignore[return-value]

        # Reciprocal Rank Fusion
        k = 60  # RRF smoothing constant
        scores: Dict[str, Dict[str, Any]] = {}

        for rank, result in enumerate(text_results):
            key = result["id"]
            if key not in scores:
                scores[key] = {**result, "_rrf": 0.0}
            scores[key]["_rrf"] += bm25_weight / (k + rank + 1)

        for rank, result in enumerate(vector_results):
            key = result["id"]
            if key not in scores:
                scores[key] = {**result, "_rrf": 0.0}
            scores[key]["_rrf"] += vector_weight / (k + rank + 1)

        # Sort by RRF score, normalise to 0-1
        merged = sorted(scores.values(), key=lambda x: x["_rrf"], reverse=True)
        max_score = merged[0]["_rrf"] if merged else 1.0

        for item in merged:
            normalised = item["_rrf"] / max_score if max_score > 0 else 0.0
            item["similarity"] = normalised
            item["relevance"] = normalised
            del item["_rrf"]

        return merged[:results]

    except Exception as e:
        logger.error(f"OpenSearch hybrid search failed: {e}")
        raise
