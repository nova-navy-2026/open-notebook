"""
Topic classification command for the document-relationship graph.

Writes a ``topic_class`` keyword onto every chunk in the navy corpus OpenSearch
index (``NAVY_OPENSEARCH_INDEX``). Two modes:

- ``mock``  — assign each chunk a *deterministic* class from the fixed taxonomy
  via an OpenSearch ``update_by_query`` Painless script. No LLM, no re-embedding;
  fast and stable across runs. Each document is biased toward a contiguous window
  of 1–3 classes so the resulting graph shows realistic multi-cluster membership.
  Used to prototype the UI before the real (expensive) reindex.

- ``real``  — read each chunk's ``content`` and ask the LLM to assign one class
  from the taxonomy, then bulk-write the result. This is the path to run once for
  the canonical classification (the "immediate next step" after the prototype).

The taxonomy comes from :mod:`open_notebook.search.topics` (a fixed, global list).
"""

import asyncio
import json
import time
from typing import List, Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.config import NAVY_OPENSEARCH_INDEX
from open_notebook.search.client import get_client
from open_notebook.search.topics import (
    TOPIC_CLASS_FIELD,
    get_topic_class_ids,
    get_topic_taxonomy,
)

# Painless script: assign a deterministic topic_class to each chunk.
#
# Each document (keyed by doc_id) is given a contiguous window of `span` classes
# (span = 1..3) starting at a per-document base offset; each chunk (keyed by its
# _id) deterministically picks one class within that window. The result is stable
# across runs and gives most documents several distinct chunk-level classes →
# multi-cluster membership in the graph.
_MOCK_PAINLESS = """
int n = params.classes.size();
if (n == 0) { return; }
String doc = (ctx._source.containsKey('doc_id') && ctx._source.doc_id != null)
    ? ctx._source.doc_id.toString() : '';
String chunk = ctx._id != null ? ctx._id.toString() : doc;
int dh = doc.hashCode();
int adh = dh < 0 ? -dh : dh;
int base = ((dh % n) + n) % n;
int span = (adh % 3) + 1;
int ch = chunk.hashCode();
int offset = ((ch % span) + span) % span;
int idx = (base + offset) % n;
ctx._source.topic_class = params.classes.get(idx);
"""


class ClassifyTopicsInput(CommandInput):
    """Input for the classify_topics command."""

    mode: str = "mock"  # "mock" | "real"
    overwrite: bool = True  # Re-classify chunks that already have a topic_class
    batch_size: int = 100  # (real mode) chunks per LLM request
    max_chunks: Optional[int] = None  # (real mode) cap for a partial/test run


class ClassifyTopicsOutput(CommandOutput):
    """Output from the classify_topics command."""

    success: bool
    mode: str = "mock"
    chunks_classified: int = 0
    processing_time: float = 0.0
    error_message: Optional[str] = None


@command("classify_topics", app="open_notebook", retry=None)
async def classify_topics_command(
    input_data: ClassifyTopicsInput,
) -> ClassifyTopicsOutput:
    """Populate ``topic_class`` on navy-corpus chunks (mock or real)."""
    start_time = time.time()
    mode = (input_data.mode or "mock").lower()
    try:
        class_ids = get_topic_class_ids()
        if not class_ids:
            raise ValueError("Topic taxonomy is empty; cannot classify.")

        logger.info(
            f"classify_topics: mode={mode} overwrite={input_data.overwrite} "
            f"index={NAVY_OPENSEARCH_INDEX} classes={len(class_ids)}"
        )

        if mode == "mock":
            count = await _classify_mock(class_ids, overwrite=input_data.overwrite)
        elif mode == "real":
            count = await _classify_real(
                class_ids,
                overwrite=input_data.overwrite,
                batch_size=input_data.batch_size,
                max_chunks=input_data.max_chunks,
            )
        else:
            raise ValueError(f"Unknown mode {mode!r} (expected 'mock' or 'real').")

        elapsed = time.time() - start_time
        logger.info(f"classify_topics complete: {count} chunks in {elapsed:.1f}s")
        return ClassifyTopicsOutput(
            success=True,
            mode=mode,
            chunks_classified=count,
            processing_time=elapsed,
        )
    except ValueError as e:
        # Permanent error — do not retry.
        logger.error(f"classify_topics validation error: {e}")
        return ClassifyTopicsOutput(
            success=False,
            mode=mode,
            processing_time=time.time() - start_time,
            error_message=str(e),
        )
    except Exception as e:
        logger.exception(f"classify_topics failed: {e}")
        return ClassifyTopicsOutput(
            success=False,
            mode=mode,
            processing_time=time.time() - start_time,
            error_message=str(e),
        )


