"""Collaborative-notebook access rules.

A collaborative notebook is shared by several users. Its *effective* navy
access is the most restrictive over all members:

* effective clearance  = MIN of members' clearance levels
* effective departments = INTERSECTION of members' department sets

A user may only join a notebook if the department intersection stays
non-empty — i.e. every member shares at least one department, guaranteeing
they can all reach the same departmental corpus.

Member navy profiles (departments + clearance) are resolved from the navy
directory (``users.json``) **by email**, reusing
``open_notebook.access_control``. This module owns the rules; persistence of
members/invites lives in ``open_notebook.domain.collaboration``.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Set, Tuple

from loguru import logger

from open_notebook.access_control import (
    build_opensearch_filter_for_profile,
    get_user_by_email,
    user_clearance,
    user_departments,
)
from open_notebook.exceptions import InvalidInputError

# A member's navy profile: (set of departments, clearance level).
Profile = Tuple[Set[str], int]


def resolve_profile(email: Optional[str]) -> Profile:
    """Resolve a navy profile (departments, clearance) for an email.

    Users with no navy-directory entry get an empty department set and
    clearance 0 — which makes any department intersection empty and fails
    closed, exactly as required for collaboration eligibility.
    """
    match = get_user_by_email(email)
    if not match:
        return set(), 0
    _navy_id, entry = match
    return set(user_departments(entry)), user_clearance(entry)


def compute_effective_access(
    profiles: Iterable[Profile],
) -> Tuple[Optional[int], List[str]]:
    """Return (min_clearance, sorted intersection of departments).

    Returns ``(None, [])`` for an empty member set.
    """
    profiles = list(profiles)
    if not profiles:
        return None, []
    min_clearance = min(clearance for _depts, clearance in profiles)
    dept_sets = [depts for depts, _clearance in profiles]
    intersection: Set[str] = set(dept_sets[0])
    for depts in dept_sets[1:]:
        intersection &= depts
    return min_clearance, sorted(intersection)


def validate_can_add(member_emails: Iterable[str], candidate_email: str) -> Profile:
    """Validate that adding ``candidate_email`` keeps the notebook coherent.

    Raises ``InvalidInputError`` when the resulting department intersection
    would be empty (no shared department). Returns the candidate's resolved
    profile on success.
    """
    candidate_profile = resolve_profile(candidate_email)
    if not candidate_profile[0]:
        raise InvalidInputError(
            "This user has no department assigned and cannot join a shared notebook."
        )
    profiles = [resolve_profile(e) for e in member_emails] + [candidate_profile]
    _clearance, intersection = compute_effective_access(profiles)
    if not intersection:
        raise InvalidInputError(
            "This user shares no department with the current members, so they "
            "cannot be added to this notebook."
        )
    return candidate_profile


async def recompute_effective_access(notebook) -> None:
    """Recompute effective access from the notebook's members and persist it.

    ``collaborative`` is true while more than one member exists; when a
    notebook drops back to a single member (or none) it reverts to a private
    notebook and the effective fields are cleared.
    """
    from open_notebook.domain.collaboration import get_members

    members = await get_members(str(notebook.id))
    profiles = [resolve_profile(m.email) for m in members]
    min_clearance, departments = compute_effective_access(profiles)

    notebook.collaborative = len(members) > 1
    if notebook.collaborative:
        notebook.effective_clearance = min_clearance
        notebook.effective_departments = departments
        # Drop any previously-selected navy corpus docs that the (possibly now
        # lower) effective clearance / narrowed departments can no longer reach,
        # so they are no longer associated with the notebook.
        selected = getattr(notebook, "navy_doc_ids", None) or []
        if selected:
            from open_notebook.search.navy_docs import filter_allowed_doc_ids

            notebook.navy_doc_ids = await filter_allowed_doc_ids(
                selected, effective_navy_filter(notebook)
            )
    else:
        notebook.effective_clearance = None
        notebook.effective_departments = None
    await notebook.save()
    logger.info(
        f"Recomputed effective access for {notebook.id}: "
        f"collaborative={notebook.collaborative} clearance={notebook.effective_clearance} "
        f"departments={notebook.effective_departments}"
    )


def effective_navy_filter(notebook) -> Optional[dict]:
    """Build the OpenSearch ACL filter for a collaborative notebook's effective
    access. Returns ``None`` for non-collaborative notebooks (caller should fall
    back to the acting user's own filter)."""
    if not getattr(notebook, "collaborative", False):
        return None
    clearance = getattr(notebook, "effective_clearance", None)
    departments = getattr(notebook, "effective_departments", None) or []
    if clearance is None:
        # Collaborative but not yet computed — fail closed (match nothing).
        return {"bool": {"must_not": {"match_all": {}}}}
    return build_opensearch_filter_for_profile(clearance, departments)
