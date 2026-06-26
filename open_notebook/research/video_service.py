"""
Video tracking service — processes video frames through SAM3 for object tracking.

Extracts frames, sends sampled frames to SAM3 /segment endpoint,
interpolates bounding boxes for skipped frames, and reassembles an annotated video.
"""

import asyncio
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
FRAME_CONCURRENCY = int(os.environ.get("VIDEO_FRAME_CONCURRENCY", "4"))


def _get_sam3_url() -> str:
    url = os.environ.get("SAM3_API_URL", "http://localhost:4800")
    return url.rstrip("/") + "/segment"


def _get_rfdetr_url() -> str:
    url = os.environ.get("RFDETR_API_URL", "http://localhost:4802")
    return url.rstrip("/") + "/detect"


def _get_llm_url() -> str:
    return os.environ.get("GEMMA_BASE_URL", "http://10.10.255.206:46888/v1").rstrip("/") + "/chat/completions"


async def _extract_objects_from_query(query: str) -> str:
    """
    Use Gemma4 to extract clean object names from a conversational query.
    Converts "Track the planes in the video" -> "plane".
    Falls back to the raw query if the LLM service is unavailable.
    """
    system_prompt = (
        "You are a computer vision extraction tool. "
        "Extract the core object(s) the user wants to detect from their prompt. "
        "Return ONLY a clean, comma-separated list of singular object names. "
        "Do not include conversational padding, punctuation, or formatting. "
        "Example input: 'Track the planes in the video' -> Example output: 'plane'"
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "model": os.environ.get("GEMMA_MODEL", "google/gemma-4-31B-it"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                "temperature": 0.0,
                "max_tokens": 20,
            }
            headers = {}
            api_key = os.environ.get("GEMMA_API_KEY", "nova-vl")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = await client.post(_get_llm_url(), json=payload, headers=headers)
            resp.raise_for_status()
            cleaned = resp.json()["choices"][0]["message"]["content"].strip()
            return cleaned
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning(f"LLM rewriting service unreachable — passing raw query directly. ({type(e).__name__})")
        return query
    except Exception as e:
        logger.error(f"LLM query extraction failed. Falling back to raw query. Error: {e}")
        return query


# COCO-91 lookup for RF-DETR class filtering.
# RF-DETR returns COCO *category_id* values (1=person, 2=bicycle, ...),
# NOT the contiguous 0-79 indexing used by some YOLO builds. Using the
# wrong table causes a one-off shift where every detected person is
# labelled as a bicycle, etc.
_COCO_CLASSES = [
    "N/A",            # 0
    "person",         # 1
    "bicycle",        # 2
    "car",            # 3
    "motorcycle",     # 4
    "airplane",       # 5
    "bus",            # 6
    "train",          # 7
    "truck",          # 8
    "boat",           # 9
    "traffic light",  # 10
    "fire hydrant",   # 11
    "N/A",            # 12
    "stop sign",      # 13
    "parking meter",  # 14
    "bench",          # 15
    "bird",           # 16
    "cat",            # 17
    "dog",            # 18
    "horse",          # 19
    "sheep",          # 20
    "cow",            # 21
    "elephant",       # 22
    "bear",           # 23
    "zebra",          # 24
    "giraffe",        # 25
    "N/A",            # 26
    "backpack",       # 27
    "umbrella",       # 28
    "N/A",            # 29
    "N/A",            # 30
    "handbag",        # 31
    "tie",            # 32
    "suitcase",       # 33
    "frisbee",        # 34
    "skis",           # 35
    "snowboard",      # 36
    "sports ball",    # 37
    "kite",           # 38
    "baseball bat",   # 39
    "baseball glove", # 40
    "skateboard",     # 41
    "surfboard",      # 42
    "tennis racket",  # 43
    "bottle",         # 44
    "N/A",            # 45
    "wine glass",     # 46
    "cup",            # 47
    "fork",           # 48
    "knife",          # 49
    "spoon",          # 50
    "bowl",           # 51
    "banana",         # 52
    "apple",          # 53
    "sandwich",       # 54
    "orange",         # 55
    "broccoli",       # 56
    "carrot",         # 57
    "hot dog",        # 58
    "pizza",          # 59
    "donut",          # 60
    "cake",           # 61
    "chair",          # 62
    "couch",          # 63
    "potted plant",   # 64
    "bed",            # 65
    "N/A",            # 66
    "dining table",   # 67
    "N/A",            # 68
    "N/A",            # 69
    "toilet",         # 70
    "N/A",            # 71
    "tv",             # 72
    "laptop",         # 73
    "mouse",          # 74
    "remote",         # 75
    "keyboard",       # 76
    "cell phone",     # 77
    "microwave",      # 78
    "oven",           # 79
    "toaster",        # 80
    "sink",           # 81
    "refrigerator",   # 82
    "N/A",            # 83
    "book",           # 84
    "clock",          # 85
    "vase",           # 86
    "scissors",       # 87
    "teddy bear",     # 88
    "hair drier",     # 89
    "toothbrush",     # 90
]


async def _detect_frame_rfdetr(
    client: httpx.AsyncClient, frame_bgr: np.ndarray, query: str,
    confidence_threshold: float = 0.35,
) -> tuple[int, list]:
    """Send a frame to RF-DETR /detect, filter by class name if query given."""
    _, png_bytes = cv2.imencode(".png", frame_bgr)
    files = {"file": ("frame.png", png_bytes.tobytes(), "image/png")}
    try:
        resp = await client.post(_get_rfdetr_url(), files=files)
        if resp.status_code != 200:
            logger.warning(f"RF-DETR returned {resp.status_code}: {resp.text[:200]}")
            return 0, []
        data = resp.json()
    except Exception as e:
        logger.warning(f"RF-DETR call failed: {e}")
        return 0, []

    det = data.get("detections") or data
    boxes = det.get("xyxy") or []
    confs = det.get("confidence") or []
    class_ids = det.get("class_id") or []

    # confidence gate
    triples = [
        (b, c, cid) for b, c, cid in zip(boxes, confs, class_ids)
        if float(c) >= confidence_threshold
    ]

    # class-name filter
    q = (query or "").strip().lower()
    if q:
        filtered = []
        for b, c, cid in triples:
            try:
                name = _COCO_CLASSES[int(cid)].lower()
            except (IndexError, ValueError, TypeError):
                continue
            if q in name or name in q:
                filtered.append((b, c, cid))
        triples = filtered

    out_boxes = [t[0] for t in triples]
    return len(out_boxes), out_boxes


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
    target: Optional[str],
    engine: str = "sam3",
) -> Dict[str, Any]:
    """
    Track an object across video frames.

    Args:
        target: text prompt / class filter. Required for ``sam3``; optional
                for ``rfdetr`` (``None``/empty → track every detection).
        engine: "sam3" (open-vocabulary segmentation) or
                "rfdetr" (fast closed-vocabulary COCO detection)

    Returns:
        {"text": "markdown summary", "video_path": "/path/to/annotated.mp4"}
    """
    engine = (engine or "sam3").lower().strip()
    if engine not in {"sam3", "rfdetr"}:
        raise ValueError(f"Invalid engine '{engine}'. Must be 'sam3' or 'rfdetr'.")

    # Normalise target, then rewrite with Gemma4 to get clean object names.
    norm_target: Optional[str] = target.strip() if (target and target.strip()) else None
    if norm_target:
        clean_target = await _extract_objects_from_query(norm_target)
        logger.info(f"LLM translated target: '{norm_target}' -> '{clean_target}'")
        norm_target = clean_target
    if engine == "sam3" and not norm_target:
        raise ValueError("The SAM3 engine requires a non-empty target.")

    logger.info(
        f"Video tracking ({engine}): target={'<none>' if norm_target is None else repr(norm_target)}, "
        f"video={video_path}"
    )

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

    sem = asyncio.Semaphore(FRAME_CONCURRENCY)

    async def _process_frame(client, idx):
        async with sem:
            if engine == "rfdetr":
                return idx, await _detect_frame_rfdetr(client, frames[idx], norm_target or "")
            return idx, await _segment_frame(client, frames[idx], norm_target or "")

    async with httpx.AsyncClient(timeout=120.0) as client:
        tasks = [_process_frame(client, idx) for idx in sampled_indices]
        results = await asyncio.gather(*tasks)
        for idx, (n_masks, boxes) in results:
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

    # Draw boxes on all frames and write output video. Drawing every frame +
    # the VideoWriter + the ffmpeg re-encode are all CPU-bound and synchronous;
    # running them inline would block the asyncio event loop for many seconds
    # (large clips), which starves keepalives and gets the request killed with
    # "socket hang up"/ECONNRESET by the proxy even though the work succeeds.
    # Run the whole render off-loop in a worker thread.
    output_id = uuid.uuid4().hex[:12]
    raw_path = os.path.join(_OUTPUT_DIR, f"tracked_{output_id}_raw.mp4")
    output_path = os.path.join(_OUTPUT_DIR, f"tracked_{output_id}.mp4")
    label_text = norm_target or "object"

    def _render_video() -> None:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(raw_path, fourcc, fps, (width, height))
        for i, frame in enumerate(frames):
            boxes = frame_boxes.get(i, [])
            writer.write(_draw_boxes(frame, boxes, label_text, color))
        writer.release()

        # Re-encode to H.264 so browsers can play the video inline.
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
        except FileNotFoundError as e:
            # ffmpeg not installed on this node — the mp4v fallback often will
            # NOT play in browsers (they want H.264). Make this loud, not debug.
            logger.error(
                "ffmpeg is not installed on this node ({}); falling back to raw "
                "mp4v, which most browsers cannot play inline. Install ffmpeg on "
                "the compute node to fix video playback AND audio transcription.",
                e,
            )
            os.rename(raw_path, output_path)
        except subprocess.CalledProcessError as e:
            logger.warning(
                "ffmpeg re-encode failed ({}); using raw mp4v.",
                (e.stderr or b"")[:300] if isinstance(e.stderr, bytes) else e.stderr,
            )
            os.rename(raw_path, output_path)

    await asyncio.to_thread(_render_video)

    frames_with_detections = sum(1 for b in frame_boxes.values() if b)
    duration_s = len(frames) / fps

    summary_title = norm_target if norm_target else "all detections (prompt-free)"
    summary = (
        f"## Video Tracking: \"{summary_title}\"\n\n"
        f"| Metric | Value |\n"
        f"|---|---|\n"
        f"| Resolution | {width}×{height} |\n"
        f"| Duration | {duration_s:.1f}s ({len(frames)} frames @ {fps:.0f} fps) |\n"
        f"| Frames analyzed ({engine.upper()}) | {len(sampled_indices)} (every {sample_rate}th) |\n"
        f"| Total detections | {detections_total} |\n"
        f"| Frames with tracking | {frames_with_detections}/{len(frames)} |\n"
    )

    logger.success(f"Video tracking complete: {output_path}")
    return {
        "text": summary,
        "video_path": output_path,
    }
