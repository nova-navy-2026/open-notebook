"""Resolve a stored ``owner`` id into flag attribution fields.

Request-driven code reads the caller's identity straight off ``request.state``
(see ``api/risk_scan.py``). Background workers (source processing) only have
the record's ``owner``, so they resolve identity from the database + navy
users directory here instead.

Best-effort by design: an unresolvable owner still produces a usable flag,
just with less attribution.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger


async def identity_for_owner(owner: Optional[str]) -> Dict[str, Any]:
    """Return flag attribution kwargs for a ``user:xxx`` record id."""
    if not owner:
        return {}

    identity: Dict[str, Any] = {"user_id": owner}
    try:
        from open_notebook.domain.user import User

        record_id = owner if ":" in str(owner) else f"user:{owner}"
        db_user = await User.get(record_id)
        email = getattr(db_user, "email", None)
        if not email:
            return identity
        identity["user_email"] = email
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[risk] could not resolve owner {owner!r} to a user: {e}")
        return identity

    # Layer on the navy ACL profile (departments / clearance) when the email
    # is present in users.json.
    try:
        from open_notebook.access_control import (
            get_user_by_email,
            user_clearance,
            user_departments,
        )

        match = get_user_by_email(identity["user_email"])
        if match:
            navy_id, entry = match
            identity["navy_user_id"] = navy_id
            identity["departments"] = user_departments(entry)
            identity["clearance_level"] = user_clearance(entry)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[risk] could not resolve navy profile for {owner!r}: {e}")

    return identity
