"""
Vision API router - endpoints for image analysis via MCP researcher.

Uses NOVA-Researcher GPTResearcher with the vision MCP config
(mcp_vision.py → SAM3) to analyze uploaded images.
"""

import base64
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from open_notebook.research.vision_service import run_vision_analysis
from open_notebook.research.video_service import run_video_tracking

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
