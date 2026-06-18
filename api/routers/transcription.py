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
from time import perf_counter
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from loguru import logger

from api.auth import get_current_user_id
from api.chat_agent_log_service import build_chat_agent_event, write_chat_agent_event
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


async def _write_transcription_tool_log(
    *,
    user_id: str,
    surface: str,
    run_id: Optional[str],
    session_id: Optional[str],
    notebook_id: Optional[str],
    model_id: Optional[str],
    status: str,
    duration_ms: Optional[int],
    filename: Optional[str],
    content_type: Optional[str],
    size: Optional[int],
    details: dict,
) -> None:
    await write_chat_agent_event(
        build_chat_agent_event(
            source="backend",
            user_id=user_id,
            surface=surface or "global_chat",
            run_id=run_id,
            session_id=session_id,
            notebook_id=notebook_id,
            model_id=model_id,
            agent="transcription",
            event="tool_call",
            status=status,
            file={"name": filename, "type": content_type, "size": size},
            duration_ms=duration_ms,
            details=details,
        )
    )


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
    surface: str = Form("global_chat"),
    run_id: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    notebook_id: Optional[str] = Form(None),
    model_id: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
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
    started_at = perf_counter()
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

    # Normalize to 16 kHz mono WAV before sending to Whisper.
    # VBR-encoded MP3/OGG/AAC files can cause Whisper to return HTTP 500 with
    # "X samples instead of expected Y samples" when the chunk boundary doesn't
    # align perfectly with the VBR frame grid.
    norm_path = saved_path
    if ext != ".wav":
        _norm_path = saved_path + "_norm.wav"
        try:
            import subprocess
            _ffmpeg_result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", saved_path,
                    "-vn",
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    _norm_path,
                ],
                capture_output=True,
                timeout=120,
            )
            if _ffmpeg_result.returncode == 0 and os.path.getsize(_norm_path) > 1024:
                norm_path = _norm_path
                logger.info(
                    f"Normalized audio to 16 kHz WAV: {os.path.getsize(norm_path)} bytes"
                )
            else:
                logger.warning(
                    f"ffmpeg normalization returned {_ffmpeg_result.returncode}; "
                    "sending original to Whisper"
                )
        except (FileNotFoundError, subprocess.TimeoutExpired) as _e:
            logger.warning(f"ffmpeg not available for audio normalization: {_e}")

    norm_lang = (language or "").strip() or None
    logger.info(
        "ChatAgent tool start | agent=transcription tool=transcription.transcribe "
        "file={} content_type={} bytes={} language={!r} diarize={} speakers={}",
        audio.filename,
        audio.content_type,
        len(audio_bytes),
        norm_lang,
        diarize,
        (num_speakers, min_speakers, max_speakers),
    )
    await _write_transcription_tool_log(
        user_id=user_id,
        surface=surface,
        run_id=run_id,
        session_id=session_id,
        notebook_id=notebook_id,
        model_id=model_id,
        status="started",
        duration_ms=None,
        filename=audio.filename,
        content_type=audio.content_type,
        size=len(audio_bytes),
        details={
            "language": norm_lang,
            "diarize": diarize,
            "speakers": {
                "num": num_speakers,
                "min": min_speakers,
                "max": max_speakers,
            },
        },
    )

    # Resolve which speech-to-text engine the user picked on the
    # Settings → Models screen. The dispatch rules are:
    #   - provider == "whisper"  → use the local NOVA-Researcher whisper
    #                              server (this router's existing path)
    #   - any other provider     → route through Esperanto's AIFactory
    #                              (e.g. openai whisper-1, groq whisper-large)
    #   - no default configured  → fall back to the local whisper server
    stt_provider: Optional[str] = None
    stt_model_name: Optional[str] = None
    try:
        from open_notebook.ai.models import model_manager
        from open_notebook.ai.models import Model as ModelRecord

        defaults = await model_manager.get_defaults()
        default_stt_id = getattr(defaults, "default_speech_to_text_model", None)
        if default_stt_id:
            stt_record = await ModelRecord.get(default_stt_id)
            if stt_record is not None:
                stt_provider = stt_record.provider
                stt_model_name = stt_record.name
                logger.info(
                    f"Using configured default STT model: "
                    f"provider={stt_provider!r} model={stt_model_name!r}"
                )
    except Exception as e:
        logger.warning(
            f"Could not resolve default STT model, falling back to local "
            f"whisper server: {e}"
        )

    try:
        if stt_provider and stt_provider != "whisper":
            # Use Esperanto's STT factory for non-local providers
            # (e.g. openai whisper-1, groq whisper-large-v3).
            from open_notebook.ai.models import model_manager as _mm

            stt_model = await _mm.get_speech_to_text()
            if stt_model is None:
                raise RuntimeError(
                    f"Default STT model is set to provider '{stt_provider}' "
                    f"but the model could not be instantiated."
                )
            # Esperanto STT models expose .transcribe(file_path) or similar.
            transcribe_fn = getattr(stt_model, "atranscribe", None) or getattr(
                stt_model, "transcribe", None
            )
            if transcribe_fn is None:
                raise RuntimeError(
                    f"STT provider '{stt_provider}' does not expose a "
                    "transcribe() method."
                )
            import inspect

            call_kwargs = {}
            if norm_lang is not None:
                call_kwargs["language"] = norm_lang
            raw = transcribe_fn(norm_path, **call_kwargs)
            if inspect.isawaitable(raw):
                raw = await raw
            # Normalise to the shape the frontend expects.
            if isinstance(raw, str):
                result = {"text": raw, "segments": [], "speakers": [], "dialog": "",
                          "diarized": False, "language": norm_lang}
            elif isinstance(raw, dict):
                result = raw
            else:
                # Try to coerce a pydantic / dataclass-ish response
                result = {
                    "text": getattr(raw, "text", str(raw)),
                    "segments": getattr(raw, "segments", []) or [],
                    "speakers": getattr(raw, "speakers", []) or [],
                    "dialog": getattr(raw, "dialog", "") or "",
                    "diarized": False,
                    "language": getattr(raw, "language", norm_lang),
                }
            result.setdefault("provider", stt_provider)
            result.setdefault("model", stt_model_name)
            logger.success(
                "ChatAgent tool success | agent=transcription tool=transcription.transcribe "
                "duration_ms={} provider={} model={} chars={} diarized={}",
                round((perf_counter() - started_at) * 1000),
                result.get("provider"),
                result.get("model"),
                len(result.get("dialog") or result.get("text") or ""),
                result.get("diarized"),
            )
            await _write_transcription_tool_log(
                user_id=user_id,
                surface=surface,
                run_id=run_id,
                session_id=session_id,
                notebook_id=notebook_id,
                model_id=model_id,
                status="success",
                duration_ms=round((perf_counter() - started_at) * 1000),
                filename=audio.filename,
                content_type=audio.content_type,
                size=len(audio_bytes),
                details={
                    "provider": result.get("provider"),
                    "model": result.get("model"),
                    "language": result.get("language"),
                    "diarized": result.get("diarized"),
                    "response_chars": len(result.get("dialog") or result.get("text") or ""),
                },
            )
            return result

        # Default path: local NOVA-Researcher whisper server
        result = await run_transcription(
            audio_path=norm_path,
            filename=audio.filename if norm_path == saved_path else (Path(audio.filename or "audio").stem + ".wav"),
            content_type=audio.content_type if norm_path == saved_path else "audio/wav",
            language=norm_lang,
            diarize=bool(diarize),
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )
        result.setdefault("provider", "whisper")
        if stt_model_name:
            result.setdefault("model", stt_model_name)
        logger.success(
            "ChatAgent tool success | agent=transcription tool=transcription.transcribe "
            "duration_ms={} provider={} model={} chars={} diarized={}",
            round((perf_counter() - started_at) * 1000),
            result.get("provider"),
            result.get("model"),
            len(result.get("dialog") or result.get("text") or ""),
            result.get("diarized"),
        )
        await _write_transcription_tool_log(
            user_id=user_id,
            surface=surface,
            run_id=run_id,
            session_id=session_id,
            notebook_id=notebook_id,
            model_id=model_id,
            status="success",
            duration_ms=round((perf_counter() - started_at) * 1000),
            filename=audio.filename,
            content_type=audio.content_type,
            size=len(audio_bytes),
            details={
                "provider": result.get("provider"),
                "model": result.get("model"),
                "language": result.get("language"),
                "diarized": result.get("diarized"),
                "response_chars": len(result.get("dialog") or result.get("text") or ""),
            },
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "ChatAgent tool failure | agent=transcription tool=transcription.transcribe "
            "duration_ms={} error={}",
            round((perf_counter() - started_at) * 1000),
            e,
        )
        await _write_transcription_tool_log(
            user_id=user_id,
            surface=surface,
            run_id=run_id,
            session_id=session_id,
            notebook_id=notebook_id,
            model_id=model_id,
            status="failure",
            duration_ms=round((perf_counter() - started_at) * 1000),
            filename=audio.filename,
            content_type=audio.content_type,
            size=len(audio_bytes),
            details={"error_type": type(e).__name__, "error": str(e) or repr(e)},
        )
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        for _cleanup_path in {saved_path, norm_path}:
            try:
                os.remove(_cleanup_path)
            except OSError:
                pass
