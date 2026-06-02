"""
Navigation API router — computes driving distance and time between
two Portuguese locations via NOVA-Researcher (OSRM + Nominatim).
"""

from time import perf_counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api.auth import get_current_user_id
from api.chat_agent_log_service import build_chat_agent_event, write_chat_agent_event
from open_notebook.research.navigation_service import compute_route

router = APIRouter()


class NavigationRequest(BaseModel):
    location_a: str = Field(..., min_length=1, description="Start location (Portugal)")
    location_b: str = Field(..., min_length=1, description="Destination (Portugal)")
    surface: str = "global_chat"
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    notebook_id: Optional[str] = None
    model_id: Optional[str] = None


async def _write_navigation_tool_log(
    *,
    req: NavigationRequest,
    user_id: str,
    status: str,
    duration_ms: Optional[int],
    details: dict,
) -> None:
    await write_chat_agent_event(
        build_chat_agent_event(
            source="backend",
            user_id=user_id,
            surface=req.surface or "global_chat",
            run_id=req.run_id,
            session_id=req.session_id,
            notebook_id=req.notebook_id,
            model_id=req.model_id,
            agent="route",
            event="tool_call",
            status=status,
            message_preview=f"{req.location_a} -> {req.location_b}",
            duration_ms=duration_ms,
            details=details,
        )
    )


@router.post("/navigation/route")
async def navigation_route(
    req: NavigationRequest,
    user_id: str = Depends(get_current_user_id),
):
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
    await _write_navigation_tool_log(
        req=req,
        user_id=user_id,
        status="started",
        duration_ms=None,
        details={"from": start, "to": destination},
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
        await _write_navigation_tool_log(
            req=req,
            user_id=user_id,
            status="success",
            duration_ms=round((perf_counter() - started_at) * 1000),
            details={
                "from": start,
                "to": destination,
                "distance_km": result.get("distance_km"),
                "duration_min": result.get("duration_min") or result.get("estimated_time"),
                "source": result.get("source"),
            },
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
        await _write_navigation_tool_log(
            req=req,
            user_id=user_id,
            status="failure",
            duration_ms=round((perf_counter() - started_at) * 1000),
            details={
                "from": start,
                "to": destination,
                "error_type": type(e).__name__,
                "error": detail,
            },
        )
        raise HTTPException(status_code=status if 400 <= status < 600 else 500, detail=detail)
