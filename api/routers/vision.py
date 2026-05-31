"""
Vision API router - endpoints for image analysis via MCP researcher.

Uses NOVA-Researcher GPTResearcher with the vision MCP config
(mcp_vision.py → SAM3) to analyze uploaded images.
"""

import base64
import math
import os
import re
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from open_notebook.research.vision_service import run_vision_analysis
from open_notebook.research.video_service import run_video_tracking

# Matches /api/vision/note-asset/<filename> paths embedded in markdown context.
_NOTE_ASSET_RE = re.compile(r"/api/vision/note-asset/([A-Za-z0-9_-]+\.[A-Za-z0-9]+)")

_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi"}

_VIDEO_FRAME_STRIDE = 15   # sample every N-th frame by default
_VIDEO_MAX_FRAMES   = 50   # hard cap; triggers adaptive stride when exceeded


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


def _extract_video_frames(video_path: str) -> List[bytes]:
    """
    Sample frames from a video at _VIDEO_FRAME_STRIDE intervals, up to
    _VIDEO_MAX_FRAMES total.  When the natural sample count would exceed the
    cap, the stride is recalculated to spread exactly _VIDEO_MAX_FRAMES frames
    evenly across the full video (adaptive stride).

    For videos with a known frame count, seek-based sampling is used (fast).
    For unknown-length sources, a sequential scan is used as fallback.
    Returns a list of JPEG-encoded frame bytes (may be empty on failure).
    """
    cap = cv2.VideoCapture(video_path)
    frames: List[bytes] = []
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total > 0:
            # Seek-based sampling — fast for indexed containers
            if total // _VIDEO_FRAME_STRIDE > _VIDEO_MAX_FRAMES:
                stride = max(1, math.ceil(total / _VIDEO_MAX_FRAMES))
            else:
                stride = _VIDEO_FRAME_STRIDE
            for pos in range(0, total, stride):
                if len(frames) >= _VIDEO_MAX_FRAMES:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ret, frame = cap.read()
                if not ret or frame is None:
                    continue
                ok, buf = cv2.imencode(".jpg", frame)
                if ok:
                    frames.append(bytes(buf))
        else:
            # Sequential scan for streams / containers without frame-count metadata
            current = 0
            while len(frames) < _VIDEO_MAX_FRAMES:
                ret, frame = cap.read()
                if not ret or frame is None:
                    break
                if current % _VIDEO_FRAME_STRIDE == 0:
                    ok, buf = cv2.imencode(".jpg", frame)
                    if ok:
                        frames.append(bytes(buf))
                current += 1
    finally:
        cap.release()
    return frames


def _extract_context_images(context: str, assets_dir: str) -> List[Tuple[bytes, str]]:
    """
    Scan context text for embedded /api/vision/note-asset/<filename> URLs.
    Returns a list of (image_bytes, mime_type) for each found asset:
    - images: read bytes directly
    - videos: sample up to _VIDEO_MAX_FRAMES frames (adaptive stride)
    """
    results: List[Tuple[bytes, str]] = []
    seen: set = set()

    for match in _NOTE_ASSET_RE.finditer(context):
        filename = match.group(1)
        if filename in seen:
            continue
        seen.add(filename)

        asset_path = os.path.abspath(os.path.join(assets_dir, filename))
        base = os.path.abspath(assets_dir)
        if not asset_path.startswith(base + os.sep):
            continue
        if not os.path.isfile(asset_path):
            logger.warning(f"Note asset not found on disk: {asset_path}")
            continue

        ext = Path(filename).suffix.lower()
        if ext in _VIDEO_EXTENSIONS:
            frames = _extract_video_frames(asset_path)
            if frames:
                for frame in frames:
                    results.append((frame, "image/jpeg"))
                logger.info(f"Extracted {len(frames)} frames from video asset: {filename}")
            else:
                logger.warning(f"Could not extract frames from: {filename}")
        else:
            with open(asset_path, "rb") as f:
                img_bytes = f.read()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
            mime = mime_map.get(ext, "image/jpeg")
            results.append((img_bytes, mime))
            logger.info(f"Loaded image asset: {filename}")

    return results


async def _call_gemma(
    prompt: str,
    images: Optional[List[Tuple[bytes, str]]] = None,
) -> str:
    """
    Call Gemma via OpenAI-compatible API with an optional list of images.
    Each image is (bytes, mime_type).
    """
    if images:
        content: list = [{"type": "text", "text": prompt}]
        for img_bytes, mime in images:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    else:
        content = prompt  # type: ignore[assignment]

    payload = {
        "model": _gemma_model(),
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{_gemma_base_url()}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {_gemma_api_key()}"},
        )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

router = APIRouter()

# Directory for uploaded vision files
VISION_UPLOADS_DIR = os.path.join("data", "vision_uploads")
os.makedirs(VISION_UPLOADS_DIR, exist_ok=True)

