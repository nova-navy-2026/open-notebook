"""
Video tracking service — processes video frames through SAM3 for object tracking.

Extracts frames, sends sampled frames to SAM3 /segment endpoint,
interpolates bounding boxes for skipped frames, and reassembles an annotated video.
"""

import io
import os
import random
import subprocess
import uuid
from typing import Any, Dict, Optional

import cv2
import httpx
import numpy as np
from loguru import logger
from PIL import Image, ImageDraw

# Where annotated output videos are temporarily stored
_OUTPUT_DIR = os.path.join("data", "vision_uploads", "video_output")
os.makedirs(_OUTPUT_DIR, exist_ok=True)

FRAME_SAMPLE_RATE = int(os.environ.get("VIDEO_FRAME_SAMPLE_RATE", "5"))


def _get_sam3_url() -> str:
    url = os.environ.get("SAM3_API_URL", "http://localhost:4800")
    return url.rstrip("/") + "/segment"


async def _segment_frame(
    client: httpx.AsyncClient, frame_bgr: np.ndarray, query: str
) -> tuple[int, list]:
    """Send a single frame to SAM3 /segment and return (n_masks, boxes)."""
    _, png_bytes = cv2.imencode(".png", frame_bgr)
    files = {"file": ("frame.png", png_bytes.tobytes(), "image/png")}
    data = {"query": query}
    resp = await client.post(_get_sam3_url(), files=files, data=data)
    if resp.status_code == 200:
        j = resp.json()
        return j.get("n_masks", 0), j.get("boxes", [])
    logger.warning(f"SAM3 returned {resp.status_code}: {resp.text[:200]}")
    return 0, []


def _interpolate_boxes(boxes_a: list, boxes_b: list, t: float) -> list:
    if not boxes_a:
        return boxes_b
    if not boxes_b:
        return boxes_a
    result = []
    for i in range(min(len(boxes_a), len(boxes_b))):
        a, b = boxes_a[i], boxes_b[i]
        if len(a) == 4 and len(b) == 4:
            result.append([
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t,
                a[3] + (b[3] - a[3]) * t,
            ])
    return result


def _draw_boxes(frame_bgr: np.ndarray, boxes: list, query: str, color: tuple) -> np.ndarray:
    if not boxes:
        return frame_bgr
    pil_img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    for box in boxes:
        if len(box) == 4:
            draw.rectangle([box[0], box[1], box[2], box[3]], outline=color, width=3)
            draw.text((box[0] + 3, box[1] + 3), query, fill=color)
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


async def run_video_tracking(
    video_path: str,
    target: str,
) -> Dict[str, Any]:
    """
    Track an object across video frames using SAM3.

    Returns:
        {"text": "markdown summary", "video_path": "/path/to/annotated.mp4"}
    """
    logger.info(f"Video tracking: target='{target}', video={video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()

    if not frames:
        raise ValueError("Video contains no readable frames.")

    logger.info(f"Video: {width}x{height}, {fps:.1f} fps, {len(frames)} frames")

    # Sample frames for SAM3
    sample_rate = FRAME_SAMPLE_RATE
    sampled_indices = list(range(0, len(frames), sample_rate))
    if sampled_indices[-1] != len(frames) - 1:
        sampled_indices.append(len(frames) - 1)

    sampled_results: Dict[int, list] = {}
    detections_total = 0
    color = (random.randint(50, 255), random.randint(50, 255), random.randint(50, 255))

    async with httpx.AsyncClient(timeout=120.0) as client:
        for idx in sampled_indices:
            n_masks, boxes = await _segment_frame(client, frames[idx], target)
            sampled_results[idx] = boxes
            detections_total += n_masks
            if idx % 20 == 0:
                logger.info(f"Frame {idx}/{len(frames)-1}: {n_masks} detections")

    # Interpolate boxes for non-sampled frames
    sorted_sampled = sorted(sampled_results.keys())
    frame_boxes: Dict[int, list] = {}
    for i in range(len(sorted_sampled)):
        frame_boxes[sorted_sampled[i]] = sampled_results[sorted_sampled[i]]
        if i < len(sorted_sampled) - 1:
            start_idx = sorted_sampled[i]
            end_idx = sorted_sampled[i + 1]
            for mid_idx in range(start_idx + 1, end_idx):
                t = (mid_idx - start_idx) / (end_idx - start_idx)
                frame_boxes[mid_idx] = _interpolate_boxes(
                    sampled_results[start_idx], sampled_results[end_idx], t
                )

    # Draw boxes on all frames and write output video
    output_id = uuid.uuid4().hex[:12]
    raw_path = os.path.join(_OUTPUT_DIR, f"tracked_{output_id}_raw.mp4")
    output_path = os.path.join(_OUTPUT_DIR, f"tracked_{output_id}.mp4")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(raw_path, fourcc, fps, (width, height))
    for i, frame in enumerate(frames):
        boxes = frame_boxes.get(i, [])
        writer.write(_draw_boxes(frame, boxes, target, color))
    writer.release()

    # Re-encode to H.264 so browsers can play the video inline
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", raw_path,
                "-c:v", "libx264", "-preset", "fast",
                "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
        os.remove(raw_path)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning(f"ffmpeg re-encode failed, using raw mp4v: {e}")
        os.rename(raw_path, output_path)

    frames_with_detections = sum(1 for b in frame_boxes.values() if b)
    duration_s = len(frames) / fps

    summary = (
        f"## Video Tracking: \"{target}\"\n\n"
        f"| Metric | Value |\n"
        f"|---|---|\n"
        f"| Resolution | {width}×{height} |\n"
        f"| Duration | {duration_s:.1f}s ({len(frames)} frames @ {fps:.0f} fps) |\n"
        f"| Frames analyzed (SAM3) | {len(sampled_indices)} (every {sample_rate}th) |\n"
        f"| Total detections | {detections_total} |\n"
        f"| Frames with tracking | {frames_with_detections}/{len(frames)} |\n"
    )

    logger.success(f"Video tracking complete: {output_path}")
    return {
        "text": summary,
        "video_path": output_path,
    }
