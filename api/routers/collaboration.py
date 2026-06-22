"""Collaborative-notebook endpoints: members and invitations.

Sharing model:
* Only the **owner** (or an admin) manages membership — invites, removals,
  link revocation. Members can read the roster.
* Invites are by **email** (single-use, targeted) or by **link** (a reusable
  token any eligible user can redeem until revoked). Both require the invitee
  to accept.
* Eligibility is enforced by ``open_notebook.collaboration.validate_can_add``:
  the department intersection across all members must stay non-empty. Effective
  clearance/departments are recomputed on every membership change.

Chat sessions stay per-user and are untouched here.
"""

import secrets
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from api.auth import assert_owns, get_current_user_id  # noqa: F401 (kept for parity)
from api.collaboration_access import assert_can_read_notebook
from api.models import (
    AcceptLinkRequest,
    CreateInviteRequest,
    NotebookInviteResponse,
    NotebookMemberResponse,
)
from open_notebook.collaboration import recompute_effective_access, validate_can_add
from open_notebook.domain.collaboration import (
    create_invite,
    create_member,
    delete_member,
    get_existing_pending_email_invite,
    get_invite,
    get_invite_by_token,
    get_member,
    get_members,
    get_notebook_invites,
    get_pending_invites_for_email,
    update_invite_status,
)
from open_notebook.domain.notebook import Notebook
from open_notebook.domain.user import User
from open_notebook.exceptions import InvalidInputError

router = APIRouter()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _current_email(request: Request) -> Optional[str]:
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        return user.get("email")
    return getattr(user, "email", None)


async def _resolve_user_email(user_id: Optional[str]) -> Optional[str]:
    """Resolve an auth user_id to its account email (navy directory key)."""
    if not user_id or not str(user_id).startswith("user:"):
        return None
    try:
        u = await User.get(str(user_id))
        return u.email
    except Exception:
        return None


async def _load_notebook(notebook_id: str) -> Notebook:
    notebook = await Notebook.get(notebook_id)
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return notebook


async def _load_owned_notebook(notebook_id: str, request: Request) -> Notebook:
    """Load a notebook and ensure the caller is its owner (or an admin)."""
    notebook = await _load_notebook(notebook_id)
    assert_owns(getattr(notebook, "owner", None), request)
    return notebook


async def _ensure_owner_member(notebook: Notebook) -> None:
    """Seed the owner's member row the first time a notebook is shared."""
    owner_id = getattr(notebook, "owner", None)
    if not owner_id:
        raise HTTPException(
            status_code=400,
            detail="This notebook has no owner account and cannot be shared.",
        )
    if await get_member(str(notebook.id), owner_id):
        return
    email = await _resolve_user_email(owner_id)
    if not email:
        raise HTTPException(
            status_code=400,
            detail="The notebook owner has no resolvable account email; "
            "collaboration requires a logged-in account.",
        )
    await create_member(
        str(notebook.id), owner_id, email, role="owner", added_by=owner_id
    )


def _invite_response(
    invite, notebook_name: Optional[str] = None
) -> NotebookInviteResponse:
    return NotebookInviteResponse(
        id=str(invite.id),
        notebook_id=str(invite.notebook),
        notebook_name=notebook_name,
        invite_type=invite.invite_type,
        email=invite.email,
        token=invite.token,
        status=invite.status,
        invited_by=invite.invited_by,
        created=str(invite.created),
    )


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------
@router.get(
    "/notebooks/{notebook_id}/members",
    response_model=List[NotebookMemberResponse],
)
async def list_members(notebook_id: str, request: Request):
    """List the members of a notebook (any member may view the roster)."""
    notebook = await _load_notebook(notebook_id)
    await assert_can_read_notebook(
        getattr(notebook, "owner", None), notebook_id, request
    )
    members = await get_members(notebook_id)
    return [
        NotebookMemberResponse(
            user_id=m.user_id,
            email=m.email,
            role=m.role,
            created=str(m.created),
        )
        for m in members
    ]


