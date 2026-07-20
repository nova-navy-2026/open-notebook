"""Runtime capability flags for the frontend.

This deployment usually runs on a closed LAN. Features that need the public
internet (ingesting a source from a URL, web/academic research) are therefore
gated on an actual connectivity probe rather than hard-coded on or off: if the
system does have internet, they light up; if it doesn't, the UI disables them
instead of letting users hit failures.

See ``open_notebook.utils.connectivity``.
"""

from fastapi import APIRouter, Query
from loguru import logger

from open_notebook.utils.connectivity import force_offline, internet_available

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("")
async def get_capabilities(
    refresh: bool = Query(
        False, description="Bypass the cache and re-probe connectivity now"
    ),
):
    """Report which internet-dependent features are currently usable.

    Cheap to call: the probe result is cached (see ``INTERNET_CHECK_TTL``), so
    the frontend can request this on load without adding latency.
    """
    try:
        online = await internet_available(force=refresh)
    except Exception as e:  # noqa: BLE001
        # Fail closed — never advertise a capability we could not confirm.
        logger.error(f"[capabilities] connectivity probe failed: {e}")
        online = False

    return {
        "internet": online,
        # Ingesting a source from a URL / website.
        "url_sources": online,
        # Deep research over the public web (Tavily) and academic APIs
        # (arxiv, pubmed, …). Corpus-backed research always works offline.
        "web_research": online,
        # True when the operator pinned the deployment offline via
        # FORCE_OFFLINE=1, rather than the probe simply failing.
        "forced_offline": force_offline(),
    }
