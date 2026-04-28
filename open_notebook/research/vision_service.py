"""
Vision service - calls SAM3 / RF-DETR servers directly for image analysis.

Flow: open-notebook backend → SAM3 /segment  (open-vocabulary, prompted)
                            → RF-DETR /detect (closed-vocabulary, COCO)

NOVA-Researcher is no longer in the loop for image analysis: we no longer
need an LLM tool-calling step (which was failing on Gemma's tokenizer), and
the annotated image / counts come straight from the vision servers.
"""

import base64
import io
import os
import random
from typing import Any, Dict, List, Optional, Tuple

import httpx
from loguru import logger
from PIL import Image, ImageDraw

# Reuse the COCO-91 lookup table maintained for video tracking so
# RF-DETR class filtering stays consistent between image & video paths.
from open_notebook.research.video_service import _COCO_CLASSES


def _get_sam3_url() -> str:
    return os.environ.get("SAM3_API_URL", "http://localhost:4800").rstrip("/") + "/segment"


def _get_rfdetr_url() -> str:
    return os.environ.get("RFDETR_API_URL", "http://localhost:4802").rstrip("/") + "/detect"


# Default confidence gate for RF-DETR. Lower than SAM3's internal threshold
# because RF-DETR's COCO head can be noisy.
_RFDETR_DEFAULT_CONF = float(os.environ.get("RFDETR_CONF_THRESHOLD", "0.35"))


def _class_name(cid: int) -> str:
    try:
        return _COCO_CLASSES[int(cid)]
    except (IndexError, ValueError, TypeError):
        return "object"


def _draw_boxes(
    image_bytes: bytes,
    boxes: List[List[float]],
    labels: List[str],
) -> str:
    """Draw bounding boxes + labels onto the image and return a data-URI PNG."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    palette: Dict[str, Tuple[int, int, int]] = {}
    for box, label in zip(boxes, labels):
        if len(box) != 4:
            continue
        if label not in palette:
            palette[label] = (
                random.randint(60, 255),
                random.randint(60, 255),
                random.randint(60, 255),
            )
        color = palette[label]
        x1, y1, x2, y2 = (float(v) for v in box)
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        draw.text((x1 + 3, y1 + 3), label, fill=color)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


async def _run_sam3(image_bytes: bytes, filename: str, query: str) -> Dict[str, Any]:
    """Call SAM3 /segment directly and produce an annotated image + summary."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        files = {"file": (filename, image_bytes, "image/png")}
        data = {"query": query}
        resp = await client.post(_get_sam3_url(), files=files, data=data)
    resp.raise_for_status()
    payload = resp.json()

    boxes = payload.get("boxes") or []
    n_masks = int(payload.get("n_masks") or 0)

    image_base64: Optional[str] = None
    if boxes:
        image_base64 = _draw_boxes(image_bytes, boxes, [query] * len(boxes))

    if n_masks > 0:
        text = (
            f"[SAM3 Analysis for '{query}']\n"
            f"Found {n_masks} instance(s) of '{query}'."
        )
    else:
        text = f"[SAM3 Analysis for '{query}']\nFound 0 instances of '{query}'."

    return {"text": text, "image_base64": image_base64}


