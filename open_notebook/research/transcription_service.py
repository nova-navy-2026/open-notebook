"""
Transcription service — thin HTTP client to the NOVA-Researcher Whisper +
Pyannote tool server (`whisper_server.py`, default port 4805).

Open-Notebook owns no transcription logic itself. All heavy lifting
(Whisper transcription, optional pyannote diarization, segment merging)
runs in the dedicated server in NOVA-Researcher, mirroring the same
pattern used for SAM3, RF-DETR, CLIP and Nomic.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx
from loguru import logger


# Default to the local NOVA-Researcher whisper server.
def _get_whisper_url() -> str:
    base = os.environ.get("WHISPER_API_URL", "http://localhost:4805").rstrip("/")
    return f"{base}/transcribe"


def _get_capabilities_url() -> str:
    base = os.environ.get("WHISPER_API_URL", "http://localhost:4805").rstrip("/")
    return f"{base}/health"


# Long timeout: meeting / VHF recordings can take many minutes to process.
_HTTP_TIMEOUT = float(os.environ.get("WHISPER_API_TIMEOUT", "1800"))


async def fetch_capabilities() -> Dict[str, Any]:
    """Probe the whisper server for available features."""
    url = _get_capabilities_url()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            return {
                "diarization_available": bool(data.get("diarization_available")),
                "diarization_model": data.get("diarization_model"),
                "model": data.get("model"),
                "device": data.get("device"),
                "allowed_extensions": data.get("allowed_extensions") or [],
                "max_audio_bytes": int(data.get("max_audio_bytes") or 0),
                "server_reachable": True,
                "server_url": url,
            }
    except Exception as e:
        logger.warning(f"Whisper server not reachable at {url}: {e}")
        return {
            "diarization_available": False,
            "server_reachable": False,
            "server_url": url,
            "error": str(e),
        }


async def run_transcription(
    audio_path: str,
    *,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    language: Optional[str] = None,
    diarize: bool = False,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    vad_filter: bool = True,
) -> Dict[str, Any]:
    """
    Forward an audio file to the whisper server's ``/transcribe`` endpoint
    and return the parsed JSON response.

    The server response shape is:

    ``{text, segments[{start,end,text,speaker?}], speakers, dialog,
       diarized, language}``
    """
    url = _get_whisper_url()
    name = filename or os.path.basename(audio_path)
    ctype = content_type or "application/octet-stream"

    data: Dict[str, Any] = {
        "diarize": "true" if diarize else "false",
        "vad_filter": "true" if vad_filter else "false",
    }
    if language:
        data["language"] = language
    if num_speakers is not None:
        data["num_speakers"] = str(int(num_speakers))
    if min_speakers is not None:
        data["min_speakers"] = str(int(min_speakers))
    if max_speakers is not None:
        data["max_speakers"] = str(int(max_speakers))

    logger.info(
        f"POST {url}: file={name!r}, language={language!r}, diarize={diarize}"
    )

    with open(audio_path, "rb") as fh:
        files = {"file": (name, fh, ctype)}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(url, files=files, data=data)

    if response.status_code >= 400:
        # Try to surface the server's detail message verbatim.
        detail: Any
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(
            f"Whisper server returned {response.status_code}: {detail}"
        )

    return response.json()
