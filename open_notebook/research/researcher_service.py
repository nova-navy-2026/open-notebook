"""
Researcher service - wraps GPTResearcher for use within OpenNotebook.

This service calls the NOVA-Researcher API server over HTTP instead of
importing its modules directly.  The server URL is configured via the
NOVA_RESEARCHER_URL environment variable (default: http://localhost:8001).
"""

import asyncio
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
from open_notebook.database.repository import ensure_record_id, repo_query

# NOVA-Researcher API base URL
NOVA_RESEARCHER_URL = os.environ.get("NOVA_RESEARCHER_URL", "http://localhost:3800").rstrip("/")
RESPONSE_LANGUAGE_POLICY = (
    "português europeu (pt-PT) por defeito; se o utilizador escrever claramente "
    "noutro idioma, responde nesse idioma; quando responderes em português, usa "
    "português europeu e não português do Brasil"
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
    PLAN_AND_EXECUTE_DR = "plan_and_execute_dr"
    # Meeting minutes (ATA): generated purely from a supplied transcript,
    # with no OpenSearch / web retrieval. Used by the transcription flow.
    MEETING_MINUTES = "meeting_minutes"


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
    # Platform/app user id. Used to load private uploads from SurrealDB.
    auth_user_id: str = "anonymous"
    # Optional response language (human-readable, e.g. "English" or
    # "português europeu (pt-PT)"). Used by retrieval-free flows such as the
    # meeting-minutes (ATA) path so the output matches the conversation
    # language. When None, falls back to RESPONSE_LANGUAGE_POLICY.
    language: Optional[str] = None
    # Transcript document style for the meeting-minutes path:
    # "ata" | "conversation" | "summary" | "literal". When None, defaults to ATA.
    report_style: Optional[str] = None
    # Optional user-supplied document title.
    title: Optional[str] = None


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
    updated_at: Optional[str] = None
    # Authenticated user id this job belongs to. Used to enforce that users
    # only see / poll / delete their own research reports.
    user_id: Optional[str] = None
    # Ids of notebook notes created from this report (via "Save to Notebook").
    # When the report is deleted from the history, these notes are deleted too.
    saved_note_ids: List[str] = []


# ── Persistent job store ──────────────────────────────────────────────

_jobs_file = os.path.join(DATA_FOLDER, "research_jobs.json")
_jobs: Dict[str, ResearchJob] = {}
_running_jobs: Dict[str, ResearchJob] = {}
_background_tasks: set[asyncio.Task] = set()
RESEARCH_JOB_TIMEOUT_SECONDS = int(os.environ.get("RESEARCH_JOB_TIMEOUT_SECONDS", "2700"))
RESEARCH_JOB_STALE_SECONDS = int(os.environ.get("RESEARCH_JOB_STALE_SECONDS", "3600"))
RESEARCH_PREFETCH_TIMEOUT_SECONDS = float(os.environ.get("RESEARCH_PREFETCH_TIMEOUT_SECONDS", "45"))
RESEARCH_MAX_APP_DOCS = int(os.environ.get("RESEARCH_MAX_APP_DOCS", "25"))
RESEARCH_MAX_APP_DOC_CHARS = int(os.environ.get("RESEARCH_MAX_APP_DOC_CHARS", "12000"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_job_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _mark_stale_job_if_needed(job: ResearchJob) -> bool:
    if job.status not in ("pending", "running"):
        return False
    reference = _parse_job_time(job.updated_at) or _parse_job_time(job.created_at)
    if not reference:
        return False
    age_seconds = (datetime.now(timezone.utc) - reference).total_seconds()
    if age_seconds <= RESEARCH_JOB_STALE_SECONDS:
        return False

    job.status = "failed"
    job.error = (
        "Research job timed out without progress. "
        "It may have been interrupted or the research backend stopped responding."
    )
    job.progress = "Falhou (sem progresso durante demasiado tempo)"
    job.updated_at = _now_iso()
    logger.warning(
        f"Marked stale research job {job.id} as failed after {int(age_seconds)}s without progress"
    )
    return True


def _read_jobs_from_disk() -> Dict[str, ResearchJob]:
    if not os.path.exists(_jobs_file):
        return {}
    with open(_jobs_file, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    return {jid: ResearchJob.model_validate(raw) for jid, raw in data.items()}


def _job_time(value: Any) -> Optional[datetime]:
    if isinstance(value, dict):
        return _parse_job_time(value.get("updated_at")) or _parse_job_time(value.get("created_at"))
    return _parse_job_time(getattr(value, "updated_at", None)) or _parse_job_time(
        getattr(value, "created_at", None)
    )


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

        # Active background jobs are the authoritative in-process objects for
        # this worker. Polling can refresh _jobs from disk, so restore these
        # references before serialising or progress/completion updates can be
        # overwritten by stale disk snapshots.
        _jobs.update(_running_jobs)

        # … then overlay this worker's view when it is at least as recent as
        # the on-disk state. This avoids resurrecting stale "running" jobs from
        # a polling worker after another worker already persisted completion.
        for jid, job in _jobs.items():
            existing = merged.get(jid)
            if existing:
                existing_time = _job_time(existing)
                job_time = _job_time(job)
                if existing_time and job_time and existing_time > job_time:
                    continue
                existing_status = str(existing.get("status") or "")
                if (
                    existing_status in ("completed", "failed")
                    and job.status in ("pending", "running")
                    and (not job_time or not existing_time or existing_time >= job_time)
                ):
                    continue
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


def _persist_job(job: ResearchJob) -> None:
    _jobs[job.id] = job
    _save_jobs()


def _load_jobs() -> None:
    """Load persisted research jobs from disk on startup.

    Active jobs are only marked failed after a stale-progress threshold. This
    avoids incorrectly failing a job owned by another worker during rolling
    startup, while still preventing forever-spinning progress bars.
    """
    if not os.path.exists(_jobs_file):
        return
    try:
        _jobs.update(_read_jobs_from_disk())

        stale = 0
        for job in _jobs.values():
            if _mark_stale_job_if_needed(job):
                stale += 1
        if stale:
            _save_jobs()
            logger.warning(f"Marked {stale} stale research job(s) as failed on startup")

        logger.info(f"Loaded {len(_jobs)} research jobs from disk")
    except Exception as exc:
        logger.warning(f"Could not load research jobs from disk: {exc}")


_load_jobs()


def _get_job(job_id: str) -> Optional[ResearchJob]:
    active_job = _running_jobs.get(job_id)
    if active_job is not None:
        if _mark_stale_job_if_needed(active_job):
            _persist_job(active_job)
        return active_job

    # Always refresh from disk first. In multi-worker deployments, the worker
    # receiving the poll may have a stale in-memory copy while another worker
    # has already completed and persisted the job.
    import time
    for attempt in range(4):
        try:
            disk_jobs = _read_jobs_from_disk()
            if job_id in disk_jobs:
                loaded = disk_jobs[job_id]
                _jobs[job_id] = loaded
                if _mark_stale_job_if_needed(loaded):
                    _save_jobs()
                return loaded
        except Exception as exc:
            logger.debug(f"Could not reload job {job_id} from disk (attempt {attempt+1}): {exc}")
        if attempt < 3:
            time.sleep(0.05 * (2 ** attempt))  # 50ms, 100ms, 200ms

    job = _jobs.get(job_id)
    if job and _mark_stale_job_if_needed(job):
        _save_jobs()
    return job


def _list_jobs() -> List[ResearchJob]:
    # Disk is the cross-worker source of truth. REBUILD this worker's cache from
    # it (rather than an additive .update()) so jobs another worker deleted are
    # dropped here too — otherwise a deleted report lingers in a stale worker's
    # memory and keeps reappearing on every poll that this worker happens to
    # answer. Locally-running jobs are the authoritative in-process objects, so
    # they always survive the rebuild and overlay any older disk snapshot.
    try:
        disk_jobs = _read_jobs_from_disk()
        rebuilt: Dict[str, ResearchJob] = dict(disk_jobs)
        rebuilt.update(_running_jobs)
        _jobs.clear()
        _jobs.update(rebuilt)
    except Exception as exc:
        # On a transient disk-read failure keep the existing cache rather than
        # wiping it; the next poll will reconcile.
        logger.debug(f"Could not merge jobs from disk: {exc}")
    changed = False
    for job in _jobs.values():
        changed = _mark_stale_job_if_needed(job) or changed
    if changed:
        _save_jobs()
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


_ACL_UNSET: Any = object()


async def _prefetch_opensearch_docs(
    query: str,
    index: str,
    max_results: int = 30,
    user_id: Optional[str] = None,
    acl_filter: Any = _ACL_UNSET,
) -> List[Dict[str, Any]]:
    """
    Pre-fetch documents from the navy OpenSearch corpus via the
    NOVA-Researcher /opensearch/prefetch endpoint.

    ``acl_filter`` overrides the per-user filter with an explicit clause (used
    for collaborative notebooks, whose effective clearance/departments differ
    from any single member's).

    Returns a list of dicts with 'page_content' and 'metadata' keys.
    """
    try:
        retriever_filter = (
            build_opensearch_filter(user_id)
            if acl_filter is _ACL_UNSET
            else acl_filter
        )
        resp = await _http_client.post(
            f"{NOVA_RESEARCHER_URL}/opensearch/prefetch",
            json={
                "query": query,
                "index": index,
                "max_results": max_results,
                "retriever_filter": retriever_filter,
            },
            timeout=RESEARCH_PREFETCH_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("documents", [])
        logger.info(f"Pre-fetched {len(docs)} docs from OpenSearch via API")
        return docs
    except Exception as exc:
        logger.error(f"OpenSearch pre-fetch via API failed: {exc}")
        return []


def _research_terms(query: str) -> List[str]:
    words = re.findall(r"[\wÀ-ÿ]{3,}", (query or "").lower())
    stop = {
        "com", "das", "dos", "para", "por", "que", "uma", "este", "esta",
        "isto", "sobre", "the", "and", "for", "with", "what", "from",
    }
    return [word for word in words if word not in stop]


def _row_to_research_document(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    source_id = str(row.get("id") or "")
    title = str(row.get("title") or row.get("file_name") or source_id or "Source")
    caption = str(row.get("caption") or "")
    full_text = str(row.get("full_text") or "")
    content = "\n\n".join(part for part in [caption, full_text] if part.strip()).strip()
    if not content:
        return None
    if len(content) > RESEARCH_MAX_APP_DOC_CHARS:
        content = content[:RESEARCH_MAX_APP_DOC_CHARS].rstrip() + "\n\n[excerto truncado]"
    return {
        "page_content": content,
        "metadata": {
            "source": source_id,
            "title": title,
            "file_mime": row.get("file_mime"),
            "storage": "surrealdb",
        },
    }


async def _load_app_upload_documents(request: ResearchRequest) -> List[Dict[str, Any]]:
    """Load private SurrealDB uploads eligible for this research request.

    Research launched inside a notebook is restricted to sources linked to that
    notebook. Research launched from the Research menu can use the authenticated
    user's private uploaded sources.
    """
    if not request.auth_user_id:
        return []

    params: Dict[str, Any] = {"owner": request.auth_user_id}
    if request.notebook_id:
        params["notebook_id"] = ensure_record_id(request.notebook_id)
        # A member/owner of the notebook may research over ALL its sources
        # (shared collaboration); otherwise fall back to only the caller's own
        # sources within the notebook.
        nb_owner_rows = await repo_query(
            "SELECT VALUE owner FROM $nb", {"nb": ensure_record_id(request.notebook_id)}
        )
        nb_owner = nb_owner_rows[0] if nb_owner_rows else None
        is_member = nb_owner == request.auth_user_id
        if not is_member:
            from open_notebook.domain.collaboration import get_member

            is_member = (
                await get_member(str(request.notebook_id), request.auth_user_id)
                is not None
            )
        owner_clause = "" if is_member else "WHERE owner = $owner"
        query = f"""
            SELECT id, title, full_text, caption, file_mime, file_name, owner, updated
            FROM (SELECT VALUE in FROM reference WHERE out = $notebook_id)
            {owner_clause}
            {"AND" if owner_clause else "WHERE"} (full_text != NONE OR caption != NONE)
            LIMIT 250
        """
    else:
        query = """
            SELECT id, title, full_text, caption, file_mime, file_name, owner, updated
            FROM source
            WHERE owner = $owner
            AND (full_text != NONE OR caption != NONE)
            ORDER BY updated DESC
            LIMIT 250
        """

    try:
        rows = await repo_query(query, params)
    except Exception as exc:
        logger.warning(f"Could not load app upload documents for research: {exc}")
        return []

    terms = _research_terms(request.query)
    scored: List[tuple[int, Dict[str, Any]]] = []
    for row in rows or []:
        doc = _row_to_research_document(row)
        if not doc:
            continue
        haystack = (
            f"{doc['metadata'].get('title', '')}\n{doc.get('page_content', '')}"
        ).lower()
        score = sum(haystack.count(term) for term in terms) if terms else 1
        scored.append((score, doc))

    scored.sort(key=lambda item: item[0], reverse=True)
    docs = [doc for _, doc in scored[:RESEARCH_MAX_APP_DOCS]]
    scope = f"notebook {request.notebook_id}" if request.notebook_id else "research menu"
    logger.info(f"Loaded {len(docs)} app upload document(s) for {scope} research")
    return docs


async def _build_accessible_research_documents(
    request: ResearchRequest,
    job_id: str,
    progress_callback=None,
    progress_steps: tuple[int, int, int] = (11, 13, 18),
) -> List[Dict[str, Any]]:
    app_pct, navy_pct, ready_pct = progress_steps
    if progress_callback:
        await progress_callback(app_pct, "Fase 1: A carregar sources privadas autorizadas...")
    app_docs = await _load_app_upload_documents(request)
    if progress_callback:
        await progress_callback(navy_pct, "Fase 1: A pesquisar documentos Navy autorizados...")
    # For a collaborative notebook, scope the corpus to the notebook's effective
    # (most-restrictive) clearance + intersected departments rather than the
    # acting member's own access — research output is shared with all members.
    prefetch_kwargs: Dict[str, Any] = {}
    if request.notebook_id:
        try:
            from open_notebook.collaboration import effective_navy_filter
            from open_notebook.domain.notebook import Notebook

            nb = await Notebook.get(str(request.notebook_id))
            override = effective_navy_filter(nb)
            if override is not None:
                prefetch_kwargs["acl_filter"] = override
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning(f"Could not derive effective navy filter: {exc}")
    navy_docs = await _prefetch_opensearch_docs(
        query=request.query,
        index=NAVY_OPENSEARCH_INDEX,
        max_results=int(os.environ.get("AMALIA_PREFETCH_DOCS", "30")),
        user_id=request.user_id,
        **prefetch_kwargs,
    )
    docs = [*app_docs, *navy_docs]
    if progress_callback:
        await progress_callback(ready_pct, "Fase 1: Documentos acessíveis preparados.")
    logger.info(
        f"Job {job_id}: accessible research docs: "
        f"{len(app_docs)} app upload(s), {len(navy_docs)} navy chunk(s)"
    )
    return docs


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

        documents = await _build_accessible_research_documents(
            request,
            job_id,
            progress_callback=progress_callback,
            progress_steps=(7, 9, 12),
        )
        if not documents:
            raise RuntimeError(
                "No accessible documents were found for this research request."
            )

        if progress_callback:
            await progress_callback(15, "A executar TTD-DR...")

        # Call NOVA-Researcher TTD-DR endpoint via SSE so we can forward
        # real-time progress events (pct + message) to the UI.
        payload = {
            "query": request.query,
            "source_urls": request.source_urls,
            "report_source": "langchain_documents",
            "language": RESPONSE_LANGUAGE_POLICY,
            "documents": documents,
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
                    break
                elif etype == "error":
                    stream_error = str(event.get("detail", "Unknown TTD-DR error"))

        if stream_error:
            raise RuntimeError(stream_error)

        if progress_callback:
            await progress_callback(95, "A finalizar...")

        if not source_urls:
            source_urls = [
                d.get("metadata", {}).get("source", "")
                for d in documents
                if d.get("metadata", {}).get("source")
            ]

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

        documents = await _build_accessible_research_documents(
            request,
            job_id,
            progress_callback=progress_callback,
            progress_steps=(7, 9, 12),
        )
        if not documents:
            raise RuntimeError(
                "No accessible documents were found for this research request."
            )

        if progress_callback:
            await progress_callback(15, "A executar ReAct-DR...")

        payload = {
            "query": request.query,
            "source_urls": request.source_urls,
            "report_source": "langchain_documents",
            "language": RESPONSE_LANGUAGE_POLICY,
            "documents": documents,
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
                    break
                elif etype == "error":
                    stream_error = str(event.get("detail", "Unknown ReAct-DR error"))

        if stream_error:
            raise RuntimeError(stream_error)

        if progress_callback:
            await progress_callback(95, "A finalizar...")

        if not source_urls:
            source_urls = [
                d.get("metadata", {}).get("source", "")
                for d in documents
                if d.get("metadata", {}).get("source")
            ]

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


async def _run_plan_and_execute_dr(request: ResearchRequest, job_id: str, progress_callback=None) -> ResearchResult:
    """Execute research using the Plan-and-Execute DR flow via the NOVA-Researcher API."""

    provider = await _resolve_model_provider(request.model_id) or _provider_for_request(request)

    try:
        logger.info(
            f"Starting Plan-and-Execute DR research job {job_id}: "
            f"query='{request.query[:80]}...', provider={provider or 'gemma(default)'}"
        )

        if progress_callback:
            await progress_callback(5, "A iniciar Plan-and-Execute DR...")

        documents = await _build_accessible_research_documents(
            request,
            job_id,
            progress_callback=progress_callback,
            progress_steps=(7, 9, 12),
        )
        if not documents:
            raise RuntimeError(
                "No accessible documents were found for this research request."
            )

        if progress_callback:
            await progress_callback(15, "A executar Plan-and-Execute DR...")

        # Call the NOVA-Researcher Plan-and-Execute DR endpoint via SSE so we
        # can forward real-time progress events (pct + message) to the UI.
        payload = {
            "query": request.query,
            "source_urls": request.source_urls,
            "report_source": "langchain_documents",
            "language": RESPONSE_LANGUAGE_POLICY,
            "documents": documents,
        }
        params: Dict[str, Any] = {"stream": "true"}
        if provider:
            params["provider"] = provider

        report = ""
        source_urls: List[str] = []
        stream_error: Optional[str] = None

        async with _http_client.stream(
            "POST",
            f"{NOVA_RESEARCHER_URL}/research/plan-and-execute-dr",
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
                        # Server pct is 0-100 over the flow. Map it into the
                        # 15-95 band so the bookend steps stay monotonic.
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
                    break
                elif etype == "error":
                    stream_error = str(event.get("detail", "Unknown Plan-and-Execute DR error"))

        if stream_error:
            raise RuntimeError(stream_error)

        if progress_callback:
            await progress_callback(95, "A finalizar...")

        if not source_urls:
            source_urls = [
                d.get("metadata", {}).get("source", "")
                for d in documents
                if d.get("metadata", {}).get("source")
            ]

        retrieved_docs = [
            RetrievedDocument(title=s, source=s, snippet="")
            for s in source_urls
            if s
        ]

        result = ResearchResult(
            id=job_id,
            query=request.query,
            report_type="plan_and_execute_dr",
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
            f"Job {job_id}: Plan-and-Execute DR research completed. "
            f"Report length: {len(report)} chars, Sources: {len(source_urls)}"
        )
        return result

    except Exception as e:
        logger.error(f"Job {job_id}: Plan-and-Execute DR research failed: {e}")
        return ResearchResult(
            id=job_id,
            query=request.query,
            report_type="plan_and_execute_dr",
            report="",
            status="failed",
            error=str(e),
            created_at=datetime.now(timezone.utc).isoformat(),
        )


async def _run_meeting_minutes(
    request: ResearchRequest, job_id: str, progress_callback=None
) -> ResearchResult:
    """Generate meeting minutes (ATA) from the query transcript.

    This path is fully retrieval-free: it does NOT touch OpenSearch or the
    web. It calls the NOVA-Researcher ``/meeting-minutes`` endpoint, which
    performs a single LLM summarisation of the transcript in the requested
    conversation language.
    """
    provider = await _resolve_model_provider(request.model_id) or _provider_for_request(request)
    language = request.language or RESPONSE_LANGUAGE_POLICY

    try:
        logger.info(
            f"Starting meeting-minutes job {job_id}: "
            f"transcript_len={len(request.query)}, language='{language}', "
            f"provider={provider or 'gemma(default)'}"
        )
        if progress_callback:
            await progress_callback(20, "A redigir a ATA da reunião...")

        # report_style lets NOVA-Researcher vary the prompt (ATA / conversa /
        # resumo / literal). Older NOVA versions ignore it and produce an ATA.
        style = (request.report_style or "ata").strip().lower()
        resp = await _http_client.post(
            f"{NOVA_RESEARCHER_URL}/meeting-minutes",
            json={
                "transcript": request.query,
                "language": language,
                "style": style,
                "title": request.title or None,
            },
            params={"provider": provider} if provider else {},
        )
        resp.raise_for_status()
        data = resp.json()

        if progress_callback:
            await progress_callback(90, "A finalizar o documento...")

        report = _normalize_report_headings(
            data.get("report", ""),
            fallback_title=request.title or "Ata da Reunião",
        )

        return ResearchResult(
            id=job_id,
            query=request.query,
            report_type=ResearchReportType.MEETING_MINUTES.value,
            report=report,
            source_urls=[],
            research_costs=data.get("costs", 0.0),
            images=[],
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
            tone=request.tone.value,
            model_id=request.model_id,
            retrieved_documents=[],
        )

    except Exception as e:
        logger.error(f"Job {job_id}: Meeting minutes generation failed: {e}")
        return ResearchResult(
            id=job_id,
            query=request.query,
            report_type=ResearchReportType.MEETING_MINUTES.value,
            report="",
            status="failed",
            error=str(e),
            created_at=datetime.now(timezone.utc).isoformat(),
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

    # ── TTD-DR, ReAct-DR and Plan-and-Execute DR use their own endpoints ──
    if request.report_type == ResearchReportType.TTD_DR:
        return await _run_ttd_dr(request, job_id, progress_callback=progress_callback)

    if request.report_type == ResearchReportType.REACT_DEEP:
        return await _run_react_dr(request, job_id, progress_callback=progress_callback)

    # ── Meeting minutes (ATA): retrieval-free, transcript-only ────────
    if request.report_type == ResearchReportType.MEETING_MINUTES:
        return await _run_meeting_minutes(request, job_id, progress_callback=progress_callback)

    if request.report_type == ResearchReportType.PLAN_AND_EXECUTE_DR:
        return await _run_plan_and_execute_dr(request, job_id, progress_callback=progress_callback)

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

        documents = await _build_accessible_research_documents(
            request,
            job_id,
            progress_callback=progress_callback,
        )
        if not documents:
            raise RuntimeError(
                "No accessible documents were found for this research request."
            )

        if progress_callback:
            await progress_callback(20, "Fase 2: A executar pesquisa...")

        # Build request payload for the NOVA-Researcher API
        payload = {
            "query": request.query,
            "report_type": request.report_type.value,
            "report_source": "langchain_documents",
            "tone": request.tone.value,
            "language": RESPONSE_LANGUAGE_POLICY,
            "source_urls": request.source_urls,
            "documents": documents,
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

        # Fallback source URLs from the server-built accessible documents.
        if not source_urls and documents:
            source_urls = [
                d.get("metadata", {}).get("source", "")
                for d in documents
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
            for d in documents
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
    job_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    job = ResearchJob(
        id=job_id,
        query=request.query,
        report_type=request.report_type.value,
        status="pending",
        created_at=now,
        updated_at=now,
        tone=request.tone.value,
        model_id=request.model_id,
        notebook_id=request.notebook_id,
        user_id=request.user_id or request.auth_user_id,
    )
    _jobs[job_id] = job
    _running_jobs[job_id] = job
    _persist_job(job)

    async def _run():
        job.status = "running"
        job.progress = "A conduzir pesquisa..."
        job.progress_pct = 5
        job.updated_at = _now_iso()
        _persist_job(job)

        async def _progress_callback(pct: int, message: str) -> None:
            """Update job progress in-place so polling clients see live updates."""
            job.progress_pct = pct
            job.progress = message
            job.updated_at = _now_iso()
            _persist_job(job)

        try:
            result = await asyncio.wait_for(
                run_research(request, progress_callback=_progress_callback),
                timeout=RESEARCH_JOB_TIMEOUT_SECONDS,
            )
            job.result = result
            job.status = result.status
            job.error = result.error
            job.progress = "Concluído" if result.status == "completed" else "Falhou"
            job.progress_pct = 100 if result.status == "completed" else job.progress_pct

        except asyncio.TimeoutError:
            job.status = "failed"
            job.error = (
                f"Research job exceeded the configured timeout "
                f"({RESEARCH_JOB_TIMEOUT_SECONDS}s)."
            )
            job.progress = "Falhou (tempo limite excedido)"
        except asyncio.CancelledError:
            job.status = "failed"
            job.error = "Research job was cancelled before completion."
            job.progress = "Falhou (job cancelado)"
            raise
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.progress = f"Falhou: {e}"
        finally:
            job.updated_at = _now_iso()
            _persist_job(job)
            _running_jobs.pop(job_id, None)

    # Keep a strong reference while the task is running; otherwise long-lived
    # jobs can be garbage-collected before they persist a terminal state.
    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return job


def get_research_job(job_id: str) -> Optional[ResearchJob]:
    """Get a research job by ID."""
    return _get_job(job_id)


def list_research_jobs() -> List[ResearchJob]:
    """List all research jobs, most recent first."""
    return _list_jobs()


def delete_research_job(job_id: str) -> bool:
    """Delete a research job by ID. Returns True if deleted, False if not found.

    Works across Uvicorn workers: the job may live only on disk (created/owned by
    another worker) and not in this worker's in-memory cache. We therefore drop
    it from the local cache AND the running set AND the persisted disk state, and
    report success if it existed in any of them.
    """
    existed_locally = _jobs.pop(job_id, None) is not None
    # Also drop any locally-running reference so it can't be re-added by the
    # _running_jobs overlay in _save_jobs()/_list_jobs().
    _running_jobs.pop(job_id, None)

    try:
        on_disk = job_id in _read_jobs_from_disk()
    except Exception:
        on_disk = False

    if not existed_locally and not on_disk:
        return False

    # Pass the deleted ID so _save_jobs() removes it from the disk state before
    # writing — without this the merge would read the job back from disk and
    # restore it, making the deletion appear to succeed but then immediately
    # reappear in the job list.
    _save_jobs(_deleted={job_id})
    return True


def record_saved_note(job_id: str, note_id: str) -> bool:
    """Record that a notebook note was created from this report.

    Lets ``delete_research_job`` (via the delete endpoint) also remove the saved
    notes. Returns True when the link was recorded, False when the job is gone.
    """
    job = _get_job(job_id)
    if not job:
        return False
    if note_id not in job.saved_note_ids:
        job.saved_note_ids.append(note_id)
        job.updated_at = _now_iso()
        _persist_job(job)
    return True


def update_report_directly(job_id: str, new_report: str) -> Optional[ResearchJob]:
    """Replace a report's content verbatim (no AI processing). Persists the change."""
    job = _get_job(job_id)
    if not job or not job.result:
        return None
    job.result.report = new_report.strip()
    job.updated_at = _now_iso()
    _persist_job(job)
    logger.info(f"Directly updated research report {job_id} ({len(new_report)} chars)")
    return job


async def revise_research_report(
    job_id: str, instruction: str, model_id: Optional[str] = None
) -> Optional[ResearchJob]:
    """Apply a user instruction to an existing report and store the revision.

    Uses a full language model (not the token-capped multimodal path) so long
    reports are not truncated, and persists the revised report back onto the job
    so the change is durable (chat + Deep Research history).

    Returns the updated job, or None if the job/report is missing or the model
    returned nothing usable.
    """
    job = _get_job(job_id)
    if not job or not job.result or not (job.result.report or "").strip():
        return None

    from open_notebook.ai.provision import provision_langchain_model
    from open_notebook.utils import clean_thinking_content
    from open_notebook.utils.text_utils import extract_text_content

    current_report = job.result.report
    prompt = (
        "És um editor de relatórios. A tua ÚNICA tarefa é aplicar a alteração pedida "
        "ao relatório e devolver o relatório COMPLETO atualizado.\n\n"
        "REGRAS ABSOLUTAS:\n"
        "1. A tua resposta deve conter o relatório COMPLETO em Markdown — todas as "
        "secções, do início ao fim.\n"
        "2. Só alteras o que foi pedido. Tudo o resto permanece igual.\n"
        "3. Não acrescentes comentários, explicações, prefácios nem notas finais.\n"
        "4. Não respondas com uma síntese nem com apenas a parte alterada.\n"
        "5. O relatório resultante deve ter comprimento igual ou maior ao original.\n\n"
        f"## Alteração pedida pelo utilizador\n{instruction.strip()}\n\n"
        f"## Relatório original completo (devolve tudo isto, com a alteração aplicada)\n"
        f"{current_report}\n\n"
        "LEMBRA: devolve o relatório COMPLETO, não apenas a secção alterada."
    )

    model = await provision_langchain_model(prompt, model_id or job.model_id, "chat", max_tokens=8000)
    ai_message = await model.ainvoke(prompt)
    revised = clean_thinking_content(extract_text_content(ai_message.content)).strip()

    # Strip an accidental code fence wrapping the whole report.
    if revised.startswith("```"):
        lines = revised.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        revised = "\n".join(lines).strip()

    if not revised:
        return None

    # Guard: if the model returned only a fragment (< 65 % of original length),
    # it likely produced just the edited section instead of the full report.
    # Reject the result so the original is preserved.
    if len(revised) < len(current_report) * 0.65:
        logger.warning(
            f"Revise {job_id}: model returned {len(revised)} chars "
            f"vs {len(current_report)} original — likely truncated, rejecting."
        )
        raise ValueError(
            "O modelo devolveu apenas uma parte do relatório em vez do relatório completo. "
            "Tenta novamente ou usa um modelo com maior capacidade."
        )

    job.result.report = revised
    job.updated_at = _now_iso()
    _persist_job(job)
    logger.info(f"Revised research report {job_id} ({len(revised)} chars)")
    return job


def get_report_type_info() -> List[Dict[str, str]]:
    """Return metadata about available report types for the UI."""
    return [
        {
            "value": "research_report",
            "label": "Research Report",
            "description": "Comprehensive research report with analysis (~1200 words)",
            "speed": "balanced",
        },
        {
            "value": "resource_report",
            "label": "Resource Report",
            "description": "Lists and describes the most relevant resources on the topic",
            "speed": "quick",
        },
        {
            "value": "ttd_dr",
            "label": "TTD-DR",
            "description": "Iterative Draft Denoising — generates, reviews and expands a structured report (~2500+ words, pt-PT)",
            "speed": "in-depth",
        },
        {
            "value": "react_deep",
            "label": "ReAct",
            "description": "ReAct (Reason + Act) loop — interleaved thought/retrieval/observation cycles before writing the final report",
            "speed": "in-depth",
        },
        {
            "value": "plan_and_execute_dr",
            "label": "Plan-and-Execute",
            "description": "Plan-first — builds a complete hierarchical plan, researches every item in parallel, fills gaps, then synthesises a plan-grounded report (pt-PT)",
            "speed": "in-depth",
        },
    ]


def get_tone_info() -> List[Dict[str, str]]:
    """Return metadata about available tones for the UI."""
    return [
        {"value": "Objective", "label": "Objective", "description": "Impartial and unbiased"},
        {"value": "Analytical", "label": "Analytical", "description": "Critical evaluation"},
        {"value": "Formal", "label": "Formal", "description": "Academic standards"},
        {"value": "Informative", "label": "Informative", "description": "Clear and comprehensive"},
        {"value": "Explanatory", "label": "Explanatory", "description": "Clarifying complex concepts"},
        {"value": "Critical", "label": "Critical", "description": "Judging validity"},
        {"value": "Comparative", "label": "Comparative", "description": "Juxtaposing theories/data"},
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
