from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger

from api.auth import assert_owns, get_current_user_id, is_admin
from api.collaboration_access import assert_can_read_notebook
from api.models import (
    NotebookCreate,
    NotebookDeletePreview,
    NotebookDeleteResponse,
    NotebookResponse,
    NotebookUpdate,
    UpdateNavyDocsRequest,
)
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.collaboration import (
    delete_notebook_collaboration,
    get_member_notebook_ids,
)
from open_notebook.domain.notebook import Notebook, Source
from open_notebook.exceptions import InvalidInputError

router = APIRouter()


def _to_notebook_response(nb: dict, user_id: str) -> NotebookResponse:
    """Build a NotebookResponse from a raw notebook row, including collaboration
    metadata. ``member_count`` falls back to 1 for private notebooks (which have
    no notebook_member rows)."""
    owner = nb.get("owner")
    collaborative = bool(nb.get("collaborative", False))
    raw_members = nb.get("member_count") or 0
    return NotebookResponse(
        id=str(nb.get("id", "")),
        name=nb.get("name", ""),
        description=nb.get("description", ""),
        archived=nb.get("archived", False),
        created=str(nb.get("created", "")),
        updated=str(nb.get("updated", "")),
        source_count=nb.get("source_count", 0),
        note_count=nb.get("note_count", 0),
        owner=owner,
        collaborative=collaborative,
        member_count=raw_members if raw_members else 1,
        is_owner=(owner is not None and owner == user_id),
        navy_doc_ids=nb.get("navy_doc_ids") or [],
    )


def _ensure_owner(nb_owner: Optional[str], user_id: str) -> None:
    """Raise 404 unless ``user_id`` owns the notebook (fail-closed).

    Notebooks without an owner (``None``) are NOT public — they are denied to
    regular users. Admin access to ownerless/legacy notebooks goes through
    endpoints that pass the request to ``assert_owns``.
    """
    if nb_owner is None or nb_owner != user_id:
        raise HTTPException(status_code=404, detail="Notebook not found")


@router.get("/notebooks", response_model=List[NotebookResponse])
async def get_notebooks(
    request: Request,
    archived: Optional[bool] = Query(None, description="Filter by archived status"),
    order_by: str = Query("updated desc", description="Order by field and direction"),
    user_id: str = Depends(get_current_user_id),
):
    """Get all notebooks with optional filtering and ordering."""
    try:
        # Fail-closed scoping: every caller — admins included — sees only the
        # notebooks they own plus the collaborative ones they belong to.
        # Ownerless/legacy notebooks are NOT public. Admin oversight does not
        # run through this listing: admins reach user content solely via
        # flagged items (see api/routers/flags.py).
        member_ids = await get_member_notebook_ids(user_id)
        where_clause = "WHERE owner = $owner OR id IN $member_ids"
        params: dict = {
            "owner": user_id,
            "member_ids": [ensure_record_id(n) for n in member_ids],
        }

        query = f"""
            SELECT *,
            count(<-reference.in) as source_count,
            count(<-artifact.in) as note_count,
            count((SELECT id FROM notebook_member WHERE notebook = $parent.id)) as member_count
            FROM notebook
            {where_clause}
            ORDER BY {order_by}
        """

        result = await repo_query(query, params)

        # Filter by archived status if specified
        if archived is not None:
            result = [nb for nb in result if nb.get("archived") == archived]

        return [_to_notebook_response(nb, user_id) for nb in result]
    except Exception as e:
        logger.error(f"Error fetching notebooks: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching notebooks: {str(e)}"
        )


