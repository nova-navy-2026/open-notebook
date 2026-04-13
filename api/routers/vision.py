"""
Vision API router - endpoints for image analysis via MCP researcher.

Uses NOVA-Researcher GPTResearcher with the vision MCP config
(mcp_vision.py → SAM3) to analyze uploaded images.
"""

import base64
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from loguru import logger

from open_notebook.research.vision_service import run_vision_analysis
from open_notebook.research.video_service import run_video_tracking

router = APIRouter()

# Directory for uploaded vision files
VISION_UPLOADS_DIR = os.path.join("data", "vision_uploads")
os.makedirs(VISION_UPLOADS_DIR, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi"}
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_VIDEO_SIZE = 200 * 1024 * 1024  # 200 MB


@router.post("/vision/image-analysis")
async def analyze_image(
    image: UploadFile = File(...),
    query: str = Form(...),
):
    """
    Analyze an uploaded image using the MCP vision researcher.

    Accepts a multipart form with:
    - image: the image file (PNG, JPG, JPEG, WEBP)
    - query: the user's question / analysis request

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

    if not query.strip():
        raise HTTPException(status_code=400, detail="Query is required.")

    # Save to a unique file so the MCP tool can read it by path
    file_id = uuid.uuid4().hex[:12]
    saved_filename = f"{file_id}{ext}"
    saved_path = os.path.abspath(os.path.join(VISION_UPLOADS_DIR, saved_filename))

    with open(saved_path, "wb") as f:
        f.write(image_bytes)

    logger.info(f"Vision analysis requested: query='{query[:80]}', image={saved_path}")

    try:
        result = await run_vision_analysis(
            image_path=saved_path,
            query=query.strip(),
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
    target: str = Form(...),
):
    """
    Track an object across video frames using SAM3.

    Accepts a multipart form with:
    - video: the video file (MP4, WEBM, MOV, AVI)
    - target: the object to track (e.g. "red car", "boat")

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

    if not target.strip():
        raise HTTPException(status_code=400, detail="Target element is required.")

    file_id = uuid.uuid4().hex[:12]
    saved_filename = f"{file_id}{ext}"
    saved_path = os.path.abspath(os.path.join(VISION_UPLOADS_DIR, saved_filename))

    with open(saved_path, "wb") as f:
        f.write(video_bytes)

    logger.info(f"Video tracking requested: target='{target[:80]}', video={saved_path}")

    output_path = None
    try:
        result = await run_video_tracking(
            video_path=saved_path,
            target=target.strip(),
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