async def _run_rfdetr(
    image_bytes: bytes,
    filename: str,
    query: Optional[str],
    confidence_threshold: float = _RFDETR_DEFAULT_CONF,
) -> Dict[str, Any]:
    """Call RF-DETR /detect directly, filter by query class, annotate image."""
    # Ask the server slightly below our gate so we don't lose detections to
    # the library's internal default threshold.
    server_thr = max(0.0, confidence_threshold - 0.05)
    async with httpx.AsyncClient(timeout=300.0) as client:
        files = {"file": (filename, image_bytes, "image/png")}
        data = {"threshold": str(server_thr)}
        resp = await client.post(_get_rfdetr_url(), files=files, data=data)
    resp.raise_for_status()
    payload = resp.json()

    det = payload.get("detections") or payload
    raw_boxes = det.get("xyxy") or []
    raw_confs = det.get("confidence") or []
    raw_cids = det.get("class_id") or []

    # Confidence gate
    triples = [
        (b, float(c), int(cid))
        for b, c, cid in zip(raw_boxes, raw_confs, raw_cids)
        if float(c) >= confidence_threshold
    ]

    # Optional class-name filter from the user query
    q = (query or "").strip().lower()
    if q:
        triples = [
            (b, c, cid) for (b, c, cid) in triples
            if q in _class_name(cid).lower() or _class_name(cid).lower() in q
        ]

    boxes = [t[0] for t in triples]
    labels = [f"{_class_name(t[2])} {t[1]:.2f}" for t in triples]

    image_base64: Optional[str] = None
    if boxes:
        image_base64 = _draw_boxes(image_bytes, boxes, labels)

    if not boxes:
        q_note = f" matching '{query}'" if query else ""
        text = f"[RF-DETR] No detections{q_note} above confidence {confidence_threshold:.2f}."
    else:
        counts: Dict[str, int] = {}
        for _, _, cid in triples:
            name = _class_name(cid)
            counts[name] = counts.get(name, 0) + 1
        lines = [f"- {n}: {c}" for n, c in sorted(counts.items(), key=lambda x: -x[1])]
        q_note = f" (filtered by '{query}')" if query else ""
        text = (
            f"[RF-DETR Analysis{q_note}]\n"
            f"Total detections: {len(boxes)}\n"
            + "\n".join(lines)
        )

    return {"text": text, "image_base64": image_base64}


async def run_vision_analysis(
    image_path: str,
    query: Optional[str],
    engine: str = "sam3",
    provider: Optional[str] = None,  # kept for API compatibility, no longer used
) -> Dict[str, Any]:
    """
    Run image analysis by calling SAM3 or RF-DETR directly.

    Args:
        image_path: local path to the uploaded image.
        query: text prompt. Required for ``sam3``; optional for ``rfdetr``
               (``None``/empty triggers prompt-free detection).
        engine: "sam3" (default) or "rfdetr".
        provider: ignored. Accepted for backwards-compatibility with the
                  previous NOVA-Researcher-backed signature.

    Returns:
        {"text": "...", "image_base64": "data:image/png;base64,..." | None}
    """
    if provider:
        logger.debug(
            f"Vision: 'provider={provider}' is ignored — vision now calls "
            f"SAM3/RF-DETR directly without an LLM step."
        )

    engine_norm = (engine or "sam3").lower().strip()
    if engine_norm not in {"sam3", "rfdetr"}:
        raise ValueError(f"Invalid engine '{engine}'. Must be 'sam3' or 'rfdetr'.")

    norm_query = query.strip() if (query and query.strip()) else None
    if engine_norm == "sam3" and not norm_query:
        raise ValueError("The SAM3 engine requires a non-empty query.")

    with open(image_path, "rb") as f:
        image_bytes = f.read()
    filename = os.path.basename(image_path) or "image.png"

    q_log = norm_query[:100] if norm_query else "<none>"
    logger.info(f"Vision ({engine_norm}) direct call: '{q_log}' on {image_path}")

    try:
        if engine_norm == "sam3":
            result = await _run_sam3(image_bytes, filename, norm_query or "")
        else:
            result = await _run_rfdetr(image_bytes, filename, norm_query)

        logger.success(
            f"Vision ({engine_norm}) done. Report length: {len(result.get('text', ''))}, "
            f"annotated_image={'yes' if result.get('image_base64') else 'no'}"
        )
        return result
    except httpx.HTTPError as e:
        logger.error(f"Vision ({engine_norm}) HTTP error: {e}")
        raise
    except Exception as e:
        logger.error(f"Vision ({engine_norm}) error: {e}")
        raise
