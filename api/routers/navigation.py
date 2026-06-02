"""
Navigation API router — computes driving distance and time between
two Portuguese locations via NOVA-Researcher (OSRM + Nominatim).
"""

from time import perf_counter

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.research.navigation_service import compute_route

router = APIRouter()


class NavigationRequest(BaseModel):
    location_a: str = Field(..., min_length=1, description="Start location (Portugal)")
    location_b: str = Field(..., min_length=1, description="Destination (Portugal)")


@router.post("/navigation/route")
async def navigation_route(req: NavigationRequest):
    """
    Returns driving route info between two locations in Portugal.
    """
    started_at = perf_counter()
    start = req.location_a.strip()
    destination = req.location_b.strip()
    logger.info(
        "ChatAgent tool start | agent=route tool=navigation.route from={!r} to={!r}",
        start,
        destination,
    )
    try:
        result = await compute_route(start, destination)
        logger.success(
            "ChatAgent tool success | agent=route tool=navigation.route "
            "duration_ms={} distance_km={} duration_min={} source={}",
            round((perf_counter() - started_at) * 1000),
            result.get("distance_km"),
            result.get("duration_min") or result.get("estimated_time"),
            result.get("source"),
        )
        return result
    except Exception as e:
        logger.error(
            "ChatAgent tool failure | agent=route tool=navigation.route "
            "duration_ms={} error={}",
            round((perf_counter() - started_at) * 1000),
            e,
        )
        # Bubble up a useful error for the UI
        status = getattr(getattr(e, "response", None), "status_code", 500)
        detail = str(e)
        try:
            detail = e.response.json().get("detail", detail)  # type: ignore[attr-defined]
        except Exception:
            pass
        raise HTTPException(status_code=status if 400 <= status < 600 else 500, detail=detail)
