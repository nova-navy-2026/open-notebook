"""Citation viewer service.

Materializes OpenSearch-only navy documents into the temporary SurrealDB
``cited_document`` table so the frontend citation side panel can display them
with the cited passage highlighted, then deletes them when the panel closes.
Regular sources are never materialized (their full_text already lives on the
``source`` record).

Highlight anchors, in priority order:
1. ``chunk_id`` — the cited chunk's child ``content`` is a verbatim substring
   of the reconstructed document; locate it for exact offsets.
2. ``snippet`` — verbatim text from search-result ``matches`` (may carry a
   leading ``[section · pp. X-Y]`` label, which is stripped).
3. page — from ``navy:{doc_id}:p{N}`` refs; highlights every chunk whose
   page range covers N.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from open_notebook.database.repository import repo_query
from open_notebook.domain.cited_document import CitedDocument
from open_notebook.exceptions import InvalidInputError, NotFoundError
from open_notebook.search.navy_docs import (
    get_navy_chunk,
    get_navy_document_segments,
)

_OPENSEARCH_REF = re.compile(r"^opensearch://[^/]+/(?P<chunk_id>.+)$")
_PAGE_SUFFIX = re.compile(r":p(\d+)$")
_SEMANTIC_SUFFIX = re.compile(r":s(\d+)$")
_MATCH_LABEL_PREFIX = re.compile(r"^\[[^\[\]]{0,200}\]\s*")

# Keep strong references to fire-and-forget sweep tasks (asyncio only holds
# weak references to tasks; without this they can be garbage collected).
_background_tasks: Set[asyncio.Task] = set()


def _parse_ref(ref: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Parse a citation ref into (doc_id, page, chunk_id).

    Accepted forms:
    - ``navy:{doc_id}`` — doc_id is the raw filename (spaces/accents/parens).
    - ``navy:{doc_id}:p{N}`` — ``:p{N}`` is a page anchor.
    - ``navy:{doc_id}:p{N}:s{M}`` — ``:s{M}`` is the semantic-chunk ordinal;
      the exact chunk_id is reconstructed as ``{doc_id}_semantic_{M}`` for
      chunk-precise highlighting (page kept as fallback).
    - ``opensearch://{index}/{chunk_id}`` — resolved to a doc via the chunk.

    Suffixes are stripped right-to-left, so filenames containing colons
    still parse (only trailing ``:sN``/``:pN`` are treated as anchors).
    """
    ref = (ref or "").strip()
    m = _OPENSEARCH_REF.match(ref)
    if m:
        return None, None, m.group("chunk_id")
    if ref.startswith("navy:"):
        payload = ref[len("navy:"):].strip()
        semantic: Optional[int] = None
        page: Optional[int] = None
        sm = _SEMANTIC_SUFFIX.search(payload)
        if sm:
            semantic = int(sm.group(1))
            payload = payload[: sm.start()]
        pm = _PAGE_SUFFIX.search(payload)
        if pm:
            page = int(pm.group(1))
            payload = payload[: pm.start()]
        if payload:
            chunk_id = (
                f"{payload}_semantic_{semantic}" if semantic is not None else None
            )
            return payload, page, chunk_id
    raise InvalidInputError(f"Unrecognized citation ref: {ref!r}")


def _normalize_with_map(text: str) -> Tuple[str, List[int]]:
    """Collapse whitespace runs to single spaces, keeping an index map back
    to the original string (one original index per normalized character)."""
    chars: List[str] = []
    index_map: List[int] = []
    prev_space = True  # suppresses leading whitespace
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                chars.append(" ")
                index_map.append(i)
                prev_space = True
        else:
            chars.append(ch)
            index_map.append(i)
            prev_space = False
    return "".join(chars), index_map


def _find_span(
    full_text: str,
    needle: str,
    norm_cache: Dict[str, Any],
    hint_start: int = 0,
) -> Optional[Tuple[int, int]]:
    """Locate ``needle`` in ``full_text``: exact match first (preferring
    occurrences at/after ``hint_start``), then whitespace-normalized."""
    needle = (needle or "").strip()
    if not needle:
        return None

    pos = full_text.find(needle, hint_start)
    if pos < 0 and hint_start:
        pos = full_text.find(needle)
    if pos >= 0:
        return pos, pos + len(needle)

    if "norm" not in norm_cache:
        norm_cache["norm"], norm_cache["map"] = _normalize_with_map(full_text)
    norm_text: str = norm_cache["norm"]
    index_map: List[int] = norm_cache["map"]
    norm_needle = " ".join(needle.split())
    if not norm_needle:
        return None
    npos = norm_text.find(norm_needle)
    if npos < 0:
        return None
    start = index_map[npos]
    end = index_map[npos + len(norm_needle) - 1] + 1
    return start, end


