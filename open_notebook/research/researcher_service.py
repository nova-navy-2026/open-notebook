"""
Researcher service - wraps GPTResearcher for use within OpenNotebook.

This service provides an async interface to run research using the
NOVA-Researcher GPTResearcher agent, supporting all report types,
tones, and sources including the Amália model.
"""

import json
import os
import sys
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel

from open_notebook.config import DATA_FOLDER, NAVY_OPENSEARCH_INDEX

# Add NOVA-Researcher to Python path so we can import gpt_researcher
_nova_researcher_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "NOVA-Researcher")
)
if _nova_researcher_path not in sys.path:
    sys.path.insert(0, _nova_researcher_path)


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
    use_amalia: bool = True  # Default to Amália model


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


class ResearchJob(BaseModel):
    """A research job with tracking info."""
    id: str
    query: str
    report_type: str
    status: str = "pending"  # pending, running, completed, failed
    progress: str = ""
    result: Optional[ResearchResult] = None
    created_at: str = ""
    error: Optional[str] = None


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
    """Load persisted research jobs from disk on startup."""
    if not os.path.exists(_jobs_file):
        return
    try:
        with open(_jobs_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        _jobs.update({jid: ResearchJob.model_validate(job) for jid, job in data.items()})
        logger.info(f"Loaded {len(_jobs)} research jobs from disk")
    except Exception as exc:
        logger.warning(f"Could not load research jobs from disk: {exc}")


_load_jobs()


def _get_job(job_id: str) -> Optional[ResearchJob]:
    return _jobs.get(job_id)


def _list_jobs() -> List[ResearchJob]:
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


# ── Amália Environment Setup ──────────────────────────────────────────

def _setup_amalia_env_llm_only():
    """Configure only the LLM-related env vars for Amália (no retriever override)."""
    amalia_vars = {
        "OPENAI_API_KEY": os.environ.get("AMALIA_API_KEY", "dummy"),
        "OPENAI_BASE_URL": os.environ.get(
            "AMALIA_BASE_URL", "https://amalia.novasearch.org/vlm/v1"
        ),
        "SMART_LLM": os.environ.get(
            "AMALIA_SMART_LLM", "openai:carminho/AMALIA-9B-50-DPO"
        ),
        "FAST_LLM": os.environ.get(
            "AMALIA_FAST_LLM", "openai:carminho/AMALIA-9B-50-DPO"
        ),
        "STRATEGIC_LLM": os.environ.get(
            "AMALIA_STRATEGIC_LLM", "openai:carminho/AMALIA-9B-50-DPO"
        ),
        # Amália's VLM endpoint does not serve an embeddings API.
        # Use a local HuggingFace model so compression/similarity steps work.
        "EMBEDDING": os.environ.get(
            "AMALIA_EMBEDDING",
            "huggingface:sentence-transformers/all-MiniLM-L6-v2",
        ),
    }
    for key, value in amalia_vars.items():
        os.environ[key] = value
    logger.info("Amália LLM environment configured (retriever unchanged)")


def _setup_amalia_env():
    """Configure environment variables for the Amália model."""
    amalia_vars = {
        "OPENAI_API_KEY": os.environ.get("AMALIA_API_KEY", "dummy"),
        "OPENAI_BASE_URL": os.environ.get(
            "AMALIA_BASE_URL", "https://amalia.novasearch.org/vlm/v1"
        ),
        "SMART_LLM": os.environ.get(
            "AMALIA_SMART_LLM", "openai:carminho/AMALIA-9B-50-DPO"
        ),
        "FAST_LLM": os.environ.get(
            "AMALIA_FAST_LLM", "openai:carminho/AMALIA-9B-50-DPO"
        ),
        "STRATEGIC_LLM": os.environ.get(
            "AMALIA_STRATEGIC_LLM", "openai:carminho/AMALIA-9B-50-DPO"
        ),
        "RETRIEVER": os.environ.get("AMALIA_RETRIEVER", "custom"),
        "OPENSEARCH_INDEX": NAVY_OPENSEARCH_INDEX,
        # Amália's VLM endpoint does not serve an embeddings API.
        # Use a local HuggingFace model so compression/similarity steps work.
        "EMBEDDING": os.environ.get(
            "AMALIA_EMBEDDING",
            "huggingface:sentence-transformers/all-MiniLM-L6-v2",
        ),
    }
    for key, value in amalia_vars.items():
        os.environ[key] = value
    logger.info("Amália environment configured for research")


def _restore_env(saved_env: Dict[str, Optional[str]]):
    """Restore original environment variables."""
    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ── Core Research Execution ───────────────────────────────────────────


async def _run_ttd_dr(request: ResearchRequest, job_id: str) -> ResearchResult:
    """Execute research using the TTD-DR (Iterative Draft Denoising) flow."""
    import importlib.util

    # Direct import to avoid backend.report_type.__init__ which pulls in
    # FastAPI/WebSocket and other NOVA-Researcher backend deps.
    _ttd_spec = importlib.util.spec_from_file_location(
        "ttd_dr",
        os.path.join(_nova_researcher_path, "backend", "report_type", "ttd_dr", "ttd_dr.py"),
    )
    _ttd_mod = importlib.util.module_from_spec(_ttd_spec)
    _ttd_spec.loader.exec_module(_ttd_mod)
    TTDDeepResearchFlow = _ttd_mod.TTDDeepResearchFlow

    saved_env: Dict[str, Optional[str]] = {}
    if request.use_amalia:
        for key in [
            "OPENAI_API_KEY", "OPENAI_BASE_URL", "SMART_LLM", "FAST_LLM",
            "STRATEGIC_LLM", "RETRIEVER", "OPENSEARCH_INDEX", "EMBEDDING",
        ]:
            saved_env[key] = os.environ.get(key)
        # Full env setup: LLM + RETRIEVER=custom + OPENSEARCH_INDEX so the
        # custom (OpenSearch) retriever drives sub-query planning in plan_research().
        _setup_amalia_env()

    try:
        logger.info(
            f"Starting TTD-DR research job {job_id}: "
            f"query='{request.query[:80]}...', amalia={request.use_amalia}"
        )

        # ── Amália path: inject OpenSearch docs so nested researchers have content ──
        lc_docs = []
        if request.use_amalia:
            lc_docs = await _prefetch_opensearch_docs(
                query=request.query,
                index=NAVY_OPENSEARCH_INDEX,
                max_results=int(os.environ.get("AMALIA_PREFETCH_DOCS", "30")),
            )
            if lc_docs:
                logger.info(
                    f"Job {job_id}: Pre-fetched {len(lc_docs)} OpenSearch docs "
                    f"for TTD-DR via langchain_documents source."
                )
            else:
                logger.warning(
                    f"Job {job_id}: OpenSearch returned no docs for TTD-DR; "
                    f"nested researchers will fall back to web."
                )

        # report_source drives the nested GPTResearcher instances inside TTDDeepResearchFlow
        ttd_report_source = (
            "langchain_documents" if lc_docs else request.report_source.value
        )

        flow = TTDDeepResearchFlow(
            query=request.query,
            report_type="ttd_dr",
            report_source=ttd_report_source,
            source_urls=request.source_urls if request.source_urls else None,
            tone=None,
            documents=lc_docs if lc_docs else None,
        )

        report = await flow.run()

        # Collect sources gathered during the iterative process
        source_urls = list(flow._retrieved_sources) if flow._retrieved_sources else []

        result = ResearchResult(
            id=job_id,
            query=request.query,
            report_type="ttd_dr",
            report=report,
            source_urls=source_urls,
            research_costs=0.0,
            status="completed",
            created_at=datetime.utcnow().isoformat(),
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
    finally:
        if request.use_amalia:
            _restore_env(saved_env)


async def _prefetch_opensearch_docs(query: str, index: str, max_results: int = 30):
    """
    Pre-fetch relevant documents from the navy OpenSearch corpus.

    Returns a list of LangChain Document objects ready for injection into
    GPTResearcher via the langchain_documents report source.
    """
    import asyncio as _asyncio
    from langchain_core.documents import Document as LangChainDoc
    from gpt_researcher.retrievers.custom.custom import CustomRetriever

    # Ensure the custom retriever reads the correct index
    os.environ["OPENSEARCH_INDEX"] = index

    logger.info(f"Pre-fetching up to {max_results} docs from OpenSearch index '{index}' for query: {query[:80]}...")

    try:
        retriever = CustomRetriever(query=query)
        search_results = await _asyncio.to_thread(retriever.search, max_results)
    except Exception as exc:
        logger.error(f"OpenSearch pre-fetch failed: {exc}")
        return []

    lc_docs = [
        LangChainDoc(
            page_content=hit.get("raw_content") or hit.get("snippet", ""),
            metadata={
                "source": hit.get("url", ""),
                "title": hit.get("title", ""),
            },
        )
        for hit in search_results
        if hit.get("raw_content") or hit.get("snippet")
    ]

    logger.info(f"Pre-fetched {len(lc_docs)} docs from OpenSearch.")
    return lc_docs


async def run_research(request: ResearchRequest) -> ResearchResult:
    """
    Execute a research query using GPTResearcher.

    This is the main entry point for running research. It handles:
    - Setting up the correct model environment (Amália or default)
    - When use_amalia=True: pre-fetches context from the navy OpenSearch corpus
      and injects it as LangChain documents so GPTResearcher can do per-sub-query
      semantic similarity search over the pre-loaded content.
    - Collecting results and metadata
    """
    from gpt_researcher import GPTResearcher
    from gpt_researcher.utils.enum import Tone as GptTone

    job_id = str(uuid.uuid4())[:8]

    # ── TTD-DR uses its own flow class ──────────────────────────────
    if request.report_type == ResearchReportType.TTD_DR:
        return await _run_ttd_dr(request, job_id)

    # Save current env if using Amália
    saved_env: Dict[str, Optional[str]] = {}
    if request.use_amalia:
        for key in [
            "OPENAI_API_KEY", "OPENAI_BASE_URL", "SMART_LLM",
            "FAST_LLM", "STRATEGIC_LLM", "OPENSEARCH_INDEX", "EMBEDDING",
        ]:
            saved_env[key] = os.environ.get(key)
        # Set only LLM env vars — retrieval is handled via pre-fetched docs below
        _setup_amalia_env_llm_only()

    try:
        # Map tone
        tone_map = {t.value: t.value for t in ResearchTone}
        gpt_tone = getattr(GptTone, request.tone.value, GptTone.Objective)

        logger.info(
            f"Starting research job {job_id}: "
            f"query='{request.query[:80]}...', "
            f"type={request.report_type.value}, "
            f"amalia={request.use_amalia}"
        )

        if request.use_amalia:
            # ── Amália path: retrieve context from navy OpenSearch corpus ──────
            # GPTResearcher's CustomRetriever returns "url" not "href", so the
            # standard web-search pipeline discards all content before it reaches
            # the LLM.  We pre-fetch docs here and inject them via the
            # langchain_documents report source, which feeds content directly to
            # the per-sub-query vector similarity step (no HTTP scraping needed).
            navy_index = NAVY_OPENSEARCH_INDEX
            lc_docs = await _prefetch_opensearch_docs(
                query=request.query,
                index=navy_index,
                max_results=int(os.environ.get("AMALIA_PREFETCH_DOCS", "30")),
            )

            if lc_docs:
                logger.info(
                    f"Job {job_id}: Using {len(lc_docs)} pre-fetched OpenSearch docs "
                    f"via langchain_documents source."
                )
                researcher = GPTResearcher(
                    query=request.query,
                    report_type=request.report_type.value,
                    report_source="langchain_documents",
                    tone=gpt_tone,
                    documents=lc_docs,
                )
            else:
                logger.warning(
                    f"Job {job_id}: OpenSearch returned no docs; falling back to web search."
                )
                researcher = GPTResearcher(
                    query=request.query,
                    report_type=request.report_type.value,
                    report_source="web",
                    tone=gpt_tone,
                )
        else:
            # ── Standard path: use whatever source the request specifies ───────
            researcher = GPTResearcher(
                query=request.query,
                report_type=request.report_type.value,
                report_source=request.report_source.value,
                tone=gpt_tone,
                source_urls=request.source_urls if request.source_urls else None,
            )

        # Phase 1: Conduct research (gather context)
        logger.info(f"Job {job_id}: Conducting research...")
        await researcher.conduct_research()

        # Phase 2: Generate report
        logger.info(f"Job {job_id}: Writing report...")
        report = await researcher.write_report()

        # Collect metadata
        source_urls = researcher.get_source_urls() if hasattr(researcher, 'get_source_urls') else []
        # For langchain_documents path the researcher may not populate source_urls itself,
        # so fall back to the metadata from the pre-fetched docs
        if not source_urls and request.use_amalia and isinstance(getattr(researcher, 'documents', None), list):
            source_urls = [
                d.metadata.get("source", "")
                for d in researcher.documents
                if d.metadata.get("source")
            ]
        costs = researcher.get_costs() if hasattr(researcher, 'get_costs') else 0.0
        images = researcher.get_research_images() if hasattr(researcher, 'get_research_images') else []

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
    finally:
        if request.use_amalia:
            _restore_env(saved_env)


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
    )
    _jobs[job_id] = job
    _save_jobs()

    async def _run():
        job.status = "running"
        job.progress = "Conducting research..."
        _save_jobs()
        try:
            result = await run_research(request)
            job.result = result
            job.status = result.status
            job.error = result.error
            job.progress = "Completed" if result.status == "completed" else "Failed"
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.progress = f"Failed: {e}"
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
        },
        {
            "value": "resource_report",
            "label": "Resource Report",
            "description": "Report focused on listing and describing resources",
        },
        {
            "value": "outline_report",
            "label": "Outline Report",
            "description": "Structured outline of the research topic",
        },
        {
            "value": "custom_report",
            "label": "Custom Report",
            "description": "User-defined custom report format",
        },
        {
            "value": "detailed_report",
            "label": "Detailed Report",
            "description": "In-depth multi-subtopic detailed analysis (~5 min)",
        },
        {
            "value": "subtopic_report",
            "label": "Subtopic Report",
            "description": "Report focused on a specific subtopic",
        },
        {
            "value": "deep",
            "label": "Deep Research",
            "description": "Recursive deep exploration with extensive analysis",
        },
        {
            "value": "ttd_dr",
            "label": "TTD-DR Deep Research",
            "description": "Iterative Draft Denoising — generates, reviews and expands a structured report (~2500+ words, pt-PT)",
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
