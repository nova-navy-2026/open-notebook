"""
Transcription API router — proxy to the NOVA-Researcher Whisper + Pyannote
tool server. Open-Notebook owns no transcription logic itself.

Endpoints:
- POST /api/transcription/transcribe : multipart audio upload → transcript (+diarization)
- GET  /api/transcription/capabilities: report which optional engines are available
"""

import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from loguru import logger

from open_notebook.research.transcription_service import (
    fetch_capabilities,
    run_transcription,
)

router = APIRouter()


# Directory for uploaded audio files. We delete each file after processing.
TRANSCRIPTION_UPLOADS_DIR = os.path.join("data", "transcription_uploads")
os.makedirs(TRANSCRIPTION_UPLOADS_DIR, exist_ok=True)

ALLOWED_AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
    ".ogg",
    ".oga",
    ".webm",
    ".mp4",
    ".aac",
    ".wma",
}
MAX_AUDIO_SIZE = 200 * 1024 * 1024  # 200 MB


@router.get("/transcription/capabilities")
async def transcription_capabilities():
    """Report which transcription / diarization backends are available."""
    caps = await fetch_capabilities()
    return {
        "diarization_available": bool(caps.get("diarization_available")),
        "diarization_unavailable_reason": (
            None
            if caps.get("server_reachable") and caps.get("diarization_available")
            else (caps.get("error") or "diarization disabled on the server")
        ),
        "server_reachable": bool(caps.get("server_reachable")),
        "server_url": caps.get("server_url"),
        "model": caps.get("model"),
        "device": caps.get("device"),
        "allowed_extensions": caps.get("allowed_extensions")
        or sorted(ALLOWED_AUDIO_EXTENSIONS),
        "max_audio_mb": MAX_AUDIO_SIZE // (1024 * 1024),
    }


@router.post("/transcription/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: Optional[str] = Form(None),
    diarize: bool = Form(False),
    num_speakers: Optional[int] = Form(None),
    min_speakers: Optional[int] = Form(None),
    max_speakers: Optional[int] = Form(None),
):
    """
    Transcribe an uploaded audio file by forwarding it to the
    NOVA-Researcher Whisper server. When ``diarize=true`` and the server
    reports pyannote.audio as available, the response also contains a
    speaker-labelled timeline.

    Form fields:
    - audio: audio file (wav, mp3, m4a, flac, ogg, webm, mp4 …)
    - language: ISO-639-1 code (e.g. "en", "pt", "fr"); empty → auto-detect
    - diarize: "true" / "false"
    - num_speakers / min_speakers / max_speakers: optional diarization hints
    """
    ext = Path(audio.filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported audio type '{ext}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}"
            ),
        )

    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file exceeds the {MAX_AUDIO_SIZE // (1024 * 1024)} MB limit.",
        )
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    file_id = uuid.uuid4().hex[:12]
    saved_filename = f"{file_id}{ext}"
    saved_path = os.path.abspath(
        os.path.join(TRANSCRIPTION_UPLOADS_DIR, saved_filename)
    )
    with open(saved_path, "wb") as f:
        f.write(audio_bytes)

    norm_lang = (language or "").strip() or None
    logger.info(
        f"Transcription requested: file={saved_path}, language={norm_lang!r}, "
        f"diarize={diarize}, speakers={(num_speakers, min_speakers, max_speakers)}"
    )

    try:
        result = await run_transcription(
            audio_path=saved_path,
            filename=audio.filename,
            content_type=audio.content_type,
            language=norm_lang,
            diarize=bool(diarize),
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        try:
            os.remove(saved_path)
        except OSError:
            pass
