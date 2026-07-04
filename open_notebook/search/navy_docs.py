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
import math
import re
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.config import NAVY_OPENSEARCH_INDEX
from open_notebook.search.client import get_client
from open_notebook.search.topics import (
    TOPIC_CLASS_FIELD,
    get_topic_class_ids,
    get_topic_color_map,
    get_topic_label_map,
)


async def _search_with_retry(
    client: Any,
    body: Dict[str, Any],
    *,
    retries: int = 3,
    base_delay: float = 0.25,
) -> Dict[str, Any]:
    """Run an OpenSearch ``search`` with retries on transient 5xx errors.

    The managed OpenSearch cluster occasionally returns a transient HTTP 500
    (e.g. ``security_exception: Unexpected exception``) when several workers
    hammer it at once during startup priming. These are not query or auth
    problems — the same request succeeds on retry — so we retry a few times
    with a short exponential backoff before giving up.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.to_thread(
                client.search, index=NAVY_OPENSEARCH_INDEX, body=body
            )
        except Exception as exc:  # noqa: BLE001 - inspected below
            status = getattr(exc, "status_code", None)
            transient = status is None or (isinstance(status, int) and status >= 500)
            if not transient or attempt == retries:
                raise
            last_exc = exc
            delay = base_delay * (2**attempt)
            logger.warning(
                f"Transient OpenSearch error on navy search "
                f"(attempt {attempt + 1}/{retries + 1}, retrying in {delay:.2f}s): {exc}"
            )
            await asyncio.sleep(delay)
    # Unreachable, but keeps type checkers happy.
    raise last_exc  # type: ignore[misc]


# In-process TTL cache for the navy documents listing. The corpus
# changes rarely (manual re-index), but every notebook/source page
# load asks for it, so caching avoids hitting OpenSearch with an
# expensive terms+top_hits aggregation on every navigation. The
# listing is ACL-filtered per user, so we key the cache by user_id
# (using the sentinel ``"__all__"`` when no ACL is applied).
_LIST_CACHE: Dict[str, Dict[str, Any]] = {}
_LIST_CACHE_TTL_SECONDS = 300.0  # 5 minutes
_LIST_CACHE_LOCK = asyncio.Lock()


def invalidate_navy_documents_cache() -> None:
    """Drop the cached navy documents listing (call after re-indexing)."""
    _LIST_CACHE.clear()


async def list_navy_documents(
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return all unique documents in the navy corpus index.

    Each item contains:
        - doc_id: str
        - chunk_count: int  (number of chunks/passages)

    When ``user_id`` is given, the navy access-control filter (clearance +
    department) is applied so the returned list only contains documents
    the user is allowed to see.

    Results are cached in-process per-user for ``_LIST_CACHE_TTL_SECONDS``
    to keep the sources view and notebook sidebar snappy.
    """
    cache_key = user_id or "__all__"
    now = time.monotonic()
    entry = _LIST_CACHE.get(cache_key)
    if entry is not None and now < entry["expires_at"]:
        return entry["data"]  # type: ignore[return-value]

    async with _LIST_CACHE_LOCK:
        # Re-check inside the lock so concurrent callers share one fetch.
        now = time.monotonic()
        entry = _LIST_CACHE.get(cache_key)
        if entry is not None and now < entry["expires_at"]:
            return entry["data"]  # type: ignore[return-value]

        documents = await _list_navy_documents_uncached(user_id=user_id)
        _LIST_CACHE[cache_key] = {
            "data": documents,
            "expires_at": time.monotonic() + _LIST_CACHE_TTL_SECONDS,
        }
        return documents


