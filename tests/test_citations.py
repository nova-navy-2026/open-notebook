"""Tests for the citation viewer: de-overlap reconstruction and highlight
offset math.

The navy index stores ``parent_content`` as parent ±1 neighbours, so
consecutive blocks share ~60% of their text; the reconstruction must
de-overlap them so each passage appears exactly once, and highlight anchors
must land on the right character offsets.
"""

import pytest

from api.citations_service import (
    _compute_highlights,
    _find_span,
    _merge_spans,
    _normalize_with_map,
    _parse_ref,
)
from open_notebook.exceptions import InvalidInputError
from open_notebook.search import navy_docs
from open_notebook.search.navy_docs import (
    _longest_suffix_prefix,
    _parent_sort_key,
    get_navy_document_segments,
)

# ---------------------------------------------------------------------------
# Synthetic corpus mimicking the real small-to-big ±1-neighbour structure
# ---------------------------------------------------------------------------

DOC_ID = "PEETNA 3253 - Logística I.pdf"
P = [
    "Primeiro parágrafo sobre logística naval e conceitos gerais.",
    "Segundo parágrafo: gestão do material e do abastecimento.",
    "Terceiro parágrafo, com detalhes de manutenção e reparação.",
    "Quarto parágrafo final da secção, sobre transporte.",
]
SEP = "\n\n"


def _block(i: int) -> str:
    """parent_content of parent i = P[i-1] + P[i] + P[i+1] (within section)."""
    parts = []
    if i > 0:
        parts.append(P[i - 1])
    parts.append(P[i])
    if i < len(P) - 1:
        parts.append(P[i + 1])
    return SEP.join(parts)


def _hit(i: int, page: int) -> dict:
    return {
        "_source": {
            "doc_id": DOC_ID,
            "chunk_id": f"{DOC_ID}_semantic_{i}",
            "parent_id": f"{DOC_ID}_section_1_chunk_{i}",
            "content": P[i],
            "parent_content": _block(i),
            "section_title": "SECÇÃO I",
            "page_start": page,
            "page_end": page,
            "document_name": DOC_ID,
        }
    }


@pytest.fixture
def patched_opensearch(monkeypatch):
    """Route the reconstruction's OpenSearch call to the synthetic corpus and
    disable ACL so no identity plumbing is needed."""
    hits = [_hit(0, 1), _hit(1, 1), _hit(2, 2), _hit(3, 2)]

    async def fake_search(client, body, **kwargs):
        return {"hits": {"hits": hits}}

    async def fake_get_client():
        return object()

    import open_notebook.access_control as ac

    monkeypatch.setattr(navy_docs, "_search_with_retry", fake_search)
    monkeypatch.setattr(navy_docs, "get_client", fake_get_client)
    monkeypatch.setattr(ac, "access_enabled", lambda: False)
    monkeypatch.setattr(ac, "build_opensearch_filter", lambda user_id: None)
    return hits


# ---------------------------------------------------------------------------
# De-overlap primitives
# ---------------------------------------------------------------------------

class TestOverlapPrimitives:
    def test_longest_suffix_prefix_finds_neighbour_overlap(self):
        b1 = _block(1)  # P0+P1+P2
        b2 = _block(2)  # P1+P2+P3
        overlap = _longest_suffix_prefix(b1, b2)
        assert b2[:overlap] == SEP.join([P[1], P[2]])

    def test_no_overlap_between_unrelated_text(self):
        assert _longest_suffix_prefix("abcdef", "xyz") == 0

    def test_parent_sort_key_orders_ordinals_numerically(self):
        low = {"parent_id": "d_section_11_chunk_0", "page_start": 5, "chunk_id": ""}
        high = {"parent_id": "d_section_111_chunk_0", "page_start": 5, "chunk_id": ""}
        assert _parent_sort_key(low) < _parent_sort_key(high)


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------

class TestReconstruction:
    @pytest.mark.asyncio
    async def test_full_text_has_each_passage_exactly_once(self, patched_opensearch):
        doc = await get_navy_document_segments(DOC_ID, user_id="tester")
        assert doc is not None
        for passage in P:
            assert doc["full_text"].count(passage) == 1, passage
        # De-overlapped join reproduces the original section text.
        assert doc["full_text"] == SEP.join(P)

    @pytest.mark.asyncio
    async def test_segments_cover_full_text_without_gaps(self, patched_opensearch):
        doc = await get_navy_document_segments(DOC_ID, user_id="tester")
        segs = doc["segments"]
        assert segs, "expected at least one segment"
        assert segs[0]["char_start"] == 0
        assert segs[-1]["char_end"] == len(doc["full_text"])
        for seg in segs:
            assert doc["full_text"][seg["char_start"]:seg["char_end"]] != ""

    @pytest.mark.asyncio
    async def test_chunks_are_verbatim_substrings(self, patched_opensearch):
        doc = await get_navy_document_segments(DOC_ID, user_id="tester")
        for chunk in doc["chunks"]:
            assert chunk["content"] in doc["full_text"]


