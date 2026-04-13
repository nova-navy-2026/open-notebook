"""
Vision service - calls mcp_researcher.py for image analysis via MCP vision tool.

Flow: open-notebook backend → mcp_researcher.py → mcp_vision.py (SAM3)
"""

import base64
import glob
import os
import sys
from typing import Any, Dict, Optional

from loguru import logger

# Path to the NOVA-Researcher project (sibling directory)
_nova_researcher_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "NOVA-Researcher")
)
if _nova_researcher_path not in sys.path:
    sys.path.insert(0, _nova_researcher_path)

# Where mcp_vision.py saves annotated images
_vision_output_dir = os.path.join(_nova_researcher_path, "output_images")


def _setup_qwen_env() -> Dict[str, Optional[str]]:
    """Apply Qwen3/Ollama LLM env vars for vision and return the originals for restore.

    Vision analysis ALWAYS uses Qwen3 via Ollama because it supports tool calling,
    which is required for MCP vision tools. AMALIA does not support tool calling.
    """
    keys = [
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "SMART_LLM",
        "FAST_LLM", "STRATEGIC_LLM", "EMBEDDING", "OLLAMA_BASE_URL",
    ]
    saved: Dict[str, Optional[str]] = {}
    for k in keys:
        saved[k] = os.environ.get(k)

    qwen_vars = {
        "OLLAMA_BASE_URL": os.environ.get(
            "QWEN_OLLAMA_BASE_URL", "http://10.10.255.202:11434/"
        ),
        "SMART_LLM": os.environ.get("QWEN_SMART_LLM", "ollama:qwen3:8b"),
        "FAST_LLM": os.environ.get("QWEN_FAST_LLM", "ollama:qwen3:8b"),
        "STRATEGIC_LLM": os.environ.get("QWEN_STRATEGIC_LLM", "ollama:qwen3:8b"),
        "OPENAI_API_KEY": os.environ.get("AMALIA_API_KEY", "dummy"),
        "EMBEDDING": os.environ.get(
            "AMALIA_EMBEDDING", "huggingface:BAAI/bge-m3"
        ),
    }
    # Clear AMALIA-specific OpenAI base URL so GPTResearcher uses Ollama
    os.environ.pop("OPENAI_BASE_URL", None)
    for k, v in qwen_vars.items():
        os.environ[k] = v

    return saved


def _restore_env(saved: Dict[str, Optional[str]]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _image_to_base64(path: str) -> Optional[str]:
    """Read an image file and return it as a data-URI base64 string."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        return f"data:image/png;base64,{base64.b64encode(data).decode()}"
    except Exception as e:
        logger.warning(f"Could not read annotated image {path}: {e}")
        return None


async def run_vision_analysis(
    image_path: str,
    query: str,
) -> Dict[str, Any]:
    """
    Run image analysis by calling mcp_researcher → mcp_vision (SAM3).

    Returns:
        {"text": "...", "image_base64": "data:image/png;base64,..." | null}
    """
    from mcp_researcher import get_vision_config, run_mcp_vision

    vision_config = get_vision_config()

    # Build a query that tells the researcher to use the vision tool on this image
    research_query = f"{query} in the image {image_path}"

    saved_env = _setup_qwen_env()

    # Remember existing output images so we can detect the new one
    existing_outputs = set(glob.glob(os.path.join(_vision_output_dir, "annotated_*.png")))

    try:
        logger.info(f"Starting vision research via mcp_researcher: '{research_query[:100]}'")

        report = await run_mcp_vision(
            query=research_query,
            mcp_configs=[vision_config],
        )

        logger.success(f"Vision research completed. Report length: {len(report)}")

        # Detect newly created annotated image
        image_base64 = None
        current_outputs = set(glob.glob(os.path.join(_vision_output_dir, "annotated_*.png")))
        new_outputs = current_outputs - existing_outputs
        if new_outputs:
            newest = max(new_outputs, key=os.path.getmtime)
            image_base64 = _image_to_base64(newest)
            # Clean up the annotated file after reading
            try:
                os.remove(newest)
            except OSError:
                pass

        return {
            "text": report,
            "image_base64": image_base64,
        }

    except Exception as e:
        logger.error(f"Vision analysis error: {e}")
        raise
    finally:
        _restore_env(saved_env)
