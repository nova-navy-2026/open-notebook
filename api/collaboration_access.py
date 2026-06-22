"""Membership-aware access checks for collaborative notebooks.

The base app gates everything by ``owner == me`` (see ``api/auth.py``). Once a
notebook can be *shared*, sources and notes must also be reachable by its
members. These helpers extend the owner check to "owner OR member of a
collaborative notebook that contains this resource", while leaving every
mutation/owner-only path on the stricter ``assert_owns`` check.

All denials raise 404 (not 403) to match the existing fail-closed convention —
we never reveal that a resource the caller can't reach exists.
"""

from typing import List, Optional

from fastapi import HTTPException, Request

from api.auth import is_admin
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.collaboration import get_member_notebook_ids


def _user_id(request: Request) -> str:
    return getattr(request.state, "user_id", "anonymous")


async def user_member_notebook_ids(user_id: str) -> List[str]:
    """Notebook ids the user is a member of (excludes pure ownership)."""
    return await get_member_notebook_ids(user_id)


async def _resource_in_member_notebook(
    resource_id: str, relation: str, member_notebook_ids: List[str]
) -> bool:
    """True if ``resource_id`` is linked (via ``relation``) to any of the given
    notebooks. ``relation`` is ``reference`` for sources, ``artifact`` for notes
    (both point FROM the resource TO the notebook)."""
    if not member_notebook_ids:
        return False
    rows = await repo_query(
        f"SELECT id FROM {relation} WHERE in = $resource AND out IN $nbs LIMIT 1",
        {
            "resource": ensure_record_id(resource_id),
            "nbs": [ensure_record_id(n) for n in member_notebook_ids],
        },
    )
    return bool(rows)


async def assert_can_read_notebook(
    notebook_owner: Optional[str], notebook_id: str, request: Request
) -> None:
    """Allow owner, admin, or any member of the notebook to read it."""
    if is_admin(request):
        return
    user_id = _user_id(request)
    if notebook_owner is not None and notebook_owner == user_id:
        return
    member_ids = await user_member_notebook_ids(user_id)
    if str(notebook_id) in member_ids:
        return
    raise HTTPException(status_code=404, detail="Notebook not found")


async def assert_can_read_source(
    source_owner: Optional[str], source_id: str, request: Request
) -> None:
    """Allow owner, admin, or a member of a notebook containing the source."""
    if is_admin(request):
        return
    user_id = _user_id(request)
    if source_owner is not None and source_owner == user_id:
        return
    member_ids = await user_member_notebook_ids(user_id)
    if await _resource_in_member_notebook(source_id, "reference", member_ids):
        return
    raise HTTPException(status_code=404, detail="Source not found")


async def _notebook_owners_referencing(resource_id: str, relation: str) -> set:
    """Owners of every notebook that references ``resource_id`` via ``relation``.

    ``relation`` is ``reference`` for sources, ``artifact`` for notes (both link
    FROM the resource TO the notebook). Ownerless notebooks contribute nothing.
    """
    rows = await repo_query(
        f"SELECT VALUE out FROM {relation} WHERE in = $res",
        {"res": ensure_record_id(resource_id)},
    )
    if not rows:
        return set()
    owners = await repo_query(
        "SELECT VALUE owner FROM notebook WHERE id IN $nbs",
        {"nbs": [ensure_record_id(str(n)) for n in rows]},
    )
    return {str(o) for o in owners if o}


async def assert_can_edit_source(
    source_owner: Optional[str], source_id: str, request: Request
) -> None:
    """Allow the source creator, an owner of a notebook containing it, or admin.

    Members of a shared notebook who did NOT create the source cannot edit it,
    but the notebook owner can curate any source contributed to their notebook.
    """
    if is_admin(request):
        return
    user_id = _user_id(request)
    if source_owner is not None and source_owner == user_id:
        return
    if user_id in await _notebook_owners_referencing(source_id, "reference"):
        return
    raise HTTPException(status_code=404, detail="Source not found")


async def assert_can_delete_source(
    source_owner: Optional[str], source_id: str, request: Request
) -> None:
    """Govern source deletion by notebook ownership.

    - An owner of any notebook that contains the source may delete it (the
      notebook owner curates shared content).
    - The source creator may delete their own source ONLY while it is not shared
      into a notebook owned by someone else (i.e. it is still effectively
      private to them).
    - Everyone else (including members of a shared notebook) is denied.
    """
    if is_admin(request):
        return
    user_id = _user_id(request)
    owners = await _notebook_owners_referencing(source_id, "reference")
    if user_id in owners:
        return
    if (
        source_owner is not None
        and source_owner == user_id
        and not (owners - {user_id})
    ):
        return
    raise HTTPException(status_code=404, detail="Source not found")


async def assert_can_read_note(
    note_owner: Optional[str], note_id: str, request: Request
) -> None:
    """Allow owner, admin, or a member of a notebook containing the note."""
    if is_admin(request):
        return
    user_id = _user_id(request)
    if note_owner is not None and note_owner == user_id:
        return
    member_ids = await user_member_notebook_ids(user_id)
    if await _resource_in_member_notebook(note_id, "artifact", member_ids):
        return
    raise HTTPException(status_code=404, detail="Note not found")
