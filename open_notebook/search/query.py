"""
OpenSearch search query implementations.

Provides text (BM25), vector (k-NN), and hybrid (RRF) search,
returning results in the same format as SurrealDB fn::text_search
and fn::vector_search so the rest of the app is unaffected.

Result format (per item):
    {id, parent_id, title, similarity, relevance, matches}
"""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.access_control import (
    ACCESS_SCOPE_FIELD,
    CLASSIFICATION_FIELD,
    STATUS_FIELD,
    build_opensearch_filter,
)
from open_notebook.config import OPENSEARCH_INDEX
from open_notebook.search.client import get_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_INDEX_FIELDS_CACHE: Optional[set[str]] = None


async def _get_index_fields(client: Any) -> set[str]:
    """Return top-level mapped fields for the configured OpenSearch index."""
    global _INDEX_FIELDS_CACHE
    if _INDEX_FIELDS_CACHE is not None:
        return _INDEX_FIELDS_CACHE
    try:
        mapping = await asyncio.to_thread(
            client.indices.get_mapping, index=OPENSEARCH_INDEX
        )
        props = (
            mapping.get(OPENSEARCH_INDEX, {})
            .get("mappings", {})
            .get("properties", {})
        )
        _INDEX_FIELDS_CACHE = set(props.keys())
    except Exception as exc:
        logger.warning(f"Could not inspect OpenSearch mapping: {exc}")
        _INDEX_FIELDS_CACHE = set()
    return _INDEX_FIELDS_CACHE


def _build_type_filter(
    source: bool, note: bool, index_fields: set[str]
) -> List[Dict[str, Any]]:
    """Build a doc_type terms filter clause."""
    if "doc_type" not in index_fields:
        # Index has no doc_type at all → every row is a navy/source document.
        if source:
            return []
        return [{"bool": {"must_not": {"match_all": {}}}}]

    types: List[str] = []
    if source:
        types.extend(["source_embedding", "source_insight", "pdf"])
    if note:
        types.append("note")
    if not types:
        return []

    # The navy corpus rows have NO ``doc_type`` field (only the few user-content
    # docs do). A plain ``terms`` filter would therefore exclude ALL navy
    # documents. Since navy rows are documents, include "doc_type missing" in
    # source searches so the 54k+ navy files are searchable. Note-only searches
    # keep matching just ``doc_type: note`` (navy files are not notes).
    should: List[Dict[str, Any]] = [{"terms": {"doc_type": types}}]
    if source:
        should.append({"bool": {"must_not": {"exists": {"field": "doc_type"}}}})

    return [{"bool": {"should": should, "minimum_should_match": 1}}]


def _build_acl_filter(user_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the mandatory navy ACL filter for OpenSearch-backed search."""
    return build_opensearch_filter(user_id)


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
        source_name = src.get("document_name") or src.get("source")
        is_navy = bool(
            doc_id
            or src.get("document_name")
            or src.get(STATUS_FIELD)
            or src.get(CLASSIFICATION_FIELD) is not None
            or src.get(ACCESS_SCOPE_FIELD)
        )

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
            content = src.get("parent_content") or src.get("content", "")
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
        file_path = src.get("document_path") or src.get("file_path")
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
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """BM25 full-text search on *content* and *title* fields.

    Returns results in the SurrealDB ``fn::text_search`` format. When
    ``parent_ids`` is provided, only chunks whose ``parent_id`` is in the
    given list are considered (used for RAG over a fixed set of sources).

    ``user_id`` is the navy ACL identity used to filter access-controlled
    documents; when omitted such documents are excluded (fail closed).
    """
    try:
        client = await get_client()
        index_fields = await _get_index_fields(client)
        filters = _build_type_filter(source, note, index_fields)
        if parent_ids:
            filters = list(filters) + [{"terms": {"parent_id": parent_ids}}]
        acl = _build_acl_filter(user_id)
        if acl is not None:
            filters = list(filters) + [acl]

        body: Dict[str, Any] = {
            "size": results * 3,  # over-fetch for deduplication
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": keyword,
                                "fields": [
                                    "document_name^3",
                                    "title^2",
                                    "section_title^2",
                                    "source^2",
                                    "content",
                                ],
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
                "chunk_id",
                "section_title",
                "source",
                "document_name",
                "document_path",
                "document_type",
                "document_status",
                "access_scope",
                "classification_level",
                "creator_department",
                "page_start",
                "page_end",
                "parent_content",
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
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Approximate nearest-neighbour search using the k-NN plugin.

    Returns results in the SurrealDB ``fn::vector_search`` format. When
    ``parent_ids`` is provided, restricts matches to chunks whose
    ``parent_id`` is in the given list.

    ``user_id`` is the navy ACL identity used to filter access-controlled
    documents; when omitted such documents are excluded (fail closed).
    """
    try:
        client = await get_client()
        index_fields = await _get_index_fields(client)
        filters = _build_type_filter(source, note, index_fields)
        if parent_ids:
            filters = list(filters) + [{"terms": {"parent_id": parent_ids}}]
        acl = _build_acl_filter(user_id)
        if acl is not None:
            filters = list(filters) + [acl]

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
                "chunk_id",
                "section_title",
                "source",
                "document_name",
                "document_path",
                "document_type",
                "document_status",
                "access_scope",
                "classification_level",
                "creator_department",
                "page_start",
                "page_end",
                "parent_content",
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
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Run BM25 and k-NN in parallel, merge via Reciprocal Rank Fusion.

    RRF produces a single ranked list that benefits from both lexical
    matching and semantic similarity.

    Returns results in the SurrealDB search-result format.
    """
    try:
        # Run both searches concurrently
        text_task = opensearch_text_search(
            keyword, results, source, note, parent_ids=parent_ids, user_id=user_id
        )
        vector_task = opensearch_vector_search(
            embedding, results, source, note, min_score,
            parent_ids=parent_ids, user_id=user_id,
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
            key = result.get("parent_id") or result["id"]
            if key not in scores:
                scores[key] = {**result, "_rrf": 0.0}
            scores[key]["_rrf"] += bm25_weight / (k + rank + 1)

        for rank, result in enumerate(vector_results):
            key = result.get("parent_id") or result["id"]
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