def _merge_spans(spans: List[Tuple[int, int]], gap: int = 2) -> List[Dict[str, int]]:
    """Merge overlapping/near-adjacent spans into sorted highlight dicts."""
    merged: List[List[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [{"start": s, "end": e} for s, e in merged]


def _compute_highlights(
    doc: Dict[str, Any],
    chunk_id: Optional[str],
    snippet: Optional[str],
    page: Optional[int],
) -> List[Dict[str, int]]:
    full_text: str = doc["full_text"]
    chunks: List[Dict[str, Any]] = doc.get("chunks", [])
    norm_cache: Dict[str, Any] = {}

    if chunk_id:
        for chunk in chunks:
            if chunk.get("chunk_id") == chunk_id:
                span = _find_span(full_text, chunk.get("content", ""), norm_cache)
                # A very short chunk is usually a bare heading/fragment —
                # highlighting it alone looks meaningless. Widen to the
                # retrieved context unit (parent ±1 neighbours), which is
                # what the model actually read.
                if span and (span[1] - span[0]) < 200:
                    wide = _find_span(
                        full_text,
                        chunk.get("parent_content", ""),
                        norm_cache,
                        hint_start=max(0, span[0] - 4000),
                    )
                    if wide and wide[0] <= span[0] and wide[1] >= span[1]:
                        span = wide
                if span:
                    return _merge_spans([span])
                break

    if snippet:
        candidates = [snippet, _MATCH_LABEL_PREFIX.sub("", snippet, count=1)]
        for candidate in candidates:
            span = _find_span(full_text, candidate, norm_cache)
            if span:
                return _merge_spans([span])

    if page is not None:
        spans: List[Tuple[int, int]] = []
        # Hint the search with the segment spans of parents on that page so
        # repeated boilerplate (headers etc.) resolves to the right region.
        segment_starts = {
            seg["parent_id"]: seg["char_start"] for seg in doc.get("segments", [])
        }
        for chunk in chunks:
            p_start, p_end = chunk.get("page_start"), chunk.get("page_end")
            if p_start is None:
                continue
            if p_start <= page <= (p_end if p_end is not None else p_start):
                hint = max(0, segment_starts.get(chunk.get("parent_id"), 0) - 8)
                span = _find_span(full_text, chunk.get("content", ""), norm_cache, hint)
                if span:
                    spans.append(span)
        if spans:
            return _merge_spans(spans)

    return []


def _schedule(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def sweep_stale_cited_documents(
    owner: Optional[str] = None, max_age: str = "1h"
) -> None:
    """Delete leaked cited_document records (no TTL exists in SurrealDB)."""
    try:
        if owner:
            await repo_query(
                f"DELETE cited_document WHERE owner = $owner "
                f"AND updated < time::now() - {max_age}",
                {"owner": owner},
            )
        else:
            await repo_query(
                f"DELETE cited_document WHERE updated < time::now() - {max_age}"
            )
    except Exception as exc:  # noqa: BLE001 - sweep must never break requests
        logger.warning(f"cited_document sweep failed: {exc}")


async def _save_upsert_with_retry(
    record: Optional[CitedDocument],
    fields: Dict[str, Any],
    owner: str,
    doc_id: str,
    attempts: int = 4,
) -> CitedDocument:
    """Apply ``fields`` to the (owner, doc_id) record and save it, surviving
    concurrency: SurrealDB raises retryable write conflicts on simultaneous
    updates, and the UNIQUE (owner, doc_id) index (migration 23) rejects the
    losers of a create race. Both are handled by re-resolving the current
    record and retrying with a short backoff."""
    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        if attempt:
            await asyncio.sleep(0.05 * attempt)
            record = await CitedDocument.get_by_owner_and_doc_id(owner, doc_id)
        try:
            if record is None:
                record = CitedDocument(**fields)
            else:
                for key, value in fields.items():
                    setattr(record, key, value)
            await record.save()
            return record
        except Exception as exc:  # noqa: BLE001 - re-raised after retries
            last_exc = exc
            record = None
    raise last_exc  # type: ignore[misc]


async def materialize_citation(
    ref: str,
    chunk_id: Optional[str],
    snippet: Optional[str],
    owner: str,
    acl_user_id: Optional[str],
) -> CitedDocument:
    """Reconstruct the cited navy document and upsert it as a temporary
    ``cited_document`` record for ``owner``. Raises ``InvalidInputError`` on
    a malformed ref and ``NotFoundError`` when the document doesn't exist or
    the user's clearance doesn't cover it (fail-closed)."""
    doc_id, page, ref_chunk_id = _parse_ref(ref)
    anchor_chunk_id = chunk_id or ref_chunk_id

    anchor_chunk: Optional[Dict[str, Any]] = None
    if doc_id is None:
        anchor_chunk = await get_navy_chunk(
            anchor_chunk_id or "", user_id=acl_user_id
        )
        if not anchor_chunk or not anchor_chunk.get("doc_id"):
            raise NotFoundError(f"Cited chunk not found: {anchor_chunk_id!r}")
        doc_id = anchor_chunk["doc_id"]

    record = await CitedDocument.get_by_owner_and_doc_id(owner, doc_id)
    if record is not None:
        # Repeat click into an already-materialized document: reuse the
        # stored full_text/segments and only re-anchor the highlights. A
        # chunk anchor needs just that one chunk (single ACL-checked term
        # query) instead of the full reconstruction; snippet anchors are a
        # pure string search. The owner passed the document ACL when the
        # record was materialized (≤1h ago — sweeps bound its age).
        if anchor_chunk_id and anchor_chunk is None:
            anchor_chunk = await get_navy_chunk(
                anchor_chunk_id, user_id=acl_user_id
            )
        cached_doc = {
            "full_text": record.full_text,
            "segments": record.segments,
            "chunks": [anchor_chunk] if anchor_chunk else [],
        }
        highlights = _compute_highlights(cached_doc, anchor_chunk_id, snippet, page)
        if highlights or (anchor_chunk_id is None and snippet is None and page is None):
            try:
                record = await _save_upsert_with_retry(
                    record, {"highlights": highlights}, owner, doc_id
                )
                _schedule(sweep_stale_cited_documents(owner=owner, max_age="1h"))
                return record
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"cached cited_document reuse failed for {doc_id!r}, "
                    f"rebuilding: {exc}"
                )
        # The anchors couldn't be resolved against the cached text (a
        # page-only ref needs the full chunk list) or the reuse save lost
        # every retry. Fall through to a full reconstruction.

    doc = await get_navy_document_segments(doc_id, user_id=acl_user_id)
    if doc is None:
        raise NotFoundError(f"Document not found or not accessible: {doc_id!r}")

    highlights = _compute_highlights(doc, anchor_chunk_id, snippet, page)
    if len(doc["full_text"]) > 2_000_000:
        logger.warning(
            f"cited_document for {doc_id!r} is very large "
            f"({len(doc['full_text'])} chars)"
        )

    fields = {
        "doc_id": doc_id,
        "title": doc["title"],
        "full_text": doc["full_text"],
        "highlights": highlights,
        "segments": doc["segments"],
        "owner": owner,
        "document_type": doc.get("document_type") or None,
        "document_status": doc.get("document_status") or None,
        "access_scope": doc.get("access_scope") or None,
        "classification_level": doc.get("classification_level"),
        "creator_department": doc.get("creator_department") or None,
        "source": doc.get("source") or None,
    }

    record = await _save_upsert_with_retry(record, fields, owner, doc_id)

    _schedule(sweep_stale_cited_documents(owner=owner, max_age="1h"))
    return record


async def get_cited_document(record_id: str, owner: str) -> CitedDocument:
    record = await CitedDocument.get(record_id)
    if not record or record.owner != owner:
        # Same error for missing and foreign records: don't leak existence.
        raise NotFoundError(f"Cited document not found: {record_id!r}")
    return record


async def delete_cited_document(record_id: str, owner: str) -> None:
    record = await get_cited_document(record_id, owner)
    await record.delete()