# Directory for persistent note assets (images/videos saved into notes)
VISION_NOTE_ASSETS_DIR = os.path.join("data", "vision_note_assets")
os.makedirs(VISION_NOTE_ASSETS_DIR, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi"}
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_VIDEO_SIZE = 200 * 1024 * 1024  # 200 MB

# Allowed MIME types for note assets and their canonical file extensions.
NOTE_ASSET_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}

# Hard limit on raw asset size (50 MB) to avoid abuse.
MAX_NOTE_ASSET_SIZE = 50 * 1024 * 1024

DATA_URL_RE = re.compile(r"^data:([^;,]+);base64,(.+)$", re.DOTALL)


@router.post("/vision/multimodal")
async def multimodal_chat(
    query: str = Form(...),
    context: Optional[str] = Form(None),
    mode: str = Form("chat"),
    file: Optional[UploadFile] = File(None),
):
    """
    Chat with notebook context using Gemma (vision-capable LLM).

    Accepts a multipart form with:
    - query: the user's question
    - context: pre-built context string sent from the client (optional)
    - mode: "chat" (default)
    - file: optional image for vision queries (PNG, JPG, JPEG, WEBP)

    Context is built client-side via /chat/context and passed as a plain
    text string; this endpoint just forwards it to Gemma.

    Returns JSON with:
    - text: the model's response
    """
    prompt = query
    if context and context.strip():
        prompt = f"{query}\n\n---\nContext:\n\n{context.strip()}"

    # Collect images: user-uploaded file first, then assets embedded in context
    images: List[Tuple[bytes, str]] = []

    if file and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image type '{ext}'. Allowed: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}",
            )
        file_bytes = await file.read()
        if len(file_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=413, detail="Image exceeds 20 MB limit.")
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        images.append((file_bytes, mime_map.get(ext, "image/jpeg")))

    if context:
        context_images = _extract_context_images(context, VISION_NOTE_ASSETS_DIR)
        images.extend(context_images)

    logger.info(
        f"Multimodal chat: mode={mode}, images={len(images)}, "
        f"context_len={len(context) if context else 0}, query={repr(query[:80])}"
    )

    try:
        text = await _call_gemma(prompt, images or None)
        return {"text": text}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPStatusError as e:
        logger.error(f"Gemma API error: {e.response.status_code} {e.response.text[:200]}")
        raise HTTPException(status_code=502, detail=f"Gemma API returned {e.response.status_code}")
    except Exception as e:
        logger.error(f"Multimodal chat failed: {e}")
        raise HTTPException(status_code=500, detail=f"Multimodal chat failed: {e}")


@router.post("/vision/image-analysis")
async def analyze_image(
    image: UploadFile = File(...),
    query: Optional[str] = Form(None),
    engine: str = Form("sam3"),
    provider: Optional[str] = Form(None),
):
    """
    Analyze an uploaded image using the MCP vision researcher.

    Accepts a multipart form with:
    - image: the image file (PNG, JPG, JPEG, WEBP)
    - query: the user's question / analysis request.
             Required for ``engine='sam3'``; optional for ``engine='rfdetr'``
             (where an empty query triggers class-agnostic detection).
    - engine: "sam3" (default) or "rfdetr"

    Returns JSON with:
    - text: the analysis report text
    - image_base64: base64-encoded annotated image (if produced), or null
    """
    # Validate file extension
    ext = Path(image.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type '{ext}'. Allowed: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}",
        )

    # Read and validate size
    image_bytes = await image.read()
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="Image exceeds 20 MB limit.")

    engine_norm = (engine or "sam3").lower().strip()
    if engine_norm not in {"sam3", "rfdetr"}:
        raise HTTPException(status_code=400, detail=f"Invalid engine '{engine}'. Must be 'sam3' or 'rfdetr'.")

    # Normalise query: empty / whitespace-only → None.
    normalised_query: Optional[str] = query.strip() if (query and query.strip()) else None

    # SAM3 is open-vocabulary → needs a prompt. RF-DETR can run prompt-free.
    if engine_norm == "sam3" and not normalised_query:
        raise HTTPException(
            status_code=400,
            detail="Query is required for the SAM3 engine. Switch to 'rfdetr' for prompt-free detection.",
        )

    # Save to a unique file so the MCP tool can read it by path
    file_id = uuid.uuid4().hex[:12]
    saved_filename = f"{file_id}{ext}"
    saved_path = os.path.abspath(os.path.join(VISION_UPLOADS_DIR, saved_filename))

    with open(saved_path, "wb") as f:
        f.write(image_bytes)

    logger.info(
        f"Vision analysis requested: engine={engine_norm}, "
        f"query={'<none>' if normalised_query is None else repr(normalised_query[:80])}, "
        f"image={saved_path}"
    )

    try:
        result = await run_vision_analysis(
            image_path=saved_path,
            query=normalised_query,
            engine=engine_norm,
            provider=provider,
        )
        return result

    except Exception as e:
        logger.error(f"Vision analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Image analysis failed: {e}")
    finally:
        # Clean up the uploaded file
        try:
            os.remove(saved_path)
        except OSError:
            pass