async def _list_navy_documents_uncached(
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    try:
        from open_notebook.access_control import (
            access_enabled,
            build_opensearch_filter,
        )

        if user_id is None and access_enabled():
            logger.debug("Skipping anonymous navy document listing (ACL enabled)")
            return []

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
                                "_source": [
                                    "source",
                                    "document_name",
                                    "document_path",
                                    "document_type",
                                    "document_status",
                                    "access_scope",
                                    "classification_level",
                                    "creator_department",
                                    "section_title",
                                    "page_start",
                                ],
                            }
                        }
                    },
                }
            },
        }

        # Apply navy access-control filter so the aggregation only considers
        # documents the user is allowed to see. Missing/unknown users fail
        # closed inside build_opensearch_filter.
        acl_filter = build_opensearch_filter(user_id)
        if acl_filter is not None:
            body["query"] = acl_filter

        response = await _search_with_retry(client, body)

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
                "source": sample.get("document_name") or sample.get("source", ""),
                "sample_section": sample.get("section_title", ""),
                # Governance metadata used by the UI to group the corpus
                # hierarchically (by department / classification / type).
                "document_type": sample.get("document_type") or "",
                "document_status": sample.get("document_status") or "",
                "access_scope": sample.get("access_scope") or "",
                "classification_level": sample.get("classification_level"),
                "creator_department": sample.get("creator_department") or "",
            })

        logger.info(
            f"Listed {len(documents)} documents from navy corpus index "
            f"'{NAVY_OPENSEARCH_INDEX}' (user_id={user_id!r})"
        )
        return documents

    except Exception as e:
        logger.error(f"Failed to list navy documents: {e}")
        raise