@router.post("/notebooks", response_model=NotebookResponse)
async def create_notebook(
    notebook: NotebookCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create a new notebook."""
    try:
        new_notebook = Notebook(
            name=notebook.name,
            description=notebook.description,
            owner=user_id,
        )
        await new_notebook.save()

        return NotebookResponse(
            id=new_notebook.id or "",
            name=new_notebook.name,
            description=new_notebook.description,
            archived=new_notebook.archived or False,
            created=str(new_notebook.created),
            updated=str(new_notebook.updated),
            source_count=0,  # New notebook has no sources
            note_count=0,  # New notebook has no notes
        )
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating notebook: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating notebook: {str(e)}"
        )


@router.get(
    "/notebooks/{notebook_id}/delete-preview", response_model=NotebookDeletePreview
)
async def get_notebook_delete_preview(
    notebook_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get a preview of what will be deleted when this notebook is deleted."""
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        _ensure_owner(getattr(notebook, "owner", None), user_id)

        preview = await notebook.get_delete_preview()

        return NotebookDeletePreview(
            notebook_id=str(notebook.id),
            notebook_name=notebook.name,
            note_count=preview["note_count"],
            exclusive_source_count=preview["exclusive_source_count"],
            shared_source_count=preview["shared_source_count"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting delete preview for notebook {notebook_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching notebook deletion preview: {str(e)}",
        )


@router.get("/notebooks/{notebook_id}", response_model=NotebookResponse)
async def get_notebook(
    notebook_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """Get a specific notebook by ID."""
    try:
        # Query with counts for single notebook
        query = """
            SELECT *,
            count(<-reference.in) as source_count,
            count(<-artifact.in) as note_count,
            count((SELECT id FROM notebook_member WHERE notebook = $parent.id)) as member_count
            FROM $notebook_id
        """
        result = await repo_query(query, {"notebook_id": ensure_record_id(notebook_id)})

        if not result:
            raise HTTPException(status_code=404, detail="Notebook not found")

        nb = result[0]
        # Owner, admin, or member may read a notebook.
        await assert_can_read_notebook(nb.get("owner"), notebook_id, request)
        return _to_notebook_response(nb, user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching notebook {notebook_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching notebook: {str(e)}"
        )


@router.put("/notebooks/{notebook_id}", response_model=NotebookResponse)
async def update_notebook(
    notebook_id: str,
    notebook_update: NotebookUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Update a notebook."""
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        _ensure_owner(getattr(notebook, "owner", None), user_id)

        # Update only provided fields
        if notebook_update.name is not None:
            notebook.name = notebook_update.name
        if notebook_update.description is not None:
            notebook.description = notebook_update.description
        if notebook_update.archived is not None:
            notebook.archived = notebook_update.archived

        await notebook.save()

        # Query with counts after update
        query = """
            SELECT *,
            count(<-reference.in) as source_count,
            count(<-artifact.in) as note_count
            FROM $notebook_id
        """
        result = await repo_query(query, {"notebook_id": ensure_record_id(notebook_id)})

        if result:
            nb = result[0]
            return _to_notebook_response(nb, user_id)

        # Fallback if query fails
        return NotebookResponse(
            id=notebook.id or "",
            name=notebook.name,
            description=notebook.description,
            archived=notebook.archived or False,
            created=str(notebook.created),
            updated=str(notebook.updated),
            source_count=0,
            note_count=0,
            owner=getattr(notebook, "owner", None),
            collaborative=bool(getattr(notebook, "collaborative", False)),
            is_owner=(getattr(notebook, "owner", None) == user_id),
            navy_doc_ids=getattr(notebook, "navy_doc_ids", None) or [],
        )
    except HTTPException:
        raise
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating notebook {notebook_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating notebook: {str(e)}"
        )


@router.put("/notebooks/{notebook_id}/navy-docs", response_model=NotebookResponse)
async def update_notebook_navy_docs(
    notebook_id: str,
    body: UpdateNavyDocsRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """Update the shared navy-corpus document selection for a notebook.

    The selection is shared content (like sources/notes), so any member — not
    just the owner — may change it for a collaborative notebook. Access is
    gated by ``assert_can_read_notebook`` (owner/admin/member).
    """
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        await assert_can_read_notebook(
            getattr(notebook, "owner", None), notebook_id, request
        )

        # De-duplicate while preserving order; enforce the 15-doc UI cap.
        seen: set = set()
        deduped: List[str] = []
        for doc_id in body.doc_ids:
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                deduped.append(doc_id)
        deduped = deduped[:15]

        # For a collaborative notebook the selection is shared and must stay
        # within the notebook's effective (most-restrictive) access — drop any
        # doc the effective clearance/departments can't reach, so a member can't
        # attach corpus another member couldn't see.
        if getattr(notebook, "collaborative", False):
            from open_notebook.collaboration import effective_navy_filter
            from open_notebook.search.navy_docs import filter_allowed_doc_ids

            deduped = await filter_allowed_doc_ids(
                deduped, effective_navy_filter(notebook)
            )
        notebook.navy_doc_ids = deduped
        await notebook.save()

        query = """
            SELECT *,
            count(<-reference.in) as source_count,
            count(<-artifact.in) as note_count,
            count((SELECT id FROM notebook_member WHERE notebook = $parent.id)) as member_count
            FROM $notebook_id
        """
        result = await repo_query(
            query, {"notebook_id": ensure_record_id(notebook_id)}
        )
        if result:
            return _to_notebook_response(result[0], user_id)
        # Fallback: build straight from the saved model.
        return NotebookResponse(
            id=notebook.id or "",
            name=notebook.name,
            description=notebook.description,
            archived=notebook.archived or False,
            created=str(notebook.created),
            updated=str(notebook.updated),
            source_count=0,
            note_count=0,
            owner=getattr(notebook, "owner", None),
            collaborative=bool(getattr(notebook, "collaborative", False)),
            is_owner=(getattr(notebook, "owner", None) == user_id),
            navy_doc_ids=notebook.navy_doc_ids or [],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating navy docs for {notebook_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating navy docs: {str(e)}"
        )


@router.post("/notebooks/{notebook_id}/sources/{source_id}")
async def add_source_to_notebook(
    notebook_id: str, source_id: str, request: Request
):
    """Add an existing source to a notebook (create the reference)."""
    try:
        # Notebook must be readable by the caller (owner/admin/member). Members
        # of a collaborative notebook may contribute sources to it.
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        await assert_can_read_notebook(
            getattr(notebook, "owner", None), notebook_id, request
        )

        # You may only link a source you own — prevents pulling another user's
        # private source into a shared notebook they didn't consent to share.
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        assert_owns(getattr(source, "owner", None), request)

        # Check if reference already exists (idempotency)
        existing_ref = await repo_query(
            "SELECT * FROM reference WHERE out = $source_id AND in = $notebook_id",
            {
                "notebook_id": ensure_record_id(notebook_id),
                "source_id": ensure_record_id(source_id),
            },
        )

        # If reference doesn't exist, create it
        if not existing_ref:
            await repo_query(
                "RELATE $source_id->reference->$notebook_id",
                {
                    "notebook_id": ensure_record_id(notebook_id),
                    "source_id": ensure_record_id(source_id),
                },
            )

        return {"message": "Source linked to notebook successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error linking source {source_id} to notebook {notebook_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Error linking source to notebook: {str(e)}"
        )


@router.delete("/notebooks/{notebook_id}/sources/{source_id}")
async def remove_source_from_notebook(
    notebook_id: str, source_id: str, request: Request
):
    """Remove a source from a notebook (delete the reference).

    Owner-only: only the notebook owner (or an admin) may remove sources from a
    shared notebook — members can contribute sources but cannot unlink them.
    """
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        assert_owns(getattr(notebook, "owner", None), request)

        # Delete the reference record linking source to notebook
        await repo_query(
            "DELETE FROM reference WHERE out = $notebook_id AND in = $source_id",
            {
                "notebook_id": ensure_record_id(notebook_id),
                "source_id": ensure_record_id(source_id),
            },
        )

        return {"message": "Source removed from notebook successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error removing source {source_id} from notebook {notebook_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Error removing source from notebook: {str(e)}"
        )


@router.delete("/notebooks/{notebook_id}", response_model=NotebookDeleteResponse)
async def delete_notebook(
    notebook_id: str,
    delete_exclusive_sources: bool = Query(
        False,
        description="Whether to delete sources that belong only to this notebook",
    ),
    user_id: str = Depends(get_current_user_id),
):
    """
    Delete a notebook with cascade deletion.

    Always deletes all notes associated with the notebook.
    If delete_exclusive_sources is True, also deletes sources that belong only
    to this notebook (not linked to any other notebooks).
    """
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        _ensure_owner(getattr(notebook, "owner", None), user_id)

        # Remove collaboration metadata (members + invites) before the notebook
        # itself is deleted.
        await delete_notebook_collaboration(notebook_id)

        result = await notebook.delete(delete_exclusive_sources=delete_exclusive_sources)

        return NotebookDeleteResponse(
            message="Notebook deleted successfully",
            deleted_notes=result["deleted_notes"],
            deleted_sources=result["deleted_sources"],
            unlinked_sources=result["unlinked_sources"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting notebook {notebook_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error deleting notebook: {str(e)}"
        )
