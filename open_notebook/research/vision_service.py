"""
Vision service - calls NOVA-Researcher API for image analysis via MCP vision tool.

Flow: open-notebook backend → NOVA-Researcher API /vision/analyze → mcp_vision.py (SAM3)
"""

import os
from typing import Any, Dict, Optional

import httpx
from loguru import logger

# NOVA-Researcher API base URL
NOVA_RESEARCHER_URL = os.environ.get("NOVA_RESEARCHER_URL", "http://localhost:8002").rstrip("/")

# Map an Open-Notebook model `provider` value (as stored in the `model` table)
# to the provider name expected by NOVA-Researcher's `/vision/analyze` endpoint
# (which only knows about "qwen", "amalia" and "gemma").
_PROVIDER_TO_NOVA: Dict[str, str] = {
    "amalia": "amalia",
    "gemma": "gemma",
    # The only Ollama backend wired into NOVA-Researcher is Qwen.
    "ollama": "qwen",
    "qwen": "qwen",
}


async def _resolve_provider_from_defaults() -> Optional[str]:
    """
    Look up the admin-selected default *tools* model (falling back to the
    default chat model) and translate its `provider` into the NOVA-Researcher
    provider name. Returns ``None`` if nothing is configured or the provider
    is not one NOVA-Researcher knows about — the caller will then fall back
    to the NOVA-Researcher default (Qwen).
    """
    try:
        from open_notebook.ai.models import DefaultModels, Model

        defaults = await DefaultModels.get_instance()
        model_id = (
            getattr(defaults, "default_tools_model", None)
            or getattr(defaults, "default_chat_model", None)
        )
        if not model_id:
            return None

        try:
            model = await Model.get(model_id)
        except Exception:
            logger.warning(f"Default tools model {model_id} not found in DB")
            return None

        prov = (model.provider or "").lower().strip()
        nova_prov = _PROVIDER_TO_NOVA.get(prov)
        if nova_prov:
            logger.info(
                f"Vision: resolved provider from default tools model "
                f"{model.name!r} ({prov}) → {nova_prov}"
            )
            return nova_prov

        logger.info(
            f"Vision: default tools model provider {prov!r} not supported by "
            f"NOVA-Researcher; using its built-in default."
        )
        return None
    except Exception as e:
        logger.warning(f"Vision: could not resolve default provider: {e}")
        return None


async def run_vision_analysis(
    image_path: str,
    query: Optional[str],
    engine: str = "sam3",
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run image analysis by calling the NOVA-Researcher /vision/analyze endpoint.

    Args:
        query: text prompt. Required for ``sam3``; optional for ``rfdetr``
               (``None``/empty triggers prompt-free detection).
        engine: "sam3" (default) or "rfdetr"
        provider: explicit provider override ("qwen" | "amalia" | "gemma").
                  When ``None`` (the usual case), the admin-selected default
                  tools/chat model is used to pick the provider automatically.

    Returns:
        {"text": "...", "image_base64": "data:image/png;base64,..." | null}
    """
    q_log = query[:100] if query else "<none>"
    logger.info(f"Starting vision analysis via NOVA-Researcher API ({engine}): '{q_log}'")

    # If the caller didn't pin a provider, honour the admin's default
    # tools model selection from the Models settings page.
    if not provider and engine == "sam3":
        provider = await _resolve_provider_from_defaults()

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(image_path, "rb") as f:
                files = {"image": (os.path.basename(image_path), f, "image/png")}
                data: Dict[str, str] = {"engine": engine}
                if query:
                    data["query"] = query
                if provider:
                    data["provider"] = provider
                resp = await client.post(
                    f"{NOVA_RESEARCHER_URL}/vision/analyze",
                    files=files,
                    data=data,
                )

        resp.raise_for_status()
        result = resp.json()

        logger.success(f"Vision analysis completed. Report length: {len(result.get('text', ''))}")

        return {
            "text": result.get("text", ""),
            "image_base64": result.get("image_base64"),
        }

    except Exception as e:
        logger.error(f"Vision analysis error: {e}")
        raise
