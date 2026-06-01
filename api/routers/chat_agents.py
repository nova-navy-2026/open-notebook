"""
Chat agent observability and routing endpoints.

The frontend emits lightweight lifecycle events here, and can ask Gemma to
route a chat message to the most appropriate app agent. Concrete tools still
execute in their own backend routers (vision, navigation, transcription).
"""

import json
import os
import re
from time import perf_counter
from typing import Any, Dict, Literal, Optional

import httpx
from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field

from api.auth import get_current_user_id
from api.chat_agent_log_service import (
    build_chat_agent_event,
    chat_agent_tool_log_path,
    write_chat_agent_event,
)
from api.chat_agents.registry import (
    agent_catalog_for_prompt,
    agent_names_for_prompt,
    agents_for_file_type,
    get_agent,
    list_agents,
    normalise_agent_name,
    parameters_for_prompt,
)

router = APIRouter()


class ChatAgentFileMetadata(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    size: Optional[int] = None


class ChatAgentLogRequest(BaseModel):
    surface: Literal["global_chat", "notebook_chat"] = Field(
        ..., description="Where the agent was selected"
    )
    agent: str = Field(..., min_length=1, max_length=80)
    event: str = Field(..., min_length=1, max_length=80)
    status: Literal["started", "selected", "success", "skipped", "failure", "info"] = "info"
    run_id: Optional[str] = Field(None, max_length=180)
    session_id: Optional[str] = Field(None, max_length=180)
    notebook_id: Optional[str] = Field(None, max_length=180)
    model_id: Optional[str] = Field(None, max_length=180)
    message_preview: Optional[str] = Field(None, max_length=500)
    file: Optional[ChatAgentFileMetadata] = None
    duration_ms: Optional[int] = Field(None, ge=0)
    details: Dict[str, Any] = Field(default_factory=dict)


class ChatAgentRouteRequest(BaseModel):
    surface: Literal["global_chat", "notebook_chat"]
    message: str = Field(..., min_length=1)
    run_id: Optional[str] = Field(None, max_length=180)
    session_id: Optional[str] = Field(None, max_length=180)
    notebook_id: Optional[str] = Field(None, max_length=180)
    model_id: Optional[str] = Field(None, max_length=180)
    has_file: bool = False
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    visual_follow_up: bool = False
    deep_research_enabled: bool = False


class ChatAgentRouteResponse(BaseModel):
    agent: str = Field(..., min_length=1)
    confidence: float = Field(ge=0, le=1)
    reason: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    handler: str = "normal_chat"
    instruction: Optional[str] = None
    source: Literal["gemma_router", "fallback"] = "gemma_router"


class ChatAgentCatalogItem(BaseModel):
    name: str
    description: str
    handler: str
    has_instruction: bool = False
    parameters: Dict[str, str] = Field(default_factory=dict)


def _agent_router_timeout() -> float:
    try:
        return float(os.environ.get("CHAT_AGENT_ROUTER_TIMEOUT", "180"))
    except ValueError:
        return 180.0


def _agent_router_enabled() -> bool:
    return os.environ.get("CHAT_AGENT_ROUTER_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
    }


def _gemma_base_url() -> str:
    url = os.environ.get("GEMMA_BASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("GEMMA_BASE_URL is not set in the environment.")
    return url


def _gemma_api_key() -> str:
    return os.environ.get("GEMMA_API_KEY", "")


def _gemma_model() -> str:
    raw = os.environ.get("GEMMA_SMART_LLM", "")
    return raw.split(":")[-1] if raw else "google/gemma-4-31B-it"


async def _call_gemma_router(prompt: str) -> str:
    timeout = _agent_router_timeout()
    payload = {
        "model": _gemma_model(),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
    }
    started_at = perf_counter()
    logger.info(
        "ChatAgent LLM start | provider=gemma purpose=agent_router model={} "
        "prompt_chars={} max_tokens={} timeout_s={}",
        payload["model"],
        len(prompt),
        payload["max_tokens"],
        timeout,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{_gemma_base_url()}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {_gemma_api_key()}"},
            )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        logger.success(
            "ChatAgent LLM success | provider=gemma purpose=agent_router "
            "duration_ms={} response_chars={}",
            round((perf_counter() - started_at) * 1000),
            len(text or ""),
        )
        return text
    except Exception as e:
        logger.error(
            "ChatAgent LLM failure | provider=gemma purpose=agent_router "
            "duration_ms={} error_type={} error={}",
            round((perf_counter() - started_at) * 1000),
            type(e).__name__,
            str(e) or repr(e),
        )
        raise


def _fallback_route(request: ChatAgentRouteRequest, reason: str) -> ChatAgentRouteResponse:
    file_type = (request.file_type or "").lower()
    text = request.message.lower()

    if request.has_file and file_type:
        matching_file_agents = list(agents_for_file_type(file_type))
        for agent in matching_file_agents:
            if agent.fallback_keywords and any(word in text for word in agent.fallback_keywords):
                return _route_response_for_agent(
                    agent.name,
                    confidence=0.72,
                    reason=reason,
                    source="fallback",
                )
        if matching_file_agents:
            preferred = next(
                (
                    agent
                    for agent in matching_file_agents
                    if agent.name in {"multimodal", "transcription"}
                ),
                matching_file_agents[0],
            )
            return _route_response_for_agent(
                preferred.name,
                confidence=0.7,
                reason=reason,
                source="fallback",
            )

    for agent in list_agents():
        if agent.fallback_keywords and any(word in text for word in agent.fallback_keywords):
            return _route_response_for_agent(
                agent.name,
                confidence=0.55,
                reason=reason,
                source="fallback",
            )

    return _route_response_for_agent(
        "normal_chat",
        confidence=0.4,
        reason=reason,
        source="fallback",
    )


def _extract_json_object(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        raise ValueError("Gemma router response did not contain JSON.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Gemma router JSON was not an object.")
    return parsed


def _route_response_for_agent(
    agent_name: str,
    confidence: float,
    reason: str,
    source: Literal["gemma_router", "fallback"],
    parameters: Optional[Dict[str, Any]] = None,
) -> ChatAgentRouteResponse:
    normalised = normalise_agent_name(agent_name)
    agent = get_agent(normalised)
    return ChatAgentRouteResponse(
        agent=normalised,
        confidence=max(0.0, min(1.0, confidence)),
        reason=reason,
        parameters=parameters or {},
        handler=agent.handler if agent else "normal_chat",
        instruction=agent.instruction if agent else None,
        source=source,
    )


def _build_router_prompt(request: ChatAgentRouteRequest) -> str:
    return f"""
És o router de agentes de uma aplicação de investigação naval.

Tarefa: escolher exatamente UM agente para processar a mensagem do utilizador.

Agentes disponíveis:
{agent_catalog_for_prompt()}

Regras:
- Se houver ficheiro de imagem/vídeo, prefere multimodal/ocr/image_detection/video_tracking conforme a intenção.
- Se houver ficheiro de áudio, prefere transcription.
- Se a intenção for ambígua, usa normal_chat.
- Não inventes ferramentas.
- Devolve APENAS JSON válido.

Schema:
{{
  "agent": "{agent_names_for_prompt()}",
  "confidence": 0.0,
  "reason": "curto",
  "parameters": {parameters_for_prompt()}
}}

Dados:
- surface: {request.surface}
- has_file: {request.has_file}
- file_type: {request.file_type or ""}
- file_name: {request.file_name or ""}
- visual_follow_up: {request.visual_follow_up}
- deep_research_enabled: {request.deep_research_enabled}

Mensagem:
{request.message}
""".strip()


async def _write_structured_router_log(
    *,
    request: ChatAgentRouteRequest,
    user_id: str,
    status: Literal["success", "skipped", "failure"],
    duration_ms: int,
    details: Dict[str, Any],
) -> None:
    await write_chat_agent_event(
        build_chat_agent_event(
            source="backend",
            user_id=user_id,
            surface=request.surface,
            run_id=request.run_id,
            session_id=request.session_id,
            notebook_id=request.notebook_id,
            model_id=request.model_id,
            agent="agent_router",
            event="router_call",
            status=status,
            message_preview=request.message[:180],
            file={
                "name": request.file_name,
                "type": request.file_type,
            }
            if request.has_file
            else None,
            duration_ms=duration_ms,
            details={
                "has_file": request.has_file,
                "visual_follow_up": request.visual_follow_up,
                "deep_research_enabled": request.deep_research_enabled,
                **details,
            },
        )
    )


@router.post("/chat-agents/log")
async def log_chat_agent_event(
    event: ChatAgentLogRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Log a frontend chat-agent lifecycle event in the API logs."""
    safe_details = {
        key: value
        for key, value in event.details.items()
        if isinstance(key, str) and len(key) <= 80
    }
    logger.info(
        "ChatAgent event | user={} surface={} agent={} event={} status={} "
        "run={} session={} notebook={} model={} duration_ms={} file={} "
        "message_preview={!r} details={}",
        user_id or "anonymous",
        event.surface,
        event.agent,
        event.event,
        event.status,
        event.run_id,
        event.session_id,
        event.notebook_id,
        event.model_id,
        event.duration_ms,
        event.file.model_dump(exclude_none=True) if event.file else None,
        event.message_preview,
        safe_details,
    )
    structured = build_chat_agent_event(
        source="frontend",
        user_id=user_id,
        surface=event.surface,
        run_id=event.run_id,
        session_id=event.session_id,
        notebook_id=event.notebook_id,
        model_id=event.model_id,
        agent=event.agent,
        event=event.event,
        status=event.status,
        message_preview=event.message_preview,
        file=event.file.model_dump(exclude_none=True) if event.file else None,
        duration_ms=event.duration_ms,
        details=safe_details,
    )
    written = await write_chat_agent_event(structured)
    return {
        "success": True,
        "structured_log_written": written,
        "log_path": str(chat_agent_tool_log_path()),
    }


@router.get("/chat-agents", response_model=list[ChatAgentCatalogItem])
async def list_chat_agents():
    """Return the backend-registered chat-agent catalog."""
    return [
        ChatAgentCatalogItem(
            name=agent.name,
            description=agent.description,
            handler=agent.handler,
            has_instruction=bool(agent.instruction),
            parameters=agent.parameters,
        )
        for agent in list_agents()
    ]


@router.post("/chat-agents/route", response_model=ChatAgentRouteResponse)
async def route_chat_agent(
    request: ChatAgentRouteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Ask Gemma to choose the best chat agent for this turn."""
    if not _agent_router_enabled():
        response = _fallback_route(request, "Gemma agent router disabled.")
        await _write_structured_router_log(
            request=request,
            user_id=user_id,
            status="skipped",
            duration_ms=0,
            details={
                "reason": "router_disabled",
                "selected_agent": response.agent,
                "confidence": response.confidence,
                "route_source": response.source,
            },
        )
        return response

    started_at = perf_counter()
    logger.info(
        "ChatAgent router start | user={} surface={} has_file={} file_type={} "
        "visual_follow_up={} deep_research_enabled={} message_preview={!r}",
        user_id or "anonymous",
        request.surface,
        request.has_file,
        request.file_type,
        request.visual_follow_up,
        request.deep_research_enabled,
        request.message[:180],
    )
    try:
        raw = await _call_gemma_router(_build_router_prompt(request))
        payload = _extract_json_object(raw)
        confidence = payload.get("confidence", 0)
        try:
            confidence_value = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence_value = 0.0
        response = _route_response_for_agent(
            str(payload.get("agent") or "normal_chat"),
            confidence=confidence_value,
            reason=str(payload.get("reason") or "")[:300],
            parameters=payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {},
            source="gemma_router",
        )
        logger.success(
            "ChatAgent router success | user={} surface={} agent={} confidence={} "
            "duration_ms={} reason={!r} parameters={}",
            user_id or "anonymous",
            request.surface,
            response.agent,
            response.confidence,
            round((perf_counter() - started_at) * 1000),
            response.reason,
            response.parameters,
        )
        await _write_structured_router_log(
            request=request,
            user_id=user_id,
            status="success",
            duration_ms=round((perf_counter() - started_at) * 1000),
            details={
                "selected_agent": response.agent,
                "confidence": response.confidence,
                "reason": response.reason,
                "route_source": response.source,
                "handler": response.handler,
                "parameters": response.parameters,
            },
        )
        return response
    except Exception as e:
        duration_ms = round((perf_counter() - started_at) * 1000)
        logger.error(
            "ChatAgent router failure | user={} surface={} duration_ms={} "
            "error_type={} error={}",
            user_id or "anonymous",
            request.surface,
            duration_ms,
            type(e).__name__,
            str(e) or repr(e),
        )
        response = _fallback_route(request, f"Gemma agent router failed: {type(e).__name__}")
        await _write_structured_router_log(
            request=request,
            user_id=user_id,
            status="failure",
            duration_ms=duration_ms,
            details={
                "error_type": type(e).__name__,
                "error": str(e) or repr(e),
                "selected_agent": response.agent,
                "confidence": response.confidence,
                "route_source": response.source,
            },
        )
        return response