# ---------------------------------------------------------------------------
# Ref parsing
# ---------------------------------------------------------------------------

class TestParseRef:
    def test_navy_plain(self):
        assert _parse_ref(f"navy:{DOC_ID}") == (DOC_ID, None, None)

    def test_navy_with_page_suffix(self):
        assert _parse_ref(f"navy:{DOC_ID}:p12") == (DOC_ID, 12, None)

    def test_navy_with_semantic_suffix(self):
        # ":s{n}" reconstructs the exact chunk_id for precise highlighting.
        assert _parse_ref(f"navy:{DOC_ID}:p12:s7") == (
            DOC_ID, 12, f"{DOC_ID}_semantic_7",
        )

    def test_navy_semantic_without_page(self):
        assert _parse_ref(f"navy:{DOC_ID}:s7") == (
            DOC_ID, None, f"{DOC_ID}_semantic_7",
        )

    def test_opensearch_url(self):
        chunk = f"{DOC_ID}_semantic_3"
        assert _parse_ref(f"opensearch://amalia_navy_test/{chunk}") == (
            None, None, chunk,
        )

    def test_invalid_ref_raises(self):
        with pytest.raises(InvalidInputError):
            _parse_ref("source:abc123")

    def test_semantic_ordinal_parsing(self):
        from open_notebook.search.navy_docs import semantic_ordinal

        assert semantic_ordinal(f"{DOC_ID}_semantic_42") == 42
        assert semantic_ordinal("no_ordinal_here") is None
        assert semantic_ordinal(None) is None


# ---------------------------------------------------------------------------
# TOC / index filtering in retrieval
# ---------------------------------------------------------------------------

class TestTocFiltering:
    def test_toc_section_titles_detected(self):
        from open_notebook.search.navy_docs import _is_toc_like

        assert _is_toc_like("ÍNDICE", "anything")
        assert _is_toc_like("Sumário", "anything")
        assert _is_toc_like("Lista de Figuras", "anything")
        assert not _is_toc_like("SECÇÃO I", "Conceito de Gestão do Material.")

    def test_toc_shaped_content_detected(self):
        from open_notebook.search.navy_docs import _is_toc_like

        toc_text = ", 1 = 401. Conceito. , 2 = 405. Objectivo. , 3 = 58"
        assert _is_toc_like("", toc_text)
        dotted = "Introdução ..... 5\nConceitos ...... 12\nAnexos ....... 60"
        assert _is_toc_like("", dotted)
        # One stray page-ref pattern is not enough to flag real content.
        assert not _is_toc_like("", "A dotação, 1 = 401 unidades, foi definida.")

    def test_collapse_skips_toc_chunks(self):
        from open_notebook.search.navy_docs import _collapse_navy_hits

        def hit(pid, section, content, score):
            return {
                "_score": score,
                "_source": {
                    "doc_id": DOC_ID,
                    "parent_id": pid,
                    "section_title": section,
                    "content": content,
                    "parent_content": content,
                    "chunk_id": f"{pid}_child",
                },
            }

        hits = [
            hit("p1", "ÍNDICE", ", 1 = 401. , 2 = 405. , 3 = 58", 0.9),
            hit("p2", "SECÇÃO I", "Conteúdo real sobre logística.", 0.8),
        ]
        results = _collapse_navy_hits(hits, 5)
        assert [r["section_title"] for r in results] == ["SECÇÃO I"]


class TestShortChunkWidening:
    def test_short_chunk_widens_to_parent_content(self):
        heading = "CAPÍTULO 2 — MANUTENÇÃO"
        parent_content = SEP.join([P[0], heading, P[1]])
        full_text = SEP.join([P[3], parent_content, P[2]])
        doc = {
            "full_text": full_text,
            "segments": [],
            "chunks": [
                {
                    "chunk_id": f"{DOC_ID}_semantic_9",
                    "parent_id": "p9",
                    "content": heading,
                    "parent_content": parent_content,
                    "page_start": 3,
                    "page_end": 3,
                }
            ],
        }
        hl = _compute_highlights(doc, f"{DOC_ID}_semantic_9", None, None)
        assert len(hl) == 1
        span = doc["full_text"][hl[0]["start"]:hl[0]["end"]]
        assert span == parent_content  # widened beyond the bare heading

    def test_long_chunk_not_widened(self):
        long_content = P[1] * 5  # comfortably > 200 chars
        full_text = SEP.join([P[0], long_content, P[2]])
        doc = {
            "full_text": full_text,
            "segments": [],
            "chunks": [
                {
                    "chunk_id": f"{DOC_ID}_semantic_3",
                    "parent_id": "p3",
                    "content": long_content,
                    "parent_content": full_text,
                    "page_start": 1,
                    "page_end": 1,
                }
            ],
        }
        hl = _compute_highlights(doc, f"{DOC_ID}_semantic_3", None, None)
        assert len(hl) == 1
        assert doc["full_text"][hl[0]["start"]:hl[0]["end"]] == long_content