@router.post("/vision/video-tracking")
async def track_video(
    video: UploadFile = File(...),
    target: Optional[str] = Form(None),
    engine: str = Form("sam3"),
):
    """
    Track an object across video frames using SAM3 or RF-DETR.

    Accepts a multipart form with:
    - video: the video file (MP4, WEBM, MOV, AVI)
    - target: the object to track (e.g. "red car", "boat").
              Required for ``engine='sam3'``; optional for ``engine='rfdetr'``.
    - engine: "sam3" (default) or "rfdetr"

    Returns JSON with:
    - text: markdown tracking summary
    - video_base64: base64-encoded annotated video (data URI)
    """
    ext = Path(video.filename or "").suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video type '{ext}'. Allowed: {', '.join(ALLOWED_VIDEO_EXTENSIONS)}",
        )

    video_bytes = await video.read()
    if len(video_bytes) > MAX_VIDEO_SIZE:
        raise HTTPException(status_code=413, detail="Video exceeds 200 MB limit.")

    engine_norm = (engine or "sam3").lower().strip()
    if engine_norm not in {"sam3", "rfdetr"}:
        raise HTTPException(status_code=400, detail=f"Invalid engine '{engine}'. Must be 'sam3' or 'rfdetr'.")

    normalised_target: Optional[str] = target.strip() if (target and target.strip()) else None

    if engine_norm == "sam3" and not normalised_target:
        raise HTTPException(
            status_code=400,
            detail="Target element is required for the SAM3 engine. Switch to 'rfdetr' for prompt-free tracking.",
        )

    file_id = uuid.uuid4().hex[:12]
    saved_filename = f"{file_id}{ext}"
    saved_path = os.path.abspath(os.path.join(VISION_UPLOADS_DIR, saved_filename))

    with open(saved_path, "wb") as f:
        f.write(video_bytes)

    logger.info(
        f"Video tracking requested: engine={engine_norm}, "
        f"target={'<none>' if normalised_target is None else repr(normalised_target[:80])}, "
        f"video={saved_path}"
    )

    output_path = None
    try:
        result = await run_video_tracking(
            video_path=saved_path,
            target=normalised_target,
            engine=engine_norm,
        )
        output_path = result["video_path"]
        text_summary = result["text"]

        # Read the output video and encode as base64
        with open(output_path, "rb") as vf:
            video_b64 = base64.b64encode(vf.read()).decode()

        return {
            "text": text_summary,
            "video_base64": f"data:video/mp4;base64,{video_b64}",
        }

    except Exception as e:
        logger.error(f"Video tracking failed: {e}")
        raise HTTPException(status_code=500, detail=f"Video tracking failed: {e}")
    finally:
        try:
            os.remove(saved_path)
        except OSError:
            pass
        if output_path:
            try:
                os.remove(output_path)
            except OSError:
                pass


class NoteAssetRequest(BaseModel):
    """Request body for persisting a base64 data URL as a servable file."""

    data_url: str


@router.post("/vision/note-asset")
async def save_note_asset(payload: NoteAssetRequest):
    """
    Persist a base64 ``data:`` URL to disk so it can be served by a stable URL
    (suitable for embedding in note markdown). Used by the "Add to Notebook"
    flow on the image / video analysis pages.

    Returns ``{ "url": "/api/vision/note-asset/<filename>" }``.
    """
    match = DATA_URL_RE.match(payload.data_url or "")
    if not match:
        raise HTTPException(status_code=400, detail="Expected a base64 data URL.")

    mime = match.group(1).strip().lower()
    b64_data = match.group(2)

    ext = NOTE_ASSET_MIME_TO_EXT.get(mime)
    if not ext:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported asset MIME type '{mime}'.",
        )

    try:
        raw = base64.b64decode(b64_data, validate=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {e}")

    if len(raw) > MAX_NOTE_ASSET_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Asset exceeds {MAX_NOTE_ASSET_SIZE // (1024 * 1024)} MB limit.",
        )

    filename = f"{uuid.uuid4().hex}{ext}"
    target_path = os.path.abspath(os.path.join(VISION_NOTE_ASSETS_DIR, filename))

    with open(target_path, "wb") as f:
        f.write(raw)

    logger.info(f"Saved note asset {filename} ({len(raw)} bytes, mime={mime})")

    return {"url": f"/api/vision/note-asset/{filename}", "mime": mime}


@router.get("/vision/note-asset/{filename}")
async def get_note_asset(filename: str):
    """Serve a previously-saved note asset by filename."""
    # Prevent path traversal: only allow simple ``<hex>.<ext>`` filenames.
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9]+", filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    target_path = os.path.abspath(os.path.join(VISION_NOTE_ASSETS_DIR, filename))
    base_dir = os.path.abspath(VISION_NOTE_ASSETS_DIR)
    if not target_path.startswith(base_dir + os.sep):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    if not os.path.isfile(target_path):
        raise HTTPException(status_code=404, detail="Asset not found.")

    return FileResponse(target_path)
