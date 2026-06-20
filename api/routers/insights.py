from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from api.auth import assert_owns
from api.models import NoteResponse, SaveAsNoteRequest, SourceInsightResponse
from open_notebook.domain.notebook import SourceInsight
from open_notebook.exceptions import InvalidInputError

router = APIRouter()


async def _insight_source_or_404(insight_id: str, request: Request):
    """Load an insight + its parent source, enforcing source ownership.

    An insight is private to whoever owns its source, so access control is
    delegated to the source's owner (fail-closed via assert_owns).
    """
    insight = await SourceInsight.get(insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")
    source = await insight.get_source()
    assert_owns(getattr(source, "owner", None), request)
    return insight, source


@router.get("/insights/{insight_id}", response_model=SourceInsightResponse)
async def get_insight(insight_id: str, request: Request):
    """Get a specific insight by ID."""
    try:
        insight, source = await _insight_source_or_404(insight_id, request)

        return SourceInsightResponse(
            id=insight.id or "",
            source_id=source.id or "",
            insight_type=insight.insight_type,
            content=insight.content,
            created=str(insight.created),
            updated=str(insight.updated),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching insight {insight_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching insight")


@router.delete("/insights/{insight_id}")
async def delete_insight(insight_id: str, request: Request):
    """Delete a specific insight."""
    try:
        insight, _ = await _insight_source_or_404(insight_id, request)

        await insight.delete()

        return {"message": "Insight deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting insight {insight_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error deleting insight")


@router.post("/insights/{insight_id}/save-as-note", response_model=NoteResponse)
async def save_insight_as_note(
    insight_id: str, body: SaveAsNoteRequest, request: Request
):
    """Convert an insight to a note."""
    try:
        insight, _ = await _insight_source_or_404(insight_id, request)

        # Use the existing save_as_note method from the domain model
        note = await insight.save_as_note(body.notebook_id)

        return NoteResponse(
            id=note.id or "",
            title=note.title,
            content=note.content,
            note_type=note.note_type,
            created=str(note.created),
            updated=str(note.updated),
        )
    except HTTPException:
        raise
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving insight {insight_id} as note: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Error saving insight as note"
        )
