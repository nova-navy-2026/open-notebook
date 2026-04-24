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
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger
from pydantic import BaseModel

from open_notebook.config import DATA_FOLDER, NAVY_OPENSEARCH_INDEX

# NOVA-Researcher API base URL
NOVA_RESEARCHER_URL = os.environ.get("NOVA_RESEARCHER_URL", "http://localhost:3800").rstrip("/")


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
    use_amalia: bool = True  # Default to Amália model


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


# ── Persistent job store ──────────────────────────────────────────────

_jobs_file = os.path.join(DATA_FOLDER, "research_jobs.json")
_jobs: Dict[str, ResearchJob] = {}


def _save_jobs() -> None:
    """Persist all research jobs to disk as JSON."""
    try:
        os.makedirs(os.path.dirname(_jobs_file), exist_ok=True)
        data = {jid: job.model_dump() for jid, job in _jobs.items()}
        with open(_jobs_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
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
    return _jobs.get(job_id)


def _list_jobs() -> List[ResearchJob]:
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


# ── OpenSearch Pre-fetch via NOVA-Researcher API ──────────────────────


async def _prefetch_opensearch_docs(
    query: str, index: str, max_results: int = 30
) -> List[Dict[str, Any]]:
    """
    Pre-fetch documents from the navy OpenSearch corpus via the
    NOVA-Researcher /opensearch/prefetch endpoint.

    Returns a list of dicts with 'page_content' and 'metadata' keys.
    """
    try:
        resp = await _http_client.post(
            f"{NOVA_RESEARCHER_URL}/opensearch/prefetch",
            json={"query": query, "index": index, "max_results": max_results},
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


# ── Core Research Execution (via NOVA-Researcher API) ─────────────────


async def _run_ttd_dr(request: ResearchRequest, job_id: str, progress_callback=None) -> ResearchResult:
    """Execute research using the TTD-DR flow via the NOVA-Researcher API."""

    provider = await _resolve_model_provider(request.model_id)

    try:
        logger.info(
            f"Starting TTD-DR research job {job_id}: "
            f"query='{request.query[:80]}...', provider={provider or 'amalia(default)'}"
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
            "opensearch_index": NAVY_OPENSEARCH_INDEX,
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
                    report = _strip_references(event.get("report", ""))
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
            created_at=datetime.utcnow().isoformat(),
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

    # ── TTD-DR uses its own endpoint ──────────────────────────────────
    if request.report_type == ResearchReportType.TTD_DR:
        return await _run_ttd_dr(request, job_id, progress_callback=progress_callback)

    provider = await _resolve_model_provider(request.model_id)

    try:
        logger.info(
            f"Starting research job {job_id}: "
            f"query='{request.query[:80]}...', "
            f"type={request.report_type.value}, "
            f"provider={provider or 'amalia(default)'}"
        )

        if progress_callback:
            await progress_callback(10, "Fase 1: A obter documentos do OpenSearch...")

        # Pre-fetch from the navy OpenSearch corpus
        os_docs = await _prefetch_opensearch_docs(
            query=request.query,
            index=NAVY_OPENSEARCH_INDEX,
            max_results=int(os.environ.get("AMALIA_PREFETCH_DOCS", "30")),
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
            "source_urls": request.source_urls,
            "documents": os_docs,
            # Tell NOVA-Researcher which OpenSearch index this app uses so
            # that — on follow-up / cross-corpus queries — the server-side
            # CustomRetriever targets the right index.
            "opensearch_index": NAVY_OPENSEARCH_INDEX,
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

        report = _strip_references(data.get("report", ""))
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
            created_at=datetime.utcnow().isoformat(),
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
            created_at=datetime.utcnow().isoformat(),
        )


async def submit_research_job(request: ResearchRequest) -> ResearchJob:
    """
    Submit a research job for background execution.
    Returns immediately with a job ID for status tracking.
    """
    import asyncio

    job_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()

    job = ResearchJob(
        id=job_id,
        query=request.query,
        report_type=request.report_type.value,
        status="pending",
        created_at=now,
        tone=request.tone.value,
        model_id=request.model_id,
        notebook_id=request.notebook_id,
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
    _save_jobs()
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