# ---------------------------------------------------------------------------
# Highlight offsets
# ---------------------------------------------------------------------------

class TestHighlightOffsets:
    def test_normalize_with_map_round_trip(self):
        text = "a  b\n\nc\td"
        norm, index_map = _normalize_with_map(text)
        assert norm == "a b c d"
        # Every normalized position maps to a valid original index.
        assert text[index_map[norm.find("c")]] == "c"

    def test_find_span_exact(self):
        assert _find_span("hello world", "world", {}) == (6, 11)

    def test_find_span_whitespace_drift(self):
        full = "linha um\n\nlinha  dois com espaços"
        span = _find_span(full, "linha dois com espaços", {})
        assert span is not None
        assert full[span[0]:span[1]].split() == ["linha", "dois", "com", "espaços"]

    def test_merge_spans_merges_adjacent(self):
        assert _merge_spans([(0, 5), (5, 9), (20, 25)]) == [
            {"start": 0, "end": 9},
            {"start": 20, "end": 25},
        ]

    def _doc(self):
        full_text = SEP.join(P)
        offsets = []
        cursor = 0
        for text in P:
            offsets.append((cursor, cursor + len(text)))
            cursor += len(text) + len(SEP)
        return {
            "full_text": full_text,
            "segments": [
                {
                    "parent_id": f"{DOC_ID}_section_1_chunk_{i}",
                    "char_start": offsets[i][0],
                    "char_end": offsets[i][1],
                }
                for i in range(len(P))
            ],
            "chunks": [
                {
                    "chunk_id": f"{DOC_ID}_semantic_{i}",
                    "parent_id": f"{DOC_ID}_section_1_chunk_{i}",
                    "content": P[i],
                    "page_start": 1 if i < 2 else 2,
                    "page_end": 1 if i < 2 else 2,
                }
                for i in range(len(P))
            ],
        }

    def test_chunk_anchor_highlights_exact_chunk(self):
        doc = self._doc()
        hl = _compute_highlights(doc, f"{DOC_ID}_semantic_2", None, None)
        assert len(hl) == 1
        assert doc["full_text"][hl[0]["start"]:hl[0]["end"]] == P[2]

    def test_snippet_anchor_with_label_prefix(self):
        doc = self._doc()
        snippet = f"[SECÇÃO I · pp. 1-2] {P[1]}"
        hl = _compute_highlights(doc, None, snippet, None)
        assert len(hl) == 1
        assert doc["full_text"][hl[0]["start"]:hl[0]["end"]] == P[1]

    def test_page_anchor_highlights_all_chunks_on_page(self):
        doc = self._doc()
        hl = _compute_highlights(doc, None, None, 2)
        covered = "".join(doc["full_text"][h["start"]:h["end"]] for h in hl)
        assert P[2] in covered and P[3] in covered
        assert P[0] not in covered

    def test_no_anchor_returns_empty(self):
        doc = self._doc()
        assert _compute_highlights(doc, None, None, None) == []

    def test_unfindable_snippet_returns_empty(self):
        doc = self._doc()
        assert _compute_highlights(doc, None, "texto inexistente xyz", None) == []


class TestDeduplicateByParent:
    """Citations derive :s from a result's id and :p from its page_start —
    _deduplicate_by_parent must keep both describing the same (best) chunk."""

    def _hits(self):
        return [
            {
                "id": "doc.pdf_semantic_10",
                "parent_id": "navy:doc.pdf",
                "similarity": 0.5,
                "matches": ["chunk on page 3"],
                "page_start": 3,
            },
            {
                "id": "doc.pdf_semantic_40",
                "parent_id": "navy:doc.pdf",
                "similarity": 0.9,
                "matches": ["chunk on page 9"],
                "page_start": 9,
            },
        ]

    def test_best_chunk_wins_id_and_page_together(self):
        from open_notebook.search.query import _deduplicate_by_parent

        out = _deduplicate_by_parent(self._hits(), limit=10)
        assert len(out) == 1
        assert out[0]["id"] == "doc.pdf_semantic_40"
        assert out[0]["page_start"] == 9
        assert out[0]["similarity"] == 0.9

    def test_lower_score_later_does_not_override(self):
        from open_notebook.search.query import _deduplicate_by_parent

        hits = list(reversed(self._hits()))
        out = _deduplicate_by_parent(hits, limit=10)
        assert len(out) == 1
        assert out[0]["id"] == "doc.pdf_semantic_40"
        assert out[0]["page_start"] == 9
