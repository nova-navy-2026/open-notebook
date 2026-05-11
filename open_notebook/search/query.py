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
        types.extend(["source_embedding", "source_insight", "pdf"])
    if note:
        types.append("note")
    if not types:
        return []
    return [{"terms": {"doc_type": types}}]


def _normalize_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert raw OpenSearch hits to the SurrealDB result format.

    Handles both Open Notebook documents (``parent_id`` + ``title``) and Navy
    PDF documents (``doc_id`` + ``section_title`` + ``source``). For Navy
    rows the document-level identity is the *file* (``source`` field) keyed
    by ``doc_id``; ``section_title`` is chunk-level metadata that goes into
    ``matches`` instead of the result title.
    """
    results = []
    for hit in hits:
        src = hit.get("_source", {})
        score = hit.get("_score", 0)

        parent_id_raw = src.get("parent_id")
        doc_id = src.get("doc_id")
        section_title = src.get("section_title")
        source_name = src.get("source")
        is_navy = not parent_id_raw and (doc_id or section_title or source_name)

        if is_navy:
            # Use a stable prefixed key so the frontend's "type:id" split works
            # and so we never collide with native open-notebook parent IDs.
            parent_id = f"navy:{doc_id or source_name or hit.get('_id', '')}"
            # Document-level title = filename / source. Fall back to section
            # title only when no source is recorded.
            title = source_name or section_title or "Untitled document"
            # Chunk-level descriptor for the matches accordion.
            page_start = src.get("page_start")
            page_end = src.get("page_end")
            chunk_label_parts: List[str] = []
            if section_title:
                chunk_label_parts.append(str(section_title))
            if page_start is not None or page_end is not None:
                if page_start == page_end or page_end is None:
                    chunk_label_parts.append(f"p. {page_start}")
                else:
                    chunk_label_parts.append(f"pp. {page_start}-{page_end}")
            chunk_prefix = " · ".join(chunk_label_parts)
            content = src.get("content", "")
            match_text = (
                f"[{chunk_prefix}] {content}" if chunk_prefix else content
            )
        else:
            parent_id = parent_id_raw or ""
            title = src.get("title") or section_title or source_name or ""
            match_text = src.get("content", "")

        item: Dict[str, Any] = {
            "id": hit.get("_id", ""),
            "parent_id": parent_id,
            "title": title,
            "similarity": score,
            "relevance": score,
            "matches": [match_text] if match_text else [],
        }
        file_path = src.get("file_path")
        if file_path:
            item["file_path"] = file_path
        results.append(item)
    return results


def _deduplicate_by_parent(
    results: List[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """Group by parent_id (the actual document) keeping the highest score.

    Chunks from the same document are collapsed into a single result entry,
    with all distinct matches collected under the ``matches`` list and the
    highest score from any chunk used as the document score.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for r in results:
        key = r.get("parent_id") or r.get("id", "")
        if key not in seen:
            seen[key] = {**r, "matches": list(r.get("matches") or [])}
        else:
            existing = seen[key]
            # Keep highest score
            if r.get("similarity", 0) > existing.get("similarity", 0):
                existing["similarity"] = r["similarity"]
                existing["relevance"] = r.get("relevance", r["similarity"])
            # Collect unique matches from this chunk
            for m in (r.get("matches") or []):
                if m and m not in existing["matches"]:
                    existing["matches"].append(m)
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
    parent_ids: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """BM25 full-text search on *content* and *title* fields.

    Returns results in the SurrealDB ``fn::text_search`` format. When
    ``parent_ids`` is provided, only chunks whose ``parent_id`` is in the
    given list are considered (used for RAG over a fixed set of sources).
    """
    try:
        client = await get_client()
        filters = _build_type_filter(source, note)
        if parent_ids:
            filters = list(filters) + [{"terms": {"parent_id": parent_ids}}]

        body: Dict[str, Any] = {
            "size": results * 3,  # over-fetch for deduplication
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": keyword,
                                "fields": ["title^2", "section_title^2", "source", "content"],
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
                # Navy PDF document fields
                "doc_id",
                "section_title",
                "source",
                "page_start",
                "page_end",
                # Shared file system path
                "file_path",
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
    parent_ids: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Approximate nearest-neighbour search using the k-NN plugin.

    Returns results in the SurrealDB ``fn::vector_search`` format. When
    ``parent_ids`` is provided, restricts matches to chunks whose
    ``parent_id`` is in the given list.
    """
    try:
        client = await get_client()
        filters = _build_type_filter(source, note)
        if parent_ids:
            filters = list(filters) + [{"terms": {"parent_id": parent_ids}}]

        # k-NN 'k' must be <= 10000 and >= 1
        k_value = min(max(results * 3, 1), 10000)

        # Build the knn clause. When filters are present we pass them via the
        # k-NN plugin's built-in "filter" parameter (efficient filtering) rather
        # than wrapping knn in a bool/must alongside a sibling bool/filter. The
        # latter pattern triggers an OpenSearch/Lucene bug:
        #   "Sub-iterators of ConjunctionDISI are not on the same document!"
        knn_clause: Dict[str, Any] = {
            "vector": embedding,
            "k": k_value,
        }
        if filters:
            knn_clause["filter"] = {"bool": {"filter": filters}}

        body: Dict[str, Any] = {
            "size": results * 3,
            "query": {"knn": {"embedding": knn_clause}},
            "min_score": min_score,
            "_source": [
                "doc_type",
                "parent_id",
                "title",
                "content",
                "insight_type",
                # Navy PDF document fields
                "doc_id",
                "section_title",
                "source",
                "page_start",
                "page_end",
                # Shared file system path
                "file_path",
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
    parent_ids: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Run BM25 and k-NN in parallel, merge via Reciprocal Rank Fusion.

    RRF produces a single ranked list that benefits from both lexical
    matching and semantic similarity.

    Returns results in the SurrealDB search-result format.
    """
    try:
        # Run both searches concurrently
        text_task = opensearch_text_search(
            keyword, results, source, note, parent_ids=parent_ids
        )
        vector_task = opensearch_vector_search(
            embedding, results, source, note, min_score, parent_ids=parent_ids
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