@router.delete("/notebooks/{notebook_id}/members/{member_user_id}")
async def remove_member(notebook_id: str, member_user_id: str, request: Request):
    """Remove a member (owner only). The owner cannot be removed this way."""
    notebook = await _load_owned_notebook(notebook_id, request)
    if member_user_id == getattr(notebook, "owner", None):
        raise HTTPException(
            status_code=400, detail="The owner cannot be removed from the notebook."
        )
    member = await get_member(notebook_id, member_user_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await delete_member(notebook_id, member_user_id)
    await recompute_effective_access(notebook)
    logger.info(f"Removed member {member_user_id} from notebook {notebook_id}")
    return {"message": "Member removed", "user_id": member_user_id}


# ---------------------------------------------------------------------------
# invites (owner-managed)
# ---------------------------------------------------------------------------
@router.post(
    "/notebooks/{notebook_id}/invites", response_model=NotebookInviteResponse
)
async def create_notebook_invite(
    notebook_id: str, body: CreateInviteRequest, request: Request
):
    """Create an email or link invite (owner only)."""
    notebook = await _load_owned_notebook(notebook_id, request)
    # Seed the owner member row + flip the notebook to collaborative.
    await _ensure_owner_member(notebook)
    await recompute_effective_access(notebook)

    member_emails = [m.email for m in await get_members(notebook_id)]

    if body.invite_type == "email":
        email = (body.email or "").strip().lower()
        if not email:
            raise HTTPException(
                status_code=400, detail="Email is required for an email invite."
            )
        # Already a member?
        if any(email == e.lower() for e in member_emails):
            raise HTTPException(
                status_code=409, detail="That user is already a member."
            )
        # Eligibility (department intersection) — fail fast for the owner.
        try:
            validate_can_add(member_emails, email)
        except InvalidInputError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # Reuse an existing pending invite (idempotent).
        existing = await get_existing_pending_email_invite(notebook_id, email)
        if existing:
            return _invite_response(existing, notebook.name)
        invite = await create_invite(
            notebook_id,
            invited_by=request.state.user_id,
            invite_type="email",
            email=email,
        )
        return _invite_response(invite, notebook.name)

    # Link invite — reusable token, eligibility checked at redemption time.
    token = secrets.token_urlsafe(32)
    invite = await create_invite(
        notebook_id,
        invited_by=request.state.user_id,
        invite_type="link",
        token=token,
    )
    return _invite_response(invite, notebook.name)


@router.get(
    "/notebooks/{notebook_id}/invites",
    response_model=List[NotebookInviteResponse],
)
async def list_notebook_invites(notebook_id: str, request: Request):
    """List a notebook's pending invites (owner only)."""
    notebook = await _load_owned_notebook(notebook_id, request)
    invites = await get_notebook_invites(notebook_id, status="pending")
    return [_invite_response(i, notebook.name) for i in invites]


@router.delete("/notebooks/{notebook_id}/invites/{invite_id}")
async def revoke_invite(notebook_id: str, invite_id: str, request: Request):
    """Revoke a pending invite or disable a share link (owner only)."""
    await _load_owned_notebook(notebook_id, request)
    invite = await get_invite(invite_id)
    # Ensure the invite belongs to this notebook (tolerate id with/without the
    # "notebook:" table prefix).
    nb_match = invite and str(invite.notebook).split(":")[-1] == str(
        notebook_id
    ).split(":")[-1]
    if not invite or not nb_match:
        raise HTTPException(status_code=404, detail="Invite not found")
    await update_invite_status(invite_id, "revoked")
    return {"message": "Invite revoked", "invite_id": invite_id}


# ---------------------------------------------------------------------------
# invitee-facing endpoints (notifications tab + accept/decline)
# ---------------------------------------------------------------------------
@router.get("/invites", response_model=List[NotebookInviteResponse])
async def my_invites(request: Request):
    """Pending email invites addressed to the current user (notifications tab)."""
    email = _current_email(request)
    if not email:
        return []
    invites = await get_pending_invites_for_email(email.strip().lower())
    out: List[NotebookInviteResponse] = []
    for inv in invites:
        name = None
        try:
            nb = await Notebook.get(str(inv.notebook))
            name = nb.name if nb else None
        except Exception:
            pass
        # Never leak the link token through the notifications feed.
        inv.token = None
        out.append(_invite_response(inv, name))
    return out


async def _join_notebook(
    notebook: Notebook, user_id: str, email: str, invited_by: Optional[str]
) -> None:
    """Validate eligibility and add the user as a member, then recompute."""
    if await get_member(str(notebook.id), user_id):
        return  # already a member — idempotent
    member_emails = [m.email for m in await get_members(str(notebook.id))]
    try:
        validate_can_add(member_emails, email)
    except InvalidInputError as e:
        raise HTTPException(status_code=403, detail=str(e))
    await create_member(
        str(notebook.id), user_id, email, role="member", added_by=invited_by
    )
    await recompute_effective_access(notebook)


@router.post("/invites/{invite_id}/accept")
async def accept_invite(invite_id: str, request: Request):
    """Accept an email invite addressed to the current user."""
    invite = await get_invite(invite_id)
    if not invite or invite.status != "pending":
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.invite_type != "email":
        raise HTTPException(
            status_code=400, detail="Use the share link to join this notebook."
        )
    email = (_current_email(request) or "").strip().lower()
    if not email or not invite.email or email != invite.email.strip().lower():
        raise HTTPException(
            status_code=403, detail="This invite is addressed to a different account."
        )
    notebook = await _load_notebook(str(invite.notebook))
    await _join_notebook(notebook, request.state.user_id, email, invite.invited_by)
    await update_invite_status(invite_id, "accepted", accepted_by=request.state.user_id)
    return {"message": "Invite accepted", "notebook_id": str(invite.notebook)}


@router.post("/invites/{invite_id}/decline")
async def decline_invite(invite_id: str, request: Request):
    """Decline an email invite addressed to the current user."""
    invite = await get_invite(invite_id)
    if not invite or invite.status != "pending":
        raise HTTPException(status_code=404, detail="Invite not found")
    email = (_current_email(request) or "").strip().lower()
    if invite.email and email != invite.email.strip().lower():
        raise HTTPException(
            status_code=403, detail="This invite is addressed to a different account."
        )
    await update_invite_status(invite_id, "declined", accepted_by=request.state.user_id)
    return {"message": "Invite declined"}


@router.post("/invites/accept-link")
async def accept_invite_link(body: AcceptLinkRequest, request: Request):
    """Redeem a share-link token to join a notebook (link stays reusable)."""
    invite = await get_invite_by_token(body.token)
    if not invite or invite.status != "pending" or invite.invite_type != "link":
        raise HTTPException(status_code=404, detail="Invalid or expired invite link")
    email = (_current_email(request) or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=403, detail="A logged-in account is required to join."
        )
    notebook = await _load_notebook(str(invite.notebook))
    await _join_notebook(notebook, request.state.user_id, email, invite.invited_by)
    # Link invites are reusable: do NOT mark accepted.
    return {"message": "Joined notebook", "notebook_id": str(invite.notebook)}