async def _classify_mock(class_ids: List[str], *, overwrite: bool) -> int:
    """Assign deterministic mock classes server-side via update_by_query."""
    client = await get_client()

    query = (
        {"match_all": {}}
        if overwrite
        else {"bool": {"must_not": [{"exists": {"field": TOPIC_CLASS_FIELD}}]}}
    )
    body = {
        "script": {
            "source": _MOCK_PAINLESS,
            "lang": "painless",
            "params": {"classes": class_ids},
        },
        "query": query,
    }

    response = await asyncio.to_thread(
        client.update_by_query,
        index=NAVY_OPENSEARCH_INDEX,
        body=body,
        refresh=True,
        conflicts="proceed",
        wait_for_completion=True,
        request_timeout=600,
    )
    return int(response.get("updated", 0))


# ---------------------------------------------------------------------------
# Real (LLM) classification — built for the canonical run; not used by the
# prototype. Scrolls all chunks, classifies each batch, then bulk-updates.
# ---------------------------------------------------------------------------

def _build_classification_prompt(class_ids: List[str], chunks: List[str]) -> str:
    taxonomy = get_topic_taxonomy()
    classes_block = "\n".join(f"- {c['id']}: {c['label']}" for c in taxonomy)
    numbered = "\n\n".join(f"[{i}] {text[:1500]}" for i, text in enumerate(chunks))
    return (
        "You are classifying document passages into a fixed topic taxonomy.\n"
        "Assign each passage to exactly ONE class id from this list:\n"
        f"{classes_block}\n\n"
        "Return ONLY a JSON array of objects like "
        '[{\"i\": 0, \"class\": \"navigation\"}, ...] with one entry per passage, '
        "using the passage index shown in brackets and a class id from the list "
        "above. Do not add commentary.\n\n"
        f"Passages:\n{numbered}"
    )


async def _classify_real(
    class_ids: List[str],
    *,
    overwrite: bool,
    batch_size: int,
    max_chunks: Optional[int],
) -> int:
    """Classify chunk content with the LLM and bulk-write topic_class."""
    from open_notebook.ai.provision import provision_langchain_model
    from open_notebook.utils import clean_thinking_content
    from open_notebook.utils.text_utils import extract_text_content

    client = await get_client()
    valid = set(class_ids)

    query = (
        {"match_all": {}}
        if overwrite
        else {"bool": {"must_not": [{"exists": {"field": TOPIC_CLASS_FIELD}}]}}
    )
    # Open a scroll over the matching chunks (id + content only).
    page = await asyncio.to_thread(
        client.search,
        index=NAVY_OPENSEARCH_INDEX,
        body={"query": query, "_source": ["content"], "size": batch_size},
        scroll="5m",
    )
    scroll_id = page.get("_scroll_id")
    hits = page.get("hits", {}).get("hits", [])

    total = 0
    try:
        while hits:
            ids = [h["_id"] for h in hits]
            texts = [h.get("_source", {}).get("content", "") for h in hits]

            prompt = _build_classification_prompt(class_ids, texts)
            chain = await provision_langchain_model(
                prompt, None, "transformation", max_tokens=4096
            )
            response = await chain.ainvoke(prompt)
            raw = clean_thinking_content(extract_text_content(response.content))
            assignments = _parse_assignments(raw, len(texts), valid, class_ids)

            # Bulk-update topic_class by _id.
            bulk = ""
            for _id, cls in zip(ids, assignments):
                bulk += json.dumps(
                    {"update": {"_index": NAVY_OPENSEARCH_INDEX, "_id": _id}}
                ) + "\n"
                bulk += json.dumps({"doc": {TOPIC_CLASS_FIELD: cls}}) + "\n"
            await asyncio.to_thread(client.bulk, body=bulk, refresh=False)
            total += len(ids)

            if max_chunks is not None and total >= max_chunks:
                break

            page = await asyncio.to_thread(client.scroll, scroll_id=scroll_id, scroll="5m")
            scroll_id = page.get("_scroll_id")
            hits = page.get("hits", {}).get("hits", [])
            logger.info(f"classify_topics(real): {total} chunks classified so far")
    finally:
        if scroll_id:
            try:
                await asyncio.to_thread(client.clear_scroll, scroll_id=scroll_id)
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
        await asyncio.to_thread(client.indices.refresh, index=NAVY_OPENSEARCH_INDEX)

    return total


def _parse_assignments(
    raw: str, n: int, valid: set, class_ids: List[str]
) -> List[str]:
    """Parse the LLM JSON array into n class ids, defaulting unknowns safely."""
    fallback = class_ids[0]
    result = [fallback] * n
    try:
        start = raw.find("[")
        end = raw.rfind("]")
        parsed = json.loads(raw[start : end + 1]) if start != -1 and end != -1 else []
        for item in parsed:
            i = int(item.get("i"))
            cls = str(item.get("class", "")).strip()
            if 0 <= i < n and cls in valid:
                result[i] = cls
    except Exception as e:  # noqa: BLE001 - tolerate malformed LLM output
        logger.warning(f"classify_topics(real): could not parse LLM output ({e}); "
                       f"defaulting batch to {fallback!r}")
    return result
