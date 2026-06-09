"""
Researcher service - wraps GPTResearcher for use within OpenNotebook.

This service calls the NOVA-Researcher API server over HTTP instead of
importing its modules directly.  The server URL is configured via the
NOVA_RESEARCHER_URL environment variable (default: http://localhost:8001).
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger
from pydantic import BaseModel

from open_notebook.access_control import build_opensearch_filter
from open_notebook.config import DATA_FOLDER, NAVY_OPENSEARCH_INDEX

# NOVA-Researcher API base URL
NOVA_RESEARCHER_URL = os.environ.get("NOVA_RESEARCHER_URL", "http://localhost:3800").rstrip("/")
RESPONSE_LANGUAGE_POLICY = (
    "português europeu (pt-PT) por defeito; se o utilizador escrever claramente "
    "noutro idioma, responde nesse idioma"
)
# RESPONSE_LANGUAGE_POLICY = "português europeu (pt-PT)"


# ── Enums mirroring GPTResearcher's types ──────────────────────────────

class ResearchReportType(str, Enum):
    """Available report types from GPTResearcher."""
    RESEARCH_REPORT = "research_report"
    RESOURCE_REPORT = "resource_report"
    OUTLINE_REPORT = "outline_report"
    CUSTOM_REPORT = "custom_report"
    DETAILED_REPORT = "detailed_report"
    SUBTOPIC_REPORT = "subtopic_report"
    DEEP_RESEARCH = "deep"
    TTD_DR = "ttd_dr"
    REACT_DEEP = "react_deep"


class ResearchReportSource(str, Enum):
    """Available data sources for research."""
    WEB = "web"
    LOCAL = "local"
    HYBRID = "hybrid"
    LANGCHAIN_VECTORSTORE = "langchain_vectorstore"


class ResearchTone(str, Enum):
    """Available writing tones."""
    OBJECTIVE = "Objective"
    FORMAL = "Formal"
    ANALYTICAL = "Analytical"
    PERSUASIVE = "Persuasive"
    INFORMATIVE = "Informative"
    EXPLANATORY = "Explanatory"
    DESCRIPTIVE = "Descriptive"
    CRITICAL = "Critical"
    COMPARATIVE = "Comparative"
    SPECULATIVE = "Speculative"
    REFLECTIVE = "Reflective"
    NARRATIVE = "Narrative"
    SIMPLE = "Simple"
    CASUAL = "Casual"


# ── Request / Response Models ──────────────────────────────────────────

class ResearchRequest(BaseModel):
    """Request to generate a research report."""
    query: str
    report_type: ResearchReportType = ResearchReportType.RESEARCH_REPORT
    report_source: ResearchReportSource = ResearchReportSource.WEB
    tone: ResearchTone = ResearchTone.OBJECTIVE
    source_urls: List[str] = []
    notebook_id: Optional[str] = None
    model_id: Optional[str] = None
    use_amalia: bool = True  # Default to Amalia model
    # Authenticated user id (e.g. "m24409"). Used to build the navy
    # OpenSearch access-control filter (classification + department).
    user_id: Optional[str] = None


class RetrievedDocument(BaseModel):
    """A document retrieved during research."""
    title: str = ""
    source: str = ""
    snippet: str = ""


class ResearchResult(BaseModel):
    """Result of a completed research job."""
    id: str
    query: str
    report_type: str
    report: str
    source_urls: List[str] = []
    research_costs: float = 0.0
    images: List[str] = []
    status: str = "completed"
    created_at: str = ""
    error: Optional[str] = None
    tone: Optional[str] = None
    model_id: Optional[str] = None
    retrieved_documents: List[RetrievedDocument] = []


class ResearchJob(BaseModel):
    """A research job with tracking info."""
    id: str
    query: str
    report_type: str
    status: str = "pending"  # pending, running, completed, failed
    progress: str = ""
    progress_pct: int = 0  # 0-100 percentage for progress bar
    result: Optional[ResearchResult] = None
    created_at: str = ""
    error: Optional[str] = None
    tone: Optional[str] = None
    model_id: Optional[str] = None
    notebook_id: Optional[str] = None
    # Authenticated user id this job belongs to. Used to enforce that users
    # only see / poll / delete their own research reports.
    user_id: Optional[str] = None


# ── Persistent job store ──────────────────────────────────────────────

_jobs_file = os.path.join(DATA_FOLDER, "research_jobs.json")
_jobs: Dict[str, ResearchJob] = {}


def _save_jobs(_deleted: Optional[set] = None) -> None:
    """Persist all research jobs to disk as JSON (atomic write via temp-file + rename).

    Merges this worker's in-memory jobs with whatever is already on disk so we
    never lose jobs owned by other Uvicorn workers when running with multiple
    processes.

    Pass ``_deleted`` (a set of job IDs) to explicitly remove those entries from
    the disk state before writing.  Without this, a job deleted from ``_jobs``
    would be re-read from disk during the merge and silently restored.
    """
    try:
        dir_ = os.path.dirname(_jobs_file)
        os.makedirs(dir_, exist_ok=True)

        # Start from what's on disk (jobs owned by other workers) …
        merged: Dict[str, dict] = {}
        if os.path.exists(_jobs_file):
            try:
                with open(_jobs_file, "r", encoding="utf-8") as f:
                    merged = json.load(f) or {}
            except Exception:
                merged = {}

        # Remove any explicitly deleted jobs from the on-disk state BEFORE the
        # in-memory overlay — otherwise they would be resurrected from disk.
        if _deleted:
            for jid in _deleted:
                merged.pop(jid, None)

        # … then overlay this worker's view (we own the latest state for our jobs).
        for jid, job in _jobs.items():
            merged[jid] = job.model_dump()

        # Write to a sibling temp file then rename so readers on other workers
        # never see a truncated / partially-written file.
        import tempfile
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp_path, _jobs_file)  # atomic on POSIX
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as exc:
        logger.warning(f"Could not save research jobs to disk: {exc}")


def _load_jobs() -> None:
    """Load persisted research jobs from disk on startup.

    Any job left in ``pending`` or ``running`` state is considered orphaned
    (the API process died mid-execution) and is marked as ``failed`` so the
    UI does not show a forever-spinning progress bar.
    """
    if not os.path.exists(_jobs_file):
        return
    try:
        with open(_jobs_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        _jobs.update({jid: ResearchJob.model_validate(job) for jid, job in data.items()})

        orphaned = 0
        for job in _jobs.values():
            if job.status in ("pending", "running"):
                job.status = "failed"
                job.error = "Interrupted: server restarted while job was running"
                job.progress = "Falhou (servidor reiniciado)"
                orphaned += 1
        if orphaned:
            _save_jobs()
            logger.warning(f"Marked {orphaned} orphaned research job(s) as failed on startup")

        logger.info(f"Loaded {len(_jobs)} research jobs from disk")
    except Exception as exc:
        logger.warning(f"Could not load research jobs from disk: {exc}")


_load_jobs()


def _get_job(job_id: str) -> Optional[ResearchJob]:
    job = _jobs.get(job_id)
    if job is not None:
        return job
    # Job may have been created by a different Uvicorn worker — fall back to disk.
    # Retry a few times with brief sleeps to survive a concurrent atomic rename.
    import time
    for attempt in range(4):
        try:
            if os.path.exists(_jobs_file):
                with open(_jobs_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if job_id in data:
                    loaded = ResearchJob.model_validate(data[job_id])
                    _jobs[job_id] = loaded  # cache locally for subsequent polls
                    return loaded
        except Exception as exc:
            logger.debug(f"Could not reload job {job_id} from disk (attempt {attempt+1}): {exc}")
        if attempt < 3:
            time.sleep(0.05 * (2 ** attempt))  # 50ms, 100ms, 200ms
    return None


def _list_jobs() -> List[ResearchJob]:
    # Merge any jobs persisted by other workers that we haven't seen yet.
    try:
        if os.path.exists(_jobs_file):
            with open(_jobs_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for jid, raw in data.items():
                if jid not in _jobs:
                    _jobs[jid] = ResearchJob.model_validate(raw)
    except Exception as exc:
        logger.debug(f"Could not merge jobs from disk: {exc}")
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


# ── HTTP client for NOVA-Researcher API ───────────────────────────────

_http_client = httpx.AsyncClient(timeout=600.0)  # 10 min for long research


# ── Model provider resolution ────────────────────────────────────────

async def _resolve_model_provider(model_id: Optional[str]) -> Optional[str]:
    """Look up a model's provider from the database.

    Returns the provider string (e.g. 'amalia', 'ollama') or None.
    """
    if not model_id:
        return None
    try:
        from open_notebook.ai.models import Model
        model = await Model.get(model_id)
        return model.provider if model else None
    except Exception as e:
        logger.warning(f"Could not resolve model provider for {model_id}: {e}")
        return None


def _provider_for_request(request: ResearchRequest) -> Optional[str]:
    """Resolve the NOVA provider while preserving the legacy use_amalia flag."""
    # model_id resolution is async, so callers pass through _resolve_model_provider
    # first and use this only for the legacy fallback.
    return "amalia" if request.use_amalia else None


# ── OpenSearch Pre-fetch via NOVA-Researcher API ──────────────────────


async def _prefetch_opensearch_docs(
    query: str, index: str, max_results: int = 30, user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Pre-fetch documents from the navy OpenSearch corpus via the
    NOVA-Researcher /opensearch/prefetch endpoint.

    Returns a list of dicts with 'page_content' and 'metadata' keys.
    """
    try:
        resp = await _http_client.post(
            f"{NOVA_RESEARCHER_URL}/opensearch/prefetch",
            json={
                "query": query,
                "index": index,
                "max_results": max_results,
                "retriever_filter": build_opensearch_filter(user_id),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("documents", [])
        logger.info(f"Pre-fetched {len(docs)} docs from OpenSearch via API")
        return docs
    except Exception as exc:
        logger.error(f"OpenSearch pre-fetch via API failed: {exc}")
        return []


def _strip_references(report: str) -> str:
    """
    Post-process a generated report to remove:
    - Reference / bibliography sections at the end
    - In-text citation markers like [1], [2], (in-text citation), etc.
    - Trailing "Notas Finais" or similar filler sections with fabricated references
    """
    # Remove reference/bibliography sections at the end of the report.
    # Match common headers in both English and Portuguese.
    ref_pattern = re.compile(
        r'\n#{1,3}\s*'
        r'(Refer[eê]ncias(\s+Bibliogr[aá]ficas)?'
        r'|Bibliography'
        r'|References'
        r'|Sources'
        r'|Fontes'
        r'|Notas\s+Finais'
        r'|Referências\s+Bibliográficas)'
        r'\s*\n.*',
        re.IGNORECASE | re.DOTALL,
    )
    report = ref_pattern.sub('', report)

    # Remove in-text citation numbers like [1], [2], [1,2], [1-3]
    report = re.sub(r'\s*\[[\d,\s\-]+\]', '', report)

    # Remove APA-style in-text citations like ([in-text citation](url)) or (in-text citation)
    report = re.sub(r'\s*\(\[?[^)]*in-text citation[^)]*\]?\)', '', report, flags=re.IGNORECASE)

    # Remove markdown hyperlink citations at end of sentences like ([Title](url))
    # but only when they look like citation references (at end of sentence before period)
    report = re.sub(r'\s*\(\[[^\]]+\]\([^)]+\)\)\.?', '', report)

    # Clean up any trailing whitespace
    report = report.rstrip()

    return report


_BARE_SECTION_RE = re.compile(
    r"^\s*(?:\*\*)?\s*("
    r"resumo\s+executivo|sum[aá]rio\s+executivo|introdu[cç][aã]o|enquadramento|contexto|metodologia|"
    r"evid[eê]ncia(?:\s+e\s+an[aá]lise)?|desenvolvimento|an[aá]lise|discuss[aã]o|resultados|"
    r"principais\s+conclus[oõ]es|conclus[aã]o|recomenda[cç][oõ]es|implica[cç][oõ]es|"
    r"limita[cç][oõ]es|s[ií]ntese|procedimentos(?:\s+de\s+.+)?|promo[cç][aã]o(?:\s+de\s+.+)?|"
    r"executive\s+summary|introduction|background|context|methodology|evidence(?:\s+and\s+analysis)?|"
    r"analysis|discussion|findings|results|recommendations|implications|limitations|conclusion|summary"
    r")\s*(?:\*\*)?\s*:?\s*$",
    flags=re.IGNORECASE,
)


def _is_likely_bare_heading(line: str) -> bool:
    stripped = line.strip().strip("*")
    if not stripped:
        return False
    if _BARE_SECTION_RE.match(stripped):
        return True
    if len(stripped) > 100 or re.search(r"[.!?]\s*$", stripped):
        return False
    if re.match(r"^(?:[-*+>]|\d+[.)]\s+|\|)", stripped):
        return False
    if re.search(r"https?://|`|\[[^\]]+\]\([^)]+\)", stripped):
        return False
    if ":" in stripped and not stripped.endswith(":"):
        return False
    words = stripped.rstrip(":").split()
    if not 1 <= len(words) <= 12:
        return False
    return stripped[0].isupper() or stripped[0].isdigit()


def _normalize_report_headings(report: str, fallback_title: str = "") -> str:
    """Ensure plain-text report section titles become Markdown headings."""
    report = (report or "").strip()
    if not report:
        return report

    lines = report.splitlines()
    output: List[str] = []
    in_fence = False
    first_content_seen = False
    has_h1 = bool(re.search(r"(?m)^#\s+\S", report))

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            output.append(line)
            continue
        if in_fence or not stripped:
            output.append(line)
            continue
        if stripped.startswith("#"):
            output.append(line)
            first_content_seen = True
            continue

        prev_blank = index == 0 or not lines[index - 1].strip()
        next_blank = index + 1 >= len(lines) or not lines[index + 1].strip()
        if not first_content_seen and not has_h1 and len(stripped) <= 140 and not re.search(r"[.!?]\s*$", stripped):
            output.append(f"# {stripped.rstrip(':')}")
            first_content_seen = True
            has_h1 = True
            continue
        if first_content_seen and (prev_blank or next_blank) and _is_likely_bare_heading(stripped):
            output.append(f"## {stripped.rstrip(':')}")
            continue

        output.append(line)
        first_content_seen = True

    normalized = "\n".join(output).strip()
    if not has_h1:
        title = (fallback_title or "Relatório de investigação").strip().rstrip(" ,.;:-")
        normalized = f"# {title}\n\n{normalized}"
    if not re.search(r"(?m)^#{2,3}\s+\S", normalized):
        normalized = re.sub(r"(?m)^(#\s+.+)\n+", r"\1\n\n## Síntese\n\n", normalized, count=1)
    return normalized


# ── Core Research Execution (via NOVA-Researcher API) ─────────────────


async def _run_ttd_dr(request: ResearchRequest, job_id: str, progress_callback=None) -> ResearchResult:
    """Execute research using the TTD-DR flow via the NOVA-Researcher API."""

    provider = await _resolve_model_provider(request.model_id) or _provider_for_request(request)

    try:
        logger.info(
            f"Starting TTD-DR research job {job_id}: "
            f"query='{request.query[:80]}...', provider={provider or 'gemma(default)'}"
        )

        if progress_callback:
            await progress_callback(5, "A iniciar TTD-DR...")

        # NOTE: We deliberately do NOT pre-fetch from OpenSearch here.
        # The TTD-DR flow (NOVA-Researcher) runs its own per-sub-query
        # retrieval against the same index via CustomRetriever, so a
        # client-side prefetch would be a wasted round-trip whose results
        # are never consumed by the LLM. The full source set is returned
        # in `source_urls` on the `done` event.

        if progress_callback:
            await progress_callback(15, "A executar TTD-DR...")

        # Call NOVA-Researcher TTD-DR endpoint via SSE so we can forward
        # real-time progress events (pct + message) to the UI.
        payload = {
            "query": request.query,
            "source_urls": request.source_urls,
            "language": RESPONSE_LANGUAGE_POLICY,
            "opensearch_index": NAVY_OPENSEARCH_INDEX,
            "retriever_filter": build_opensearch_filter(request.user_id),
        }
        params: Dict[str, Any] = {"stream": "true"}
        if provider:
            params["provider"] = provider

        report = ""
        source_urls: List[str] = []
        stream_error: Optional[str] = None

        async with _http_client.stream(
            "POST",
            f"{NOVA_RESEARCHER_URL}/research/ttd-dr",
            json=payload,
            params=params,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                if not raw_line or not raw_line.startswith("data:"):
                    continue  # skip heartbeats / blank separators
                try:
                    event = json.loads(raw_line[5:].strip())
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")
                if etype == "progress":
                    if progress_callback:
                        # Server pct is 0-100 over the TTD-DR phase. Map it
                        # into the 15-95 band so the prefetch (5) and
                        # finalize (95) bookends stay monotonic.
                        server_pct = int(event.get("pct", 0))
                        mapped = 15 + int(server_pct * 0.80)
                        await progress_callback(
                            min(mapped, 95),
                            str(event.get("message", "")),
                        )
                elif etype == "done":
                    report = _normalize_report_headings(
                        _strip_references(event.get("report", "")),
                        fallback_title=request.query,
                    )
                    source_urls = event.get("source_urls", []) or []
                elif etype == "error":
                    stream_error = str(event.get("detail", "Unknown TTD-DR error"))

        if stream_error:
            raise RuntimeError(stream_error)

        if progress_callback:
            await progress_callback(95, "A finalizar...")

        # Build retrieved documents list for the UI from the page-level
        # sources that TTD-DR collected during its iterative retrieval.
        # Snippets are not available here — the UI shows source filename
        # + page reference, which is what users care about.
        retrieved_docs = [
            RetrievedDocument(title=s, source=s, snippet="")
            for s in source_urls
            if s
        ]

        result = ResearchResult(
            id=job_id,
            query=request.query,
            report_type="ttd_dr",
            report=report,
            source_urls=source_urls,
            research_costs=0.0,
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
            tone=request.tone.value,
            model_id=request.model_id,
            retrieved_documents=retrieved_docs,
        )

        logger.success(
            f"Job {job_id}: TTD-DR research completed. "
            f"Report length: {len(report)} chars, Sources: {len(source_urls)}"
        )
        return result

    except Exception as e:
        logger.error(f"Job {job_id}: TTD-DR research failed: {e}")
        return ResearchResult(
            id=job_id,
            query=request.query,
            report_type="ttd_dr",
            report="",
            status="failed",
            error=str(e),
            created_at=datetime.now(timezone.utc).isoformat(),
        )


async def _run_react_dr(request: ResearchRequest, job_id: str, progress_callback=None) -> ResearchResult:
    """Execute research using the ReAct-DR flow via the NOVA-Researcher API."""

    provider = await _resolve_model_provider(request.model_id)

    try:
        logger.info(
            f"Starting ReAct-DR research job {job_id}: "
            f"query='{request.query[:80]}...', provider={provider or 'amalia(default)'}"
        )

        if progress_callback:
            await progress_callback(5, "A iniciar ReAct-DR...")

        if progress_callback:
            await progress_callback(15, "A executar ReAct-DR...")

        payload = {
            "query": request.query,
            "source_urls": request.source_urls,
            "opensearch_index": NAVY_OPENSEARCH_INDEX,
            "retriever_filter": build_opensearch_filter(request.user_id),
        }
        params: Dict[str, Any] = {"stream": "true"}
        if provider:
            params["provider"] = provider

        report = ""
        source_urls: List[str] = []
        stream_error: Optional[str] = None

        async with _http_client.stream(
            "POST",
            f"{NOVA_RESEARCHER_URL}/research/react-dr",
            json=payload,
            params=params,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                try:
                    event = json.loads(raw_line[5:].strip())
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")
                if etype == "progress":
                    if progress_callback:
                        server_pct = int(event.get("pct", 0))
                        mapped = 15 + int(server_pct * 0.80)
                        await progress_callback(
                            min(mapped, 95),
                            str(event.get("message", "")),
                        )
                elif etype == "done":
                    report = _strip_references(event.get("report", ""))
                    source_urls = event.get("source_urls", []) or []
                elif etype == "error":
                    stream_error = str(event.get("detail", "Unknown ReAct-DR error"))

        if stream_error:
            raise RuntimeError(stream_error)

        if progress_callback:
            await progress_callback(95, "A finalizar...")

        retrieved_docs = [
            RetrievedDocument(title=s, source=s, snippet="")
            for s in source_urls
            if s
        ]

        result = ResearchResult(
            id=job_id,
            query=request.query,
            report_type="react_deep",
            report=report,
            source_urls=source_urls,
            research_costs=0.0,
            status="completed",
            created_at=datetime.utcnow().isoformat(),
            tone=request.tone.value,
            model_id=request.model_id,
            retrieved_documents=retrieved_docs,
        )

        logger.success(
            f"Job {job_id}: ReAct-DR research completed. "
            f"Report length: {len(report)} chars, Sources: {len(source_urls)}"
        )
        return result

    except Exception as e:
        logger.error(f"Job {job_id}: ReAct-DR research failed: {e}")
        return ResearchResult(
            id=job_id,
            query=request.query,
            report_type="react_deep",
            report="",
            status="failed",
            error=str(e),
            created_at=datetime.now(timezone.utc).isoformat(),
        )


async def _run_react_dr(request: ResearchRequest, job_id: str, progress_callback=None) -> ResearchResult:
    """Execute research using the ReAct-DR flow via the NOVA-Researcher API."""

    provider = await _resolve_model_provider(request.model_id)

    try:
        logger.info(
            f"Starting ReAct-DR research job {job_id}: "
            f"query='{request.query[:80]}...', provider={provider or 'amalia(default)'}"
        )

        if progress_callback:
            await progress_callback(5, "A iniciar ReAct-DR...")

        if progress_callback:
            await progress_callback(15, "A executar ReAct-DR...")

        payload = {
            "query": request.query,
            "source_urls": request.source_urls,
            "opensearch_index": NAVY_OPENSEARCH_INDEX,
            "retriever_filter": build_opensearch_filter(request.user_id),
        }
        params: Dict[str, Any] = {"stream": "true"}
        if provider:
            params["provider"] = provider

        report = ""
        source_urls: List[str] = []
        stream_error: Optional[str] = None

        async with _http_client.stream(
            "POST",
            f"{NOVA_RESEARCHER_URL}/research/react-dr",
            json=payload,
            params=params,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                try:
                    event = json.loads(raw_line[5:].strip())
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")
                if etype == "progress":
                    if progress_callback:
                        server_pct = int(event.get("pct", 0))
                        mapped = 15 + int(server_pct * 0.80)
                        await progress_callback(
                            min(mapped, 95),
                            str(event.get("message", "")),
                        )
                elif etype == "done":
                    report = _strip_references(event.get("report", ""))
                    source_urls = event.get("source_urls", []) or []
                elif etype == "error":
                    stream_error = str(event.get("detail", "Unknown ReAct-DR error"))

        if stream_error:
            raise RuntimeError(stream_error)

        if progress_callback:
            await progress_callback(95, "A finalizar...")

        retrieved_docs = [
            RetrievedDocument(title=s, source=s, snippet="")
            for s in source_urls
            if s
        ]

        result = ResearchResult(
            id=job_id,
            query=request.query,
            report_type="react_deep",
            report=report,
            source_urls=source_urls,
            research_costs=0.0,
            status="completed",
            created_at=datetime.utcnow().isoformat(),
            tone=request.tone.value,
            model_id=request.model_id,
            retrieved_documents=retrieved_docs,
        )

        logger.success(
            f"Job {job_id}: ReAct-DR research completed. "
            f"Report length: {len(report)} chars, Sources: {len(source_urls)}"
        )
        return result

    except Exception as e:
        logger.error(f"Job {job_id}: ReAct-DR research failed: {e}")
        return ResearchResult(
            id=job_id,
            query=request.query,
            report_type="react_deep",
            report="",
            status="failed",
            error=str(e),
            created_at=datetime.utcnow().isoformat(),
        )


async def run_research(request: ResearchRequest, progress_callback=None) -> ResearchResult:
    """
    Execute a research query via the NOVA-Researcher API.

    This is the main entry point for running research. It handles:
    - Resolving the model provider (Amália or Qwen3/Ollama)
    - Pre-fetching context from the navy OpenSearch corpus
    - Calling the NOVA-Researcher /research endpoint
    - Post-processing to strip hallucinated references
    """
    job_id = str(uuid.uuid4())[:8]

    # ── TTD-DR and ReAct-DR use their own endpoints ───────────────────
    if request.report_type == ResearchReportType.TTD_DR:
        return await _run_ttd_dr(request, job_id, progress_callback=progress_callback)

    if request.report_type == ResearchReportType.REACT_DEEP:
        return await _run_react_dr(request, job_id, progress_callback=progress_callback)

    provider = await _resolve_model_provider(request.model_id)
    provider = await _resolve_model_provider(request.model_id) or _provider_for_request(request)

    try:
        logger.info(
            f"Starting research job {job_id}: "
            f"query='{request.query[:80]}...', "
            f"type={request.report_type.value}, "
            f"provider={provider or 'gemma(default)'}"
        )

        if progress_callback:
            await progress_callback(10, "Fase 1: A obter documentos do OpenSearch...")

        # Pre-fetch from the navy OpenSearch corpus
        os_docs = await _prefetch_opensearch_docs(
            query=request.query,
            index=NAVY_OPENSEARCH_INDEX,
            max_results=int(os.environ.get("AMALIA_PREFETCH_DOCS", "30")),
            user_id=request.user_id,
        )

        if os_docs:
            logger.info(f"Job {job_id}: Using {len(os_docs)} pre-fetched OpenSearch docs.")
        else:
            logger.warning(f"Job {job_id}: OpenSearch returned no docs; falling back to web search.")

        if progress_callback:
            await progress_callback(20, "Fase 2: A executar pesquisa...")

        # Build request payload for the NOVA-Researcher API
        payload = {
            "query": request.query,
            "report_type": request.report_type.value,
            "report_source": "langchain_documents" if os_docs else request.report_source.value,
            "tone": request.tone.value,
            "language": RESPONSE_LANGUAGE_POLICY,
            "source_urls": request.source_urls,
            "documents": os_docs,
            # Tell NOVA-Researcher which OpenSearch index this app uses so
            # that — on follow-up / cross-corpus queries — the server-side
            # CustomRetriever targets the right index.
            "opensearch_index": NAVY_OPENSEARCH_INDEX,
            # Navy-specific access-control filter (classification +
            # department). NOVA-Researcher applies it verbatim as the
            # OpenSearch kNN filter.
            "retriever_filter": build_opensearch_filter(request.user_id),
        }

        resp = await _http_client.post(
            f"{NOVA_RESEARCHER_URL}/research",
            json=payload,
            params={"provider": provider} if provider else {},
        )
        resp.raise_for_status()
        data = resp.json()

        if progress_callback:
            await progress_callback(90, "Fase 3: A processar e finalizar relatório...")

        report = _normalize_report_headings(
            _strip_references(data.get("report", "")),
            fallback_title=request.query,
        )
        source_urls = data.get("source_urls", [])
        costs = data.get("costs", 0.0)
        images = data.get("images", [])

        # Fallback source URLs from pre-fetched docs
        if not source_urls and os_docs:
            source_urls = [
                d.get("metadata", {}).get("source", "")
                for d in os_docs
                if d.get("metadata", {}).get("source")
            ]

        # Build retrieved documents list for the UI.
        # Merge in any extra source urls the server returned that aren't
        # already represented by the prefetched OpenSearch docs.
        retrieved_docs = [
            RetrievedDocument(
                title=d.get("metadata", {}).get("title", ""),
                source=d.get("metadata", {}).get("source", ""),
                snippet=(d.get("page_content", ""))[:300],
            )
            for d in os_docs
        ]
        existing_sources = {rd.source for rd in retrieved_docs if rd.source}
        for s in source_urls:
            if s and s not in existing_sources:
                retrieved_docs.append(
                    RetrievedDocument(title=s, source=s, snippet="")
                )
                existing_sources.add(s)

        result = ResearchResult(
            id=job_id,
            query=request.query,
            report_type=request.report_type.value,
            report=report,
            source_urls=source_urls,
            research_costs=costs,
            images=images,
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
            tone=request.tone.value,
            model_id=request.model_id,
            retrieved_documents=retrieved_docs,
        )

        logger.success(
            f"Job {job_id}: Research completed. "
            f"Report length: {len(report)} chars, "
            f"Sources: {len(source_urls)}, "
            f"Cost: ${costs:.4f}"
        )

        return result

    except Exception as e:
        logger.error(f"Job {job_id}: Research failed: {e}")
        return ResearchResult(
            id=job_id,
            query=request.query,
            report_type=request.report_type.value,
            report="",
            status="failed",
            error=str(e),
            created_at=datetime.now(timezone.utc).isoformat(),
        )


async def submit_research_job(request: ResearchRequest) -> ResearchJob:
    """
    Submit a research job for background execution.
    Returns immediately with a job ID for status tracking.
    """
    import asyncio

    job_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    job = ResearchJob(
        id=job_id,
        query=request.query,
        report_type=request.report_type.value,
        status="pending",
        created_at=now,
        tone=request.tone.value,
        model_id=request.model_id,
        notebook_id=request.notebook_id,
        user_id=request.user_id,
    )
    _jobs[job_id] = job
    _save_jobs()

    async def _run():
        job.status = "running"
        job.progress = "A conduzir pesquisa..."
        job.progress_pct = 5
        _save_jobs()

        async def _progress_callback(pct: int, message: str) -> None:
            """Update job progress in-place so polling clients see live updates."""
            job.progress_pct = pct
            job.progress = message
            _save_jobs()

        try:
            result = await run_research(request, progress_callback=_progress_callback)
            job.result = result
            job.status = result.status
            job.error = result.error
            job.progress = "Concluído" if result.status == "completed" else "Falhou"
            job.progress_pct = 100 if result.status == "completed" else job.progress_pct

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.progress = f"Falhou: {e}"
        finally:
            _save_jobs()

    # Run in background
    asyncio.create_task(_run())

    return job


def get_research_job(job_id: str) -> Optional[ResearchJob]:
    """Get a research job by ID."""
    return _get_job(job_id)


def list_research_jobs() -> List[ResearchJob]:
    """List all research jobs, most recent first."""
    return _list_jobs()


def delete_research_job(job_id: str) -> bool:
    """Delete a research job by ID. Returns True if deleted, False if not found."""
    if job_id not in _jobs:
        return False
    del _jobs[job_id]
    # Pass the deleted ID so _save_jobs() removes it from the disk state before
    # writing — without this the merge would read the job back from disk and
    # restore it, making the deletion appear to succeed but then immediately
    # reappear in the job list.
    _save_jobs(_deleted={job_id})
    return True


def get_report_type_info() -> List[Dict[str, str]]:
    """Return metadata about available report types for the UI."""
    return [
        {
            "value": "research_report",
            "label": "Research Report",
            "description": "Comprehensive research report with analysis (~1200 words)",
            "speed": "medium",
        },
        {
            "value": "resource_report",
            "label": "Resource Report",
            "description": "Lists and describes the most relevant resources on the topic",
            "speed": "quick",
        },
        {
            "value": "outline_report",
            "label": "Outline Report",
            "description": "Structured hierarchical outline of the research topic",
            "speed": "quick",
        },
        {
            "value": "custom_report",
            "label": "Custom Report",
            "description": "Flexible user-defined report — adapts to your prompt instructions",
            "speed": "medium",
        },
        {
            "value": "detailed_report",
            "label": "Detailed Report",
            "description": "In-depth multi-subtopic analysis with thorough coverage",
            "speed": "slow",
        },
        {
            "value": "subtopic_report",
            "label": "Subtopic Report",
            "description": "Deep dive into a single subtopic within a broader subject",
            "speed": "medium",
        },
        {
            "value": "deep",
            "label": "Deep Research",
            "description": "Recursive multi-layer exploration with extensive analysis",
            "speed": "slow",
        },
        {
            "value": "ttd_dr",
            "label": "TTD-DR Deep Research",
            "description": "Iterative Draft Denoising — generates, reviews and expands a structured report (~2500+ words, pt-PT)",
            "speed": "slow",
        },
        {
            "value": "react_deep",
            "label": "ReAct Deep Research",
            "description": "ReAct (Reason + Act) loop — interleaved thought/retrieval/observation cycles before writing the final report",
            "speed": "slow",
        },
    ]


def get_tone_info() -> List[Dict[str, str]]:
    """Return metadata about available tones for the UI."""
    return [
        {"value": "Objective", "label": "Objective", "description": "Impartial and unbiased"},
        {"value": "Formal", "label": "Formal", "description": "Academic standards"},
        {"value": "Analytical", "label": "Analytical", "description": "Critical evaluation"},
        {"value": "Persuasive", "label": "Persuasive", "description": "Convincing viewpoint"},
        {"value": "Informative", "label": "Informative", "description": "Clear and comprehensive"},
        {"value": "Explanatory", "label": "Explanatory", "description": "Clarifying complex concepts"},
        {"value": "Descriptive", "label": "Descriptive", "description": "Detailed depiction"},
        {"value": "Critical", "label": "Critical", "description": "Judging validity"},
        {"value": "Comparative", "label": "Comparative", "description": "Juxtaposing theories/data"},
        {"value": "Speculative", "label": "Speculative", "description": "Exploring hypotheses"},
        {"value": "Reflective", "label": "Reflective", "description": "Personal insights"},
        {"value": "Narrative", "label": "Narrative", "description": "Story-telling"},
        {"value": "Simple", "label": "Simple", "description": "Young readers, basic vocab"},
        {"value": "Casual", "label": "Casual", "description": "Conversational and relaxed"},
    ]


def get_source_info() -> List[Dict[str, str]]:
    """Return metadata about available report sources for the UI."""
    return [
        {"value": "web", "label": "Web", "description": "Search and scrape content from the web"},
        {"value": "local", "label": "Local Documents", "description": "Use local documents and files"},
        {"value": "hybrid", "label": "Hybrid", "description": "Combine web and local sources"},
        {
            "value": "langchain_vectorstore",
            "label": "Vector Store",
            "description": "Use vector store for retrieval (e.g., OpenSearch)",
        },
    ]
