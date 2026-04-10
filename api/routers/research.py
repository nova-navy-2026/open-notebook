"""
Research API router - endpoints for NOVA-Researcher integration.

Provides REST endpoints for:
- Generating research reports (sync and async)
- Checking job status
- Listing available report types, tones, and sources
- Saving research results as notebook notes/sources
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from open_notebook.research.researcher_service import (
    ResearchReportSource,
    ResearchReportType,
    ResearchRequest,
    ResearchResult,
    ResearchTone,
    delete_research_job,
    get_report_type_info,
    get_research_job,
    get_source_info,
    get_tone_info,
    list_research_jobs,
    run_research,
    submit_research_job,
)

router = APIRouter()


# ── Request / Response Models ──────────────────────────────────────────


class GenerateResearchRequest(BaseModel):
    """API request to generate a research report."""
    query: str
    report_type: str = "research_report"
    report_source: str = "web"
    tone: str = "Objective"
    source_urls: List[str] = []
    notebook_id: Optional[str] = None
    model_id: Optional[str] = None
    use_amalia: bool = True
    run_in_background: bool = True


class ResearchJobResponse(BaseModel):
    """Response for a submitted research job."""
    job_id: str
    status: str
    message: str


class ResearchResultResponse(BaseModel):
    """Full research result response."""
    id: str
    query: str
    report_type: str
    report: str
    source_urls: List[str] = []
    research_costs: float = 0.0
    images: List[str] = []
    status: str
    created_at: str = ""
    error: Optional[str] = None


class SaveResearchAsNoteRequest(BaseModel):
    """Request to save a research result as a notebook note."""
    research_id: str
    notebook_id: str
    title: Optional[str] = None


class ReportTypeInfo(BaseModel):
    """Info about a report type for the UI."""
    value: str
    label: str
    description: str
    speed: str = ""


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("/research/report-types", response_model=List[ReportTypeInfo])
async def get_report_types():
    """Get available research report types."""
    return get_report_type_info()


@router.get("/research/tones")
async def get_tones():
    """Get available writing tones."""
    return get_tone_info()


@router.get("/research/sources")
async def get_sources():
    """Get available report sources."""
    return get_source_info()


@router.post("/research/generate")
async def generate_research(request: GenerateResearchRequest):
    """
    Generate a research report.

    If run_in_background is True, returns immediately with a job ID.
    If False, waits for the research to complete and returns the full result.
    """
    try:
        # Build internal request
        logger.debug(f"Research request received: query='{request.query[:100]}', type={request.report_type}")
        research_request = ResearchRequest(
            query=request.query,
            report_type=ResearchReportType(request.report_type),
            report_source=ResearchReportSource(request.report_source),
            tone=ResearchTone(request.tone),
            source_urls=request.source_urls,
            notebook_id=request.notebook_id,
            model_id=request.model_id,
            use_amalia=request.use_amalia,
        )

        if request.run_in_background:
            # Submit as background job
            job = await submit_research_job(research_request)
            return {
                "job_id": job.id,
                "status": job.status,
                "message": "Research job submitted. Poll /research/jobs/{job_id} for status.",
            }
        else:
            # Run synchronously
            result = await run_research(research_request)
            return {
                "id": result.id,
                "query": result.query,
                "report_type": result.report_type,
                "report": result.report,
                "source_urls": result.source_urls,
                "research_costs": result.research_costs,
                "images": result.images,
                "status": result.status,
                "created_at": result.created_at,
                "error": result.error,
            }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {e}")
    except Exception as e:
        logger.error(f"Research generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/research/jobs")
async def list_jobs():
    """List all research jobs."""
    jobs = list_research_jobs()
    return {
        "jobs": [
            {
                "id": j.id,
                "query": j.query,
                "report_type": j.report_type,
                "status": j.status,
                "progress": j.progress,
                "progress_pct": j.progress_pct,
                "created_at": j.created_at,
                "error": j.error,
                "has_result": j.result is not None,
                "tone": j.tone,
                "model_id": j.model_id,
            }
            for j in jobs
        ]
    }


@router.get("/research/jobs/{job_id}")
async def get_job(job_id: str):
    """Get a research job by ID, including the result if completed."""
    job = get_research_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")

    response = {
        "id": job.id,
        "query": job.query,
        "report_type": job.report_type,
        "status": job.status,
        "progress": job.progress,
        "progress_pct": job.progress_pct,
        "created_at": job.created_at,
        "error": job.error,
        "has_result": job.result is not None,
        "tone": job.tone,
        "model_id": job.model_id,
    }

    if job.result:
        response["result"] = {
            "report": job.result.report,
            "source_urls": job.result.source_urls,
            "research_costs": job.result.research_costs,
            "images": job.result.images,
            "tone": job.result.tone,
            "model_id": job.result.model_id,
            "retrieved_documents": job.result.retrieved_documents,
        }

    return response


@router.delete("/research/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a research job and its result permanently."""
    deleted = delete_research_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Research job not found")
    return {"success": True, "message": f"Job {job_id} deleted"}


@router.post("/research/save-as-note")
async def save_research_as_note(request: SaveResearchAsNoteRequest):
    """
    Save a completed research result as a Note in a Notebook.
    """
    job = get_research_job(request.research_id)
    if not job or not job.result:
        raise HTTPException(
            status_code=404, detail="Research job not found or not completed"
        )

    try:
        from open_notebook.domain.notebook import Note

        title = request.title or f"Research: {job.query[:80]}"
        note = Note(
            title=title,
            content=job.result.report,
            note_type="ai",
        )
        await note.save()
        await note.add_to_notebook(request.notebook_id)

        logger.info(
            f"Saved research result {request.research_id} as note {note.id} "
            f"in notebook {request.notebook_id}"
        )

        return {
            "success": True,
            "note_id": note.id,
            "message": f"Research saved as note: {title}",
        }

    except Exception as e:
        logger.error(f"Failed to save research as note: {e}")
        raise HTTPException(status_code=500, detail=str(e))