async def get_navy_document_content(
    doc_id: str,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch one navy document's full text + metadata from OpenSearch.

    ACL-enforced: returns ``None`` when the document does not exist OR the user
    is not allowed to read it (fail-closed for missing/unknown identities). The
    text is taken from the stored ``parent_content`` when present, otherwise it
    is stitched together from the document's de-duplicated chunks, ordered by
    page.
    """
    from open_notebook.access_control import access_enabled, build_opensearch_filter

    if not doc_id:
        return None
    if user_id is None and access_enabled():
        logger.debug("Skipping anonymous navy document content fetch (ACL enabled)")
        return None

    client = await get_client()

    query: Dict[str, Any] = {"bool": {"must": [{"term": {"doc_id": doc_id}}]}}
    # acl_filter is itself a bool clause (or None for admin / disabled ACL);
    # require it IN ADDITION to the doc_id so a user can only read documents at
    # or below their clearance.
    acl_filter = build_opensearch_filter(user_id)
    if acl_filter is not None:
        query["bool"]["filter"] = [acl_filter]

    body: Dict[str, Any] = {
        "size": 2000,  # generous upper bound on chunks per document
        "query": query,
        "_source": [
            "doc_id", "content", "parent_content", "section_title",
            "page_start", "page_end", "chunk_id",
            "document_name", "source", "document_type", "document_status",
            "access_scope", "classification_level", "creator_department",
            "document_path",
        ],
        "sort": [{"page_start": {"order": "asc", "missing": "_last"}}],
    }

    response = await _search_with_retry(client, body)
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        # Document doesn't exist, or the user can't access it (fail-closed).
        return None

    first = hits[0].get("_source", {})

    # Reassemble the WHOLE document. Each hit is one chunk; the index stores the
    # surrounding page/section text in ``parent_content``. Collect the DISTINCT
    # parent_content blocks (one per page/section) in page order — this rebuilds
    # the full document without the chunk-overlap repetition you'd get from
    # joining the small ``content`` chunks. Earlier this used only the FIRST
    # hit's parent_content, so only the cover page showed. Fall back to stitching
    # ``content`` chunks when no parent_content is present.
    ordered_parents: List[str] = []
    seen_parents: set = set()
    for h in hits:
        pc = (h.get("_source", {}).get("parent_content") or "").strip()
        if pc and pc not in seen_parents:
            seen_parents.add(pc)
            ordered_parents.append(pc)

    if ordered_parents:
        content = "\n\n".join(ordered_parents)
    else:
        parts: List[str] = []
        seen_chunks: set = set()
        for h in hits:
            src = h.get("_source", {})
            chunk = (src.get("content") or "").strip()
            if not chunk or chunk in seen_chunks:
                continue
            seen_chunks.add(chunk)
            section = (src.get("section_title") or "").strip()
            parts.append(f"## {section}\n\n{chunk}" if section else chunk)
        content = "\n\n".join(parts)

    logger.info(
        "Navy doc content {!r}: {} chunk hit(s), {} parent block(s), {} chars "
        "(user_id={!r})",
        doc_id,
        len(hits),
        len(ordered_parents),
        len(content),
        user_id,
    )

    title = (
        first.get("document_name")
        or first.get("source")
        or _pretty_doc_label(doc_id, first)
    )

    return {
        "doc_id": doc_id,
        "title": title,
        "content": content,
        "chunk_count": len(hits),
        "document_type": first.get("document_type") or "",
        "document_status": first.get("document_status") or "",
        "access_scope": first.get("access_scope") or "",
        "classification_level": first.get("classification_level"),
        "creator_department": first.get("creator_department") or "",
        "source": first.get("document_name") or first.get("source") or "",
    }


def _parent_sort_key(src: Dict[str, Any]) -> tuple:
    """Document-order sort key for a chunk hit.

    ``chunk_order`` is the child index WITHIN a parent (0..2), so document
    order must come from ``page_start`` with the ordinals embedded in
    ``parent_id`` (``{doc}_section_{s}_chunk_{c}``) as tiebreakers — parsed
    numerically, because a string sort misorders section_11 vs section_111.
    ``chunk_id`` (``{doc}_semantic_{n}``) is a last-resort global signal.
    """
    page = src.get("page_start")
    page_key = page if isinstance(page, (int, float)) else math.inf
    m = re.search(r"_section_(\d+)_chunk_(\d+)$", src.get("parent_id") or "")
    section_key = int(m.group(1)) if m else math.inf
    chunk_key = int(m.group(2)) if m else math.inf
    m2 = re.search(r"_semantic_(\d+)$", src.get("chunk_id") or "")
    semantic_key = int(m2.group(1)) if m2 else math.inf
    return (page_key, section_key, chunk_key, semantic_key)


def _longest_suffix_prefix(prev: str, nxt: str) -> int:
    """Length of the longest suffix of ``prev`` equal to a prefix of ``nxt``.

    Consecutive ``parent_content`` blocks share their neighbour text
    verbatim (block_i = P(i-1)+P(i)+P(i+1), block_i+1 = P(i)+P(i+1)+P(i+2)),
    so an exact match finds the seam. Failed comparisons bail on the first
    character, so the scan is cheap in practice.
    """
    max_len = min(len(prev), len(nxt))
    for length in range(max_len, 0, -1):
        if prev[-length:] == nxt[:length]:
            return length
    return 0


async def get_navy_document_segments(
    doc_id: str,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Reconstruct one navy document as clean text with offset metadata.

    Unlike :func:`get_navy_document_content` (which joins distinct
    ``parent_content`` blocks and therefore repeats the ±1-neighbour text the
    blocks share), this de-overlaps consecutive blocks via exact
    suffix/prefix matching, yielding text where each passage appears once —
    a requirement for character-offset highlighting in the citation viewer.

    Returns ``None`` when the document doesn't exist or the user can't read
    it (fail-closed, same ACL as ``get_navy_document_content``). Otherwise:

    - ``full_text``: the de-overlapped document text.
    - ``segments``: ``[{parent_id, section_title, page_start, page_end,
      char_start, char_end}]`` — the span each parent block contributed
      (display/scoping metadata; spans never overlap).
    - ``chunks``: ``[{chunk_id, parent_id, content, section_title,
      page_start, page_end}]`` — every child chunk, whose ``content`` is a
      verbatim substring of the document; callers anchor highlights by
      locating it in ``full_text``.
    """
    from open_notebook.access_control import access_enabled, build_opensearch_filter

    if not doc_id:
        return None
    if user_id is None and access_enabled():
        logger.debug("Skipping anonymous navy document segments fetch (ACL enabled)")
        return None

    client = await get_client()

    query: Dict[str, Any] = {"bool": {"must": [{"term": {"doc_id": doc_id}}]}}
    acl_filter = build_opensearch_filter(user_id)
    if acl_filter is not None:
        query["bool"]["filter"] = [acl_filter]

    body: Dict[str, Any] = {
        "size": 2000,  # generous upper bound on chunks per document
        "query": query,
        "_source": [
            "doc_id", "content", "parent_content", "section_title",
            "page_start", "page_end", "chunk_id", "parent_id", "chunk_order",
            "document_name", "source", "document_type", "document_status",
            "access_scope", "classification_level", "creator_department",
            "document_path",
        ],
    }

    response = await _search_with_retry(client, body)
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return None

    sources = sorted(
        (h.get("_source", {}) for h in hits), key=_parent_sort_key
    )
    first = sources[0]

    # Group child chunks under their parent, preserving document order.
    # Children of a parent share the same parent_content block.
    parents: List[Dict[str, Any]] = []
    parent_index: Dict[str, int] = {}
    chunks: List[Dict[str, Any]] = []
    for src in sources:
        section_title = (src.get("section_title") or "").strip()
        parent_key = src.get("parent_id") or f"{doc_id}:{section_title}"
        chunks.append(
            {
                "chunk_id": src.get("chunk_id") or "",
                "parent_id": parent_key,
                "content": (src.get("content") or "").strip(),
                # The retrieved context unit (parent ±1 neighbours) — a
                # verbatim substring of full_text by construction; used to
                # widen highlights when the child alone is a bare heading.
                "parent_content": (src.get("parent_content") or "").strip(),
                "section_title": section_title,
                "page_start": src.get("page_start"),
                "page_end": src.get("page_end"),
            }
        )
        if parent_key in parent_index:
            continue
        parent_index[parent_key] = len(parents)
        parents.append(
            {
                "parent_id": parent_key,
                "block": (src.get("parent_content") or "").strip(),
                "section_title": section_title,
                "page_start": src.get("page_start"),
                "page_end": src.get("page_end"),
            }
        )

    segments: List[Dict[str, Any]] = []
    pieces: List[str] = []
    cursor = 0

    def _append_segment(parent: Dict[str, Any], text: str) -> None:
        nonlocal cursor
        if not text:
            return
        if pieces:
            pieces.append("\n\n")
            cursor += 2
        pieces.append(text)
        segments.append(
            {
                "parent_id": parent["parent_id"],
                "section_title": parent["section_title"],
                "page_start": parent["page_start"],
                "page_end": parent["page_end"],
                "char_start": cursor,
                "char_end": cursor + len(text),
            }
        )
        cursor += len(text)

    have_blocks = any(p["block"] for p in parents)
    if have_blocks:
        # Identical blocks (all children of one parent, or exact repeats)
        # collapse; consecutive distinct blocks get de-overlapped.
        prev_block = ""
        for parent in parents:
            block = parent["block"]
            if not block or block == prev_block:
                continue
            overlap = _longest_suffix_prefix(prev_block, block)
            remainder = block[overlap:]
            if overlap and remainder:
                # Continue the previous segment's text without a separator:
                # the seam is mid-flow document text, not a block boundary.
                pieces.append(remainder)
                segments.append(
                    {
                        "parent_id": parent["parent_id"],
                        "section_title": parent["section_title"],
                        "page_start": parent["page_start"],
                        "page_end": parent["page_end"],
                        "char_start": cursor,
                        "char_end": cursor + len(remainder),
                    }
                )
                cursor += len(remainder)
            elif remainder:
                _append_segment(parent, remainder)
            prev_block = block
    else:
        # Legacy docs without parent_content: stitch de-duplicated child
        # chunks, one segment per chunk (mirrors get_navy_document_content).
        seen: set = set()
        for chunk in chunks:
            text = chunk["content"]
            if not text or text in seen:
                continue
            seen.add(text)
            _append_segment(
                {
                    "parent_id": chunk["parent_id"],
                    "section_title": chunk["section_title"],
                    "page_start": chunk["page_start"],
                    "page_end": chunk["page_end"],
                },
                text,
            )

    full_text = "".join(pieces)

    logger.info(
        "Navy doc segments {!r}: {} chunk hit(s), {} parent(s), {} segment(s), "
        "{} chars (user_id={!r})",
        doc_id,
        len(hits),
        len(parents),
        len(segments),
        len(full_text),
        user_id,
    )

    title = (
        first.get("document_name")
        or first.get("source")
        or _pretty_doc_label(doc_id, first)
    )

    return {
        "doc_id": doc_id,
        "title": title,
        "full_text": full_text,
        "segments": segments,
        "chunks": chunks,
        "chunk_count": len(hits),
        "document_type": first.get("document_type") or "",
        "document_status": first.get("document_status") or "",
        "access_scope": first.get("access_scope") or "",
        "classification_level": first.get("classification_level"),
        "creator_department": first.get("creator_department") or "",
        "source": first.get("document_name") or first.get("source") or "",
    }


async def get_navy_chunk(
    chunk_id: str,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch a single navy chunk by ``chunk_id`` (ACL-enforced, fail-closed).

    Used to resolve ``opensearch://{index}/{chunk_id}`` citation refs to
    their ``doc_id`` before reconstructing the document.
    """
    from open_notebook.access_control import access_enabled, build_opensearch_filter

    if not chunk_id:
        return None
    if user_id is None and access_enabled():
        return None

    client = await get_client()
    query: Dict[str, Any] = {"bool": {"must": [{"term": {"chunk_id": chunk_id}}]}}
    acl_filter = build_opensearch_filter(user_id)
    if acl_filter is not None:
        query["bool"]["filter"] = [acl_filter]

    body = {
        "size": 1,
        "query": query,
        "_source": [
            "doc_id", "chunk_id", "parent_id", "content", "parent_content",
            "section_title", "page_start", "page_end",
        ],
    }
    response = await _search_with_retry(client, body)
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return None
    return hits[0].get("_source", {})


def semantic_ordinal(chunk_id: Optional[str]) -> Optional[int]:
    """Extract ``n`` from a ``{doc_id}_semantic_{n}`` chunk id.

    The ordinal is short enough for an LLM to reproduce inside a citation
    (``navy:{doc_id}:p{page}:s{n}``), and the full chunk_id is reconstructible
    from ``doc_id`` + ``n`` — that is how citation clicks resolve back to the
    exact retrieved chunk for highlighting.
    """
    m = re.search(r"_semantic_(\d+)$", chunk_id or "")
    return int(m.group(1)) if m else None


def _pretty_doc_label(doc_id: str, sample: Dict[str, Any]) -> str:
    """Human-readable label for a document node."""
    name = sample.get("document_name") or sample.get("source")
    if name:
        return str(name)
    return doc_id.replace("_", " ").replace(".pdf", "").strip() or doc_id


def _cosine(a: Dict[str, int], b: Dict[str, int]) -> float:
    """Cosine similarity between two class→count vectors."""
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[c] * b[c] for c in shared)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# The navy index may map ``topic_class`` either as a pure ``keyword`` (when the
# corpus is reindexed with an explicit mapping) or — when the field is first
# created dynamically — as ``text`` with a ``.keyword`` sub-field. Aggregations
# require the keyword variant, so resolve it once from the live mapping.
_topic_agg_field_cache: Optional[str] = None


async def _topic_agg_field(client: Any) -> str:
    global _topic_agg_field_cache
    if _topic_agg_field_cache:
        return _topic_agg_field_cache
    try:
        mapping = await asyncio.to_thread(
            client.indices.get_mapping, index=NAVY_OPENSEARCH_INDEX
        )
        props = (
            mapping.get(NAVY_OPENSEARCH_INDEX, {})
            .get("mappings", {})
            .get("properties", {})
        )
        fld = props.get(TOPIC_CLASS_FIELD, {})
        if fld.get("type") == "keyword":
            _topic_agg_field_cache = TOPIC_CLASS_FIELD
        elif "keyword" in (fld.get("fields") or {}):
            _topic_agg_field_cache = f"{TOPIC_CLASS_FIELD}.keyword"
        else:
            _topic_agg_field_cache = TOPIC_CLASS_FIELD
    except Exception as e:  # noqa: BLE001 - fall back to the common dynamic case
        logger.warning(f"Could not resolve topic_class agg field: {e}")
        _topic_agg_field_cache = f"{TOPIC_CLASS_FIELD}.keyword"
    return _topic_agg_field_cache


async def build_document_graph(
    doc_ids: List[str],
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the document-relationship graph for a set of navy documents.

    Clusters the given documents by the ``topic_class`` of their chunks (a fixed,
    global taxonomy). Because a document's chunks can carry different classes, a
    document can belong to several clusters at once.

    Returns a payload with both graph topologies (the frontend toggles between
    them):
      - ``documents``  : per-doc class profile ``{id, label, chunk_count, classes}``
      - ``topics``     : the topic nodes present ``{id, label, color, doc_count, chunk_count}``
      - ``edges_bipartite``  : document→topic edges, weight = chunks of that class
      - ``edges_similarity`` : document↔document edges, weight = cosine over class
        profiles (0..1); only pairs sharing at least one class are included
    """
    from open_notebook.access_control import build_opensearch_filter

    color_map = get_topic_color_map()
    label_map = get_topic_label_map()

    empty: Dict[str, Any] = {
        "documents": [],
        "topics": [],
        "edges_bipartite": [],
        "edges_similarity": [],
    }
    if not doc_ids:
        return empty

    client = await get_client()

    filter_clauses: List[Dict[str, Any]] = [{"terms": {"doc_id": doc_ids}}]
    acl = build_opensearch_filter(user_id)
    if acl is not None:
        filter_clauses.append(acl)

    class_ids = get_topic_class_ids()
    agg_field = await _topic_agg_field(client)
    body: Dict[str, Any] = {
        "size": 0,
        "query": {"bool": {"filter": filter_clauses}},
        "aggs": {
            "docs": {
                "terms": {"field": "doc_id", "size": max(len(doc_ids), 1)},
                "aggs": {
                    "classes": {
                        "terms": {
                            "field": agg_field,
                            "size": max(len(class_ids), 1),
                        }
                    },
                    "sample": {
                        "top_hits": {
                            "size": 1,
                            "_source": ["document_name", "source"],
                        }
                    },
                },
            }
        },
    }

    response = await _search_with_retry(client, body)
    buckets = response.get("aggregations", {}).get("docs", {}).get("buckets", [])

    documents: List[Dict[str, Any]] = []
    profiles: Dict[str, Dict[str, int]] = {}
    topic_doc_count: Dict[str, int] = {}
    topic_chunk_count: Dict[str, int] = {}
    edges_bipartite: List[Dict[str, Any]] = []

    for bucket in buckets:
        doc_id = bucket["key"]
        chunk_count = bucket["doc_count"]
        sample_hits = bucket.get("sample", {}).get("hits", {}).get("hits", [])
        sample = sample_hits[0]["_source"] if sample_hits else {}

        class_buckets = bucket.get("classes", {}).get("buckets", [])
        profile: Dict[str, int] = {}
        classes_out: List[Dict[str, Any]] = []
        for cb in class_buckets:
            cls = cb["key"]
            count = cb["doc_count"]
            profile[cls] = count
            classes_out.append({"class": cls, "count": count})
            topic_doc_count[cls] = topic_doc_count.get(cls, 0) + 1
            topic_chunk_count[cls] = topic_chunk_count.get(cls, 0) + count
            edges_bipartite.append(
                {"source": doc_id, "topic": cls, "weight": count}
            )

        profiles[doc_id] = profile
        documents.append(
            {
                "id": doc_id,
                "label": _pretty_doc_label(doc_id, sample),
                "chunk_count": chunk_count,
                "classes": classes_out,
            }
        )

    # Topic nodes: only those actually present, in taxonomy order.
    topics = [
        {
            "id": cls,
            "label": label_map.get(cls, cls),
            "color": color_map.get(cls, "#94a3b8"),
            "doc_count": topic_doc_count[cls],
            "chunk_count": topic_chunk_count[cls],
        }
        for cls in class_ids
        if cls in topic_doc_count
    ]

    # Document↔document similarity edges (cosine over class profiles). Notebook
    # selections are capped (<= ~15 docs) so all-pairs is cheap.
    ids = list(profiles.keys())
    edges_similarity: List[Dict[str, Any]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            w = _cosine(profiles[ids[i]], profiles[ids[j]])
            if w > 0:
                edges_similarity.append(
                    {
                        "source": ids[i],
                        "target": ids[j],
                        "weight": round(w, 4),
                        "shared": sorted(
                            set(profiles[ids[i]]) & set(profiles[ids[j]])
                        ),
                    }
                )

    return {
        "documents": documents,
        "topics": topics,
        "edges_bipartite": edges_bipartite,
        "edges_similarity": edges_similarity,
    }


# Table-of-contents / index sections. Their chunks mention every topic in the
# document, so they embed close to almost ANY query and crowd out substantive
# chunks — and citations that land on them highlight index entries instead of
# content. Detected by section title or by TOC-shaped text (page-reference
# runs like ", 2 = 58" or dotted leaders "..... 58").
_TOC_SECTION_RE = re.compile(
    r"^\s*(índice|indice|sumário|sumario|table of contents|contents"
    r"|lista de (figuras|tabelas|abreviaturas|acrónimos|acronimos|anexos))\b",
    re.IGNORECASE,
)
_TOC_PAGE_REF_RE = re.compile(r",\s*\d+\s*=|\.{4,}\s*\d+")


def _is_toc_like(section_title: str, content: str) -> bool:
    """True when a chunk is a table-of-contents / index entry, not content."""
    if _TOC_SECTION_RE.match(section_title or ""):
        return True
    return len(_TOC_PAGE_REF_RE.findall(content or "")) >= 3


def _collapse_navy_hits(
    hits: List[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """Convert OpenSearch hits to navy result dicts, collapsing children of the
    same parent section into a single entry (small-to-big retrieval).

    Hits must arrive best-first (default OpenSearch score order), so keeping the
    first occurrence of each parent preserves its highest-ranked match. The full
    parent section (``parent_content``) is returned when present, falling back to
    the child chunk for documents indexed before parent fields existed. Legacy
    docs without ``parent_id`` collapse on ``doc_id:section_title`` instead, so a
    section is never represented more than once.
    """
    results: List[Dict[str, Any]] = []
    seen_parents: set = set()
    for hit in hits:
        src = hit.get("_source", {})
        doc_id = src.get("doc_id", "")
        section_title = src.get("section_title", "")
        parent_key = src.get("parent_id") or f"{doc_id}:{section_title}"
        if parent_key in seen_parents:
            continue
        seen_parents.add(parent_key)
        # Skip index/TOC chunks: they are retrieval noise and make citations
        # highlight index entries. Callers over-fetch ~3x, so dropping them
        # rarely starves the requested k.
        if _is_toc_like(section_title, src.get("content", "")):
            continue
        results.append({
            "doc_id": doc_id,
            "content": src.get("parent_content") or src.get("content", ""),
            "source": src.get("document_name") or src.get("source", ""),
            "section_title": section_title,
            "page_start": src.get("page_start"),
            "page_end": src.get("page_end"),
            "score": hit.get("_score", 0),
            # Best-ranked child of this parent — its semantic ordinal goes
            # into citable ids so the citation viewer can highlight the exact
            # retrieved passage instead of a whole page.
            "chunk_id": src.get("chunk_id", ""),
        })
        if len(results) >= limit:
            break
    return results


# Source fields fetched for navy chunk results. parent_id is the dedup key and
# parent_content is the full section text returned by small-to-big retrieval.
_NAVY_RESULT_SOURCE = [
    "doc_id",
    "chunk_id",
    "content",
    "source",
    "document_name",
    "document_path",
    "document_type",
    "document_status",
    "access_scope",
    "classification_level",
    "creator_department",
    "section_title",
    "page_start",
    "page_end",
    "parent_id",
    "parent_content",
]


# Sentinel: distinguishes "no ACL override given, derive from user_id" from
# "override explicitly provided (possibly None / a collaborative filter)".
_ACL_UNSET: Any = object()


async def filter_allowed_doc_ids(
    doc_ids: List[str], acl_filter: Optional[Dict[str, Any]]
) -> List[str]:
    """Return the subset of ``doc_ids`` still visible under ``acl_filter``.

    Used to prune a collaborative notebook's selected navy documents when its
    effective access tightens (e.g. a lower-clearance member joins): documents
    the new effective profile can no longer reach are dropped so they are no
    longer associated with the notebook. Original order is preserved.

    Best-effort: ``acl_filter is None`` means "no restriction" (returns the
    input de-duplicated); on any OpenSearch error the input is returned
    unchanged — the query-time ACL filter still prevents access regardless.
    """
    ordered = list(dict.fromkeys(doc_ids or []))  # de-dupe, keep order
    if not ordered:
        return []
    if acl_filter is None:
        return ordered
    try:
        client = await get_client()
        body: Dict[str, Any] = {
            "size": 0,
            "query": {
                "bool": {"filter": [acl_filter, {"terms": {"doc_id": ordered}}]}
            },
            "aggs": {"allowed": {"terms": {"field": "doc_id", "size": len(ordered)}}},
        }
        response = await _search_with_retry(client, body)
        buckets = (
            response.get("aggregations", {}).get("allowed", {}).get("buckets", [])
        )
        allowed = {b["key"] for b in buckets}
        return [d for d in ordered if d in allowed]
    except Exception as exc:  # noqa: BLE001 - best-effort prune
        logger.warning(
            f"Could not prune navy doc selection against effective ACL "
            f"(keeping current selection; query-time ACL still applies): {exc}"
        )
        return ordered


async def search_navy_documents(
    query: str,
    doc_ids: Optional[List[str]] = None,
    k: int = 10,
    user_id: Optional[str] = None,
    acl_filter: Any = _ACL_UNSET,
) -> List[Dict[str, Any]]:
    """BM25 text search on the navy corpus, optionally filtered by doc_ids.

    When ``user_id`` is given, the navy access-control filter (clearance +
    department) is applied so that only documents the user is allowed to
    see can be returned. Pass ``acl_filter`` to override that per-user filter
    with an explicit clause (e.g. a collaborative notebook's *effective*
    clearance/department filter).

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

        if acl_filter is _ACL_UNSET:
            from open_notebook.access_control import build_opensearch_filter
            acl = build_opensearch_filter(user_id)
        else:
            acl = acl_filter
        if acl is not None:
            filter_clause.append(acl)

        body: Dict[str, Any] = {
            # Over-fetch so that collapsing children of the same parent section
            # still leaves up to k distinct sections to return.
            "size": k * 3,
            "query": {
                "bool": {
                    "must": must_clause,
                    "filter": filter_clause,
                }
            },
            "_source": _NAVY_RESULT_SOURCE,
        }

        response = await _search_with_retry(client, body)

        hits = response.get("hits", {}).get("hits", [])
        return _collapse_navy_hits(hits, k)

    except Exception as e:
        logger.error(f"Navy document search failed: {e}")
        raise


async def vector_search_navy_documents(
    query: str,
    doc_ids: Optional[List[str]] = None,
    k: int = 5,
    min_score: float = 0.0,
    user_id: Optional[str] = None,
    acl_filter: Any = _ACL_UNSET,
) -> List[Dict[str, Any]]:
    """Semantic kNN search on the navy corpus using BGE-M3 embeddings.

    The navy index stores BAAI/bge-m3 embeddings in the ``embedding`` field.
    The query is embedded with the configured embedding model (which must
    also be BGE-M3 for the vectors to be comparable) and matched against
    those vectors via the OpenSearch k-NN plugin.

    When ``user_id`` is given, the navy access-control filter (clearance +
    department) is applied alongside the kNN match.

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
            return await search_navy_documents(
                query, doc_ids=doc_ids, k=k, user_id=user_id, acl_filter=acl_filter
            )

        client = await get_client()

        # Over-fetch candidates so parent-section dedup still yields up to k.
        fetch_n = max(k * 3, 1)
        knn_clause: Dict[str, Any] = {
            "vector": embedding,
            "k": fetch_n,
        }

        if acl_filter is _ACL_UNSET:
            from open_notebook.access_control import build_opensearch_filter
            acl = build_opensearch_filter(user_id)
        else:
            acl = acl_filter
        knn_filters: List[Dict[str, Any]] = []
        if doc_ids:
            knn_filters.append({"terms": {"doc_id": doc_ids}})
        if acl is not None:
            knn_filters.append(acl)
        if len(knn_filters) == 1:
            knn_clause["filter"] = knn_filters[0]
        elif knn_filters:
            knn_clause["filter"] = {"bool": {"must": knn_filters}}

        body: Dict[str, Any] = {
            "size": fetch_n,
            "query": {"knn": {"embedding": knn_clause}},
            "_source": _NAVY_RESULT_SOURCE,
        }
        if min_score > 0:
            body["min_score"] = min_score

        response = await _search_with_retry(client, body)

        hits = response.get("hits", {}).get("hits", [])
        return _collapse_navy_hits(hits, k)

    except Exception as e:
        logger.error(f"Navy vector search failed, falling back to BM25: {e}")
        return await search_navy_documents(
            query,
            doc_ids=doc_ids,
            k=k,
            user_id=user_id,
        )


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
