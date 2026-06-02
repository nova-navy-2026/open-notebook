"""
Vision API router - endpoints for image analysis via MCP researcher.

Uses NOVA-Researcher GPTResearcher with the vision MCP config
(mcp_vision.py → SAM3) to analyze uploaded images.
"""

import base64
import asyncio
import json
import math
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from time import perf_counter
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
            # Seek-based sampling - fast for indexed containers.
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
            # Sequential scan for streams / containers without frame-count metadata.
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


def _gemma_multimodal_timeout() -> float:
    try:
        return float(os.environ.get("GEMMA_MULTIMODAL_TIMEOUT", "600"))
    except ValueError:
        return 600.0


def _gemma_multimodal_max_tokens() -> int:
    try:
        return int(os.environ.get("GEMMA_MULTIMODAL_MAX_TOKENS", "1024"))
    except ValueError:
        return 1024


def _gemma_ocr_max_tokens() -> int:
    try:
        return int(os.environ.get("GEMMA_OCR_MAX_TOKENS", "2048"))
    except ValueError:
        return 2048


def _gemma_ocr_postprocess_enabled() -> bool:
    return os.environ.get("GEMMA_OCR_POSTPROCESS_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
    }


def _gemma_ocr_postprocess_timeout() -> float:
    try:
        return float(os.environ.get("GEMMA_OCR_POSTPROCESS_TIMEOUT", "240"))
    except ValueError:
        return 240.0


def _docling_ocr_timeout() -> float:
    try:
        return float(os.environ.get("DOCLING_OCR_TIMEOUT", "90"))
    except ValueError:
        return 90.0


def _docling_ocr_enabled() -> bool:
    return os.environ.get("DOCLING_OCR_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
    }


def _first_frame_as_jpeg(video_path: str) -> Optional[bytes]:
    """Extract the first frame of a video and return it as JPEG bytes."""
    cap = cv2.VideoCapture(video_path)
    try:
        ret, frame = cap.read()
        if not ret or frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame)
        return bytes(buf) if ok else None
    finally:
        cap.release()


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
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
    purpose: str = "multimodal",
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
        "max_tokens": max_tokens or _gemma_multimodal_max_tokens(),
    }
    request_timeout = timeout or _gemma_multimodal_timeout()
    started_at = perf_counter()
    logger.info(
        "ChatAgent LLM start | provider=gemma purpose={} model={} images={} "
        "prompt_chars={} max_tokens={} timeout_s={}",
        purpose,
        payload["model"],
        len(images or []),
        len(prompt),
        payload["max_tokens"],
        request_timeout,
    )
    try:
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            resp = await client.post(
                f"{_gemma_base_url()}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {_gemma_api_key()}"},
            )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        logger.success(
            "ChatAgent LLM success | provider=gemma purpose={} duration_ms={} "
            "response_chars={}",
            purpose,
            round((perf_counter() - started_at) * 1000),
            len(text or ""),
        )
        return text
    except Exception as e:
        logger.error(
            "ChatAgent LLM failure | provider=gemma purpose={} duration_ms={} "
            "error_type={} error={}",
            purpose,
            round((perf_counter() - started_at) * 1000),
            type(e).__name__,
            str(e) or repr(e),
        )
        raise

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

_DETECTION_WORDS = {
    "detect", "detecta", "detetar", "detectar", "detection",
    "identify", "identifica", "identificar", "identification",
    "find", "encontra", "encontrar", "locate", "localiza", "localizar",
    "count", "conta", "contar", "segment", "segmentation",
    "segmenta", "segmentar", "segmentação", "segmentacao",
    "track", "segue", "seguir", "rastreia", "rastrear",
}

_OCR_WORDS = {
    "ocr", "texto", "text", "ler", "read", "extrai", "extrair", "extract",
    "extração", "extracao", "tabela", "table", "csv", "coluna", "colunas",
    "linha", "linhas",
    "transcrever", "transcreve", "transcribe", "reconhecer", "recognize",
    "reconhecimento", "documento", "document", "placa", "license", "plate",
}

_COMMON_OBJECT_ALIASES = {
    "plane": "airplane",
    "planes": "airplane",
    "aircraft": "airplane",
    "airplane": "airplane",
    "airplanes": "airplane",
    "aeroplane": "airplane",
    "aeroplanes": "airplane",
    "aviao": "airplane",
    "avioes": "airplane",
    "avião": "airplane",
    "aviões": "airplane",
    "boat": "boat",
    "boats": "boat",
    "ship": "boat",
    "ships": "boat",
    "barco": "boat",
    "barcos": "boat",
    "navio": "boat",
    "navios": "boat",
    "car": "car",
    "cars": "car",
    "carro": "car",
    "carros": "car",
    "person": "person",
    "people": "person",
    "pessoa": "person",
    "pessoas": "person",
    "truck": "truck",
    "trucks": "truck",
    "camiao": "truck",
    "camioes": "truck",
    "camião": "truck",
    "camiões": "truck",
}


def _normalise_query_text(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip())


def _extract_common_target(query: str) -> Optional[str]:
    text = _normalise_query_text(query).lower()
    words = re.findall(r"[\wÀ-ÿ]+", text)
    for word in words:
        if word in _COMMON_OBJECT_ALIASES:
            return _COMMON_OBJECT_ALIASES[word]
    return None


def _extract_sam3_target(query: str) -> str:
    target = _extract_common_target(query)
    if target:
        return target

    text = _normalise_query_text(query).lower()
    if "pedido atual:" in text:
        text = text.split("pedido atual:", 1)[1]
    text = re.sub(r"\bsam[-\s]?3\b|segment anything|rf[-\s]?detr|rfdetr", " ", text)
    text = re.sub(
        r"\b(podes|pode|consegues|consegue|can you|please|por favor|analisa|analisar|analyze|imagem|image|foto|photo|utilizando|using|usar|use|fazer|do|a|o|os|as|the|this|esta|este|com|with|e|and|to)\b",
        " ",
        text,
    )
    text = re.sub(
        r"\b(segmentacao|segmentação|segmentar|segmenta|segmentation|segment)\b",
        " ",
        text,
    )
    text = re.sub(r"[^\wÀ-ÿ\s-]", " ", text)
    cleaned = _normalise_query_text(text)
    return cleaned if len(cleaned) > 2 else "object"


def _requested_visual_engine(query: str) -> Optional[str]:
    text = _normalise_query_text(query).lower()
    matches: List[Tuple[int, str]] = []
    for match in re.finditer(r"\bsam[-\s]?3\b|segment anything", text):
        matches.append((match.start(), "sam3"))
    for match in re.finditer(r"\brf[-\s]?detr\b|rfdetr", text):
        matches.append((match.start(), "rfdetr"))
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def _looks_like_detection_task(query: str) -> bool:
    text = _normalise_query_text(query).lower()
    if not text:
        return False
    words = set(re.findall(r"[\wÀ-ÿ]+", text))
    return (
        _requested_visual_engine(text) is not None
        or bool(words & _DETECTION_WORDS)
        or _extract_common_target(text) is not None
    )


def _looks_like_ocr_task(query: str) -> bool:
    text = _normalise_query_text(query).lower()
    if not text:
        return False
    words = set(re.findall(r"[\wÀ-ÿ]+", text))
    if words & _OCR_WORDS:
        return True
    return bool(
        re.search(
            r"\b(read|extract|transcribe)\s+(the\s+)?(text|words|document)\b",
            text,
        )
    )


def _choose_visual_engine(query: str) -> Tuple[str, Optional[str]]:
    """
    Pick the concrete vision engine for a natural-language request.

    RF-DETR is preferred for common COCO classes because it is fast and does
    not need prompt interpretation. SAM3 remains the fallback for open-vocabulary
    prompts such as "red inflatable boat" or "damaged antenna".
    """
    requested_engine = _requested_visual_engine(query)
    target = _extract_common_target(query)

    if requested_engine:
        if requested_engine == "sam3":
            return "sam3", target or _extract_sam3_target(query)
        return "rfdetr", target

    if target:
        return "rfdetr", target

    cleaned = _normalise_query_text(query)
    if cleaned:
        return "sam3", cleaned

    return "rfdetr", None


def _target_label_pt(target: Optional[str]) -> str:
    labels = {
        "airplane": "aviões",
        "boat": "embarcações",
        "car": "carros",
        "person": "pessoas",
        "truck": "camiões",
    }
    return labels.get(target or "", target or "objetos")


def _extract_detection_count(tool_result: str) -> Optional[int]:
    for pattern in (r"Total detections:\s*(\d+)", r"Found\s+(\d+)\s+instance"):
        match = re.search(pattern, tool_result or "", re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _summarise_tool_result(
    query: str,
    tool_result: str,
    media_kind: str,
    engine: str,
    target: Optional[str] = None,
) -> str:
    count = _extract_detection_count(tool_result)
    target_label = _target_label_pt(target)

    if count is not None:
        if media_kind == "video":
            return (
                f"Detetei {count} ocorrência(s) de {target_label} no vídeo com {engine}. "
                "O vídeo anotado está abaixo.\n\n"
                f"{tool_result}"
            )
        return (
            f"Detetei {count} {target_label} na imagem com {engine}. "
            "A imagem anotada está abaixo.\n\n"
            f"{tool_result}"
        )

    return tool_result


async def _image_analysis_fallback_response(
    image_path: str,
    reason: str,
) -> dict:
    try:
        result = await run_vision_analysis(
            image_path=image_path,
            query=None,
            engine="rfdetr",
            provider="gemma",
        )
        return {
            "text": (
                f"{reason}\n\n"
                "Executei uma deteção visual geral com RF-DETR para devolver uma resposta útil.\n\n"
                f"{result.get('text') or ''}"
            ),
            "route": "image_analysis_fallback",
            "engine": "rfdetr",
            "image_base64": result.get("image_base64"),
        }
    except Exception as fallback_error:
        detail = str(fallback_error) or repr(fallback_error)
        logger.error(f"RF-DETR fallback failed after Gemma multimodal failure: {detail}")
        return {
            "text": (
                f"{reason}\n\n"
                "Também não consegui executar a deteção visual de fallback com RF-DETR. "
                f"Detalhe técnico: {type(fallback_error).__name__}: {detail}"
            ),
            "route": "vision_unavailable",
            "engine": "rfdetr",
            "image_base64": None,
        }


async def _run_gemma_ocr(
    query: str,
    images: List[Tuple[bytes, str]],
    context: Optional[str] = None,
    media_kind: str = "imagem",
) -> dict:
    prompt = (
        "Atua como um motor de OCR rigoroso.\n"
        f"Pedido do utilizador: {query}\n\n"
        f"Analisa a {media_kind} enviada e extrai todo o texto visível.\n"
        "Regras:\n"
        "- Mantém o texto original tal como aparece, incluindo maiúsculas, números e pontuação.\n"
        "- Se houver várias zonas de texto, organiza por blocos/linhas.\n"
        "- Se algum texto estiver ilegível, marca como [ilegível] em vez de inventar.\n"
        "- Depois da transcrição, acrescenta uma nota curta sobre a confiança/leiturabilidade.\n"
        "- Responde em pt-PT, exceto se o pedido do utilizador estiver claramente noutra língua.\n"
    )
    if context and context.strip():
        prompt = f"{prompt}\n\nContexto visual anterior, se for útil:\n{context.strip()}"

    try:
        text = await _call_gemma(
            prompt,
            images,
            max_tokens=_gemma_ocr_max_tokens(),
            purpose="ocr_fallback",
        )
        return {
            "text": text,
            "route": "ocr",
            "engine": "gemma_ocr",
            "image_base64": None,
        }
    except Exception as e:
        detail = str(e) or repr(e)
        logger.error(f"Gemma OCR failed: {type(e).__name__}: {detail}")
        return {
            "text": (
                "Não consegui executar OCR nesta imagem. "
                f"Detalhe técnico: {type(e).__name__}: {detail}"
            ),
            "route": "ocr_failed",
            "engine": "gemma_ocr",
            "image_base64": None,
        }


def _run_docling_ocr_subprocess(image_path: str) -> str:
    engine = os.environ.get("DOCLING_OCR_ENGINE", "auto").strip().lower() or "auto"
    timeout = _docling_ocr_timeout()
    langs = os.environ.get("DOCLING_OCR_LANGS", "").strip()

    script = r"""
import json
import os
import sys

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    OcrAutoOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TesseractCliOcrOptions,
    TesseractOcrOptions,
)
from docling.document_converter import (
    DocumentConverter,
    ImageFormatOption,
    PdfFormatOption,
)

path = sys.argv[1]
engine = sys.argv[2]
langs_arg = sys.argv[3]

pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = True
pipeline_options.do_table_structure = True

if engine == "rapidocr":
    pipeline_options.ocr_options = RapidOcrOptions()
elif engine == "easyocr":
    langs = [x.strip() for x in (langs_arg or "pt,en").split(",") if x.strip()]
    pipeline_options.ocr_options = EasyOcrOptions(
        lang=langs,
        download_enabled=os.environ.get("DOCLING_EASYOCR_DOWNLOAD", "false").lower()
        in {"1", "true", "yes"},
    )
elif engine == "tesseract":
    langs = [x.strip() for x in (langs_arg or "por,eng").split(",") if x.strip()]
    pipeline_options.ocr_options = TesseractOcrOptions(lang=langs)
elif engine in {"tesseract_cli", "tesseract-cli"}:
    langs = [x.strip() for x in (langs_arg or "por,eng").split(",") if x.strip()]
    pipeline_options.ocr_options = TesseractCliOcrOptions(lang=langs)
else:
    langs = [x.strip() for x in langs_arg.split(",") if x.strip()]
    pipeline_options.ocr_options = OcrAutoOptions(lang=langs)

converter = DocumentConverter(
    format_options={
        InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
    }
)
result = converter.convert(path)
doc = result.document

markdown = ""
plain_text = ""
if hasattr(doc, "export_to_markdown"):
    markdown = doc.export_to_markdown() or ""
if hasattr(doc, "export_to_text"):
    plain_text = doc.export_to_text() or ""

print(json.dumps({"markdown": markdown, "text": plain_text}, ensure_ascii=False))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script, image_path, engine, langs],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr[-2000:] or stdout[-2000:] or f"exit code {completed.returncode}"
        raise RuntimeError(detail)

    stdout = (completed.stdout or "").strip()
    json_line = ""
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            json_line = candidate
            break

    try:
        payload = json.loads(json_line or stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid Docling output: {stdout[:500]}") from e

    text = (payload.get("markdown") or payload.get("text") or "").strip()
    if not text:
        raise RuntimeError("Docling did not extract any text.")
    return text


async def _run_docling_ocr(image_path: str) -> str:
    return await asyncio.to_thread(_run_docling_ocr_subprocess, image_path)


async def _postprocess_ocr_with_gemma(ocr_text: str, query: str) -> Tuple[str, bool]:
    if not _gemma_ocr_postprocess_enabled() or not ocr_text.strip():
        return ocr_text, False

    prompt = (
        "Revê o seguinte texto extraído por OCR.\n\n"
        "Objetivo: corrigir apenas erros óbvios de OCR, especialmente acentos, "
        "cedilhas e tils em português europeu.\n\n"
        "Regras estritas:\n"
        "- Não inventes texto novo.\n"
        "- Não resumas.\n"
        "- Mantém nomes, números, siglas, datas, coordenadas e códigos exatamente como no OCR, "
        "exceto quando a correção for inequívoca.\n"
        "- Mantém a estrutura em linhas/blocos o mais parecida possível.\n"
        "- Se uma palavra estiver ambígua, deixa como está.\n"
        "- Devolve apenas o texto corrigido, sem comentários.\n\n"
        f"Pedido original do utilizador: {query}\n\n"
        "Texto OCR:\n"
        f"{ocr_text}"
    )
    try:
        corrected = await _call_gemma(
            prompt,
            images=None,
            max_tokens=_gemma_ocr_max_tokens(),
            timeout=_gemma_ocr_postprocess_timeout(),
            purpose="ocr_postprocess",
        )
        corrected = corrected.strip()
        return (corrected or ocr_text, bool(corrected))
    except Exception as e:
        detail = str(e) or repr(e)
        logger.warning(
            f"Gemma OCR post-processing failed; returning raw Docling OCR: "
            f"{type(e).__name__}: {detail}"
        )
        return ocr_text, False


async def _run_ocr_with_fallback(
    query: str,
    image_path: str,
    images: List[Tuple[bytes, str]],
    context: Optional[str] = None,
    media_kind: str = "imagem",
) -> dict:
    if _docling_ocr_enabled():
        try:
            text = await _run_docling_ocr(image_path)
            text, polished = await _postprocess_ocr_with_gemma(text, query)
            engine_note = (
                "OCR concluído com Docling e revisto com Gemma para correção de acentuação.\n\n"
                if polished
                else "OCR concluído com Docling.\n\n"
            )
            return {
                "text": f"{engine_note}{text}",
                "route": "ocr",
                "engine": "docling_gemma" if polished else "docling",
                "image_base64": None,
            }
        except subprocess.TimeoutExpired:
            logger.warning(
                f"Docling OCR timed out after {_docling_ocr_timeout()}s; "
                "falling back to Gemma OCR."
            )
        except Exception as e:
            detail = str(e) or repr(e)
            logger.warning(
                f"Docling OCR failed ({type(e).__name__}); falling back to Gemma OCR: {detail}"
            )

    gemma_result = await _run_gemma_ocr(
        query=query,
        images=images,
        context=context,
        media_kind=media_kind,
    )
    if gemma_result.get("route") == "ocr":
        gemma_result["text"] = (
            "OCR concluído com Gemma multimodal.\n\n"
            f"{gemma_result.get('text') or ''}"
        )
    return gemma_result


@router.post("/vision/multimodal")
async def multimodal_chat(
    query: str = Form(...),
    context: Optional[str] = Form(None),
    mode: str = Form("chat"),
    force_engine: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """
    Chat with notebook context using Gemma (vision-capable LLM).

    Accepts a multipart form with:
    - query: the user's question
    - context: pre-built context string sent from the client (optional)
    - mode: "chat" (default)
    - file: optional image/video for visual queries

    Context is built client-side via /chat/context and passed as a plain
    text string; this endpoint just forwards it to Gemma.

    Returns JSON with:
    - text: the model's response
    """
    started_at = perf_counter()
    prompt = query
    if context and context.strip():
        prompt = f"{query}\n\n---\nContext:\n\n{context.strip()}"

    # Collect images: user-uploaded image first, then assets embedded in context.
    # Video uploads are handled by the video tracking agent when the request is
    # detection/tracking-like; otherwise Gemma receives the first frame.
    images: List[Tuple[bytes, str]] = []
    saved_path: Optional[str] = None
    uploaded_ext: Optional[str] = None
    requested_force_engine = (force_engine or "").strip().lower()
    if requested_force_engine not in {"", "sam3", "rfdetr"}:
        raise HTTPException(
            status_code=400,
            detail="force_engine must be one of: sam3, rfdetr",
        )

    if file and file.filename:
        ext = Path(file.filename).suffix.lower()
        uploaded_ext = ext
        if ext not in ALLOWED_IMAGE_EXTENSIONS and ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported file type '{ext}'. Allowed images: "
                    f"{', '.join(ALLOWED_IMAGE_EXTENSIONS)}; videos: "
                    f"{', '.join(ALLOWED_VIDEO_EXTENSIONS)}"
                ),
            )
        file_bytes = await file.read()
        if ext in ALLOWED_IMAGE_EXTENSIONS and len(file_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=413, detail="Image exceeds 20 MB limit.")
        if ext in ALLOWED_VIDEO_EXTENSIONS and len(file_bytes) > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=413, detail="Video exceeds 200 MB limit.")

        file_id = uuid.uuid4().hex[:12]
        saved_path = os.path.abspath(os.path.join(VISION_UPLOADS_DIR, f"{file_id}{ext}"))
        with open(saved_path, "wb") as f:
            f.write(file_bytes)

        if ext in ALLOWED_IMAGE_EXTENSIONS and _looks_like_ocr_task(query):
            logger.info(
                "ChatAgent tool start | agent=multimodal route=ocr media=image "
                "file={} bytes={} query={!r}",
                file.filename,
                len(file_bytes),
                query[:160],
            )
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            try:
                result = await _run_ocr_with_fallback(
                    query=query,
                    image_path=saved_path,
                    images=[(file_bytes, mime_map.get(ext, "image/jpeg"))],
                    context=context,
                    media_kind="imagem",
                )
                logger.success(
                    "ChatAgent tool success | agent=multimodal route=ocr "
                    "media=image engine={} duration_ms={} chars={}",
                    result.get("engine"),
                    round((perf_counter() - started_at) * 1000),
                    len(result.get("text") or ""),
                )
                return result
            finally:
                try:
                    os.remove(saved_path)
                except OSError:
                    pass

        if ext in ALLOWED_IMAGE_EXTENSIONS and _looks_like_detection_task(query):
            engine, target = _choose_visual_engine(query)
            if requested_force_engine:
                engine = requested_force_engine
            logger.info(
                "ChatAgent tool start | agent=multimodal route=image_analysis "
                "engine={} target={!r} file={} bytes={} query={!r}",
                engine,
                target,
                file.filename,
                len(file_bytes),
                query[:160],
            )
            try:
                result = await run_vision_analysis(
                    image_path=saved_path,
                    query=target,
                    engine=engine,
                    provider="gemma",
                )
                text = _summarise_tool_result(
                    query=query,
                    tool_result=str(result.get("text") or ""),
                    media_kind="image",
                    engine=engine,
                    target=target,
                )
                response = {
                    "text": text,
                    "route": "image_analysis",
                    "engine": engine,
                    "image_base64": result.get("image_base64"),
                }
                logger.success(
                    "ChatAgent tool success | agent=multimodal route=image_analysis "
                    "engine={} duration_ms={} has_image={}",
                    engine,
                    round((perf_counter() - started_at) * 1000),
                    bool(response.get("image_base64")),
                )
                return response
            except Exception as e:
                detail = str(e) or repr(e)
                logger.error(
                    "ChatAgent tool failure | agent=multimodal route=image_analysis "
                    "engine={} duration_ms={} error_type={} error={}",
                    engine,
                    round((perf_counter() - started_at) * 1000),
                    type(e).__name__,
                    detail,
                )
                if engine == "sam3":
                    return await _image_analysis_fallback_response(
                        saved_path,
                        (
                            "Não consegui executar a segmentação com SAM3. "
                            f"Detalhe técnico: {type(e).__name__}: {detail}"
                        ),
                    )
                return {
                    "text": (
                        f"Não consegui executar a análise visual com {engine}. "
                        f"Detalhe técnico: {type(e).__name__}: {detail}"
                    ),
                    "route": "vision_unavailable",
                    "engine": engine,
                    "image_base64": None,
                }
            finally:
                try:
                    os.remove(saved_path)
                except OSError:
                    pass

        if ext in ALLOWED_VIDEO_EXTENSIONS and _looks_like_detection_task(query):
            engine, target = _choose_visual_engine(query)
            if requested_force_engine:
                engine = requested_force_engine
            logger.info(
                "ChatAgent tool start | agent=multimodal route=video_tracking "
                "engine={} target={!r} file={} bytes={} query={!r}",
                engine,
                target,
                file.filename,
                len(file_bytes),
                query[:160],
            )
            try:
                result = await run_video_tracking(
                    video_path=saved_path,
                    target=target,
                    engine=engine,
                )
                output_path = result.get("video_path")
                video_base64 = None
                if output_path:
                    with open(output_path, "rb") as vf:
                        video_base64 = f"data:video/mp4;base64,{base64.b64encode(vf.read()).decode()}"
                text = _summarise_tool_result(
                    query=query,
                    tool_result=str(result.get("text") or ""),
                    media_kind="video",
                    engine=engine,
                    target=target,
                )
                response = {
                    "text": text,
                    "route": "video_tracking",
                    "engine": engine,
                    "video_base64": video_base64,
                }
                logger.success(
                    "ChatAgent tool success | agent=multimodal route=video_tracking "
                    "engine={} duration_ms={} has_video={}",
                    engine,
                    round((perf_counter() - started_at) * 1000),
                    bool(response.get("video_base64")),
                )
                return response
            finally:
                try:
                    os.remove(saved_path)
                except OSError:
                    pass
                output_path = locals().get("output_path")
                if output_path:
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass

        if ext in ALLOWED_VIDEO_EXTENSIONS:
            frame = _first_frame_as_jpeg(saved_path)
            if frame:
                if _looks_like_ocr_task(query):
                    logger.info(
                        "ChatAgent tool start | agent=multimodal route=ocr media=video_frame "
                        "file={} bytes={} query={!r}",
                        file.filename,
                        len(file_bytes),
                        query[:160],
                    )
                    frame_id = uuid.uuid4().hex[:12]
                    frame_path = os.path.abspath(
                        os.path.join(VISION_UPLOADS_DIR, f"{frame_id}.jpg")
                    )
                    with open(frame_path, "wb") as f:
                        f.write(frame)
                    try:
                        result = await _run_ocr_with_fallback(
                            query=query,
                            image_path=frame_path,
                            images=[(frame, "image/jpeg")],
                            context=context,
                            media_kind="primeiro fotograma do vídeo",
                        )
                        logger.success(
                            "ChatAgent tool success | agent=multimodal route=ocr "
                            "media=video_frame engine={} duration_ms={} chars={}",
                            result.get("engine"),
                            round((perf_counter() - started_at) * 1000),
                            len(result.get("text") or ""),
                        )
                        return result
                    finally:
                        try:
                            os.remove(saved_path)
                        except OSError:
                            pass
                        try:
                            os.remove(frame_path)
                        except OSError:
                            pass
                images.append((frame, "image/jpeg"))
                prompt = (
                    f"{prompt}\n\nNota: o ficheiro enviado é um vídeo. "
                    "Para esta resposta geral foi analisado apenas o primeiro fotograma. "
                    "Para deteção/seguimento de objetos, pede explicitamente para detetar, "
                    "contar, identificar ou seguir o alvo."
                )
        else:
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            images.append((file_bytes, mime_map.get(ext, "image/jpeg")))

    if context and not images:
        context_images = _extract_context_images(context, VISION_NOTE_ASSETS_DIR)
        images.extend(context_images)

    logger.info(
        f"Multimodal chat: mode={mode}, images={len(images)}, "
        f"context_len={len(context) if context else 0}, force_engine={requested_force_engine or None}, "
        f"query={repr(query[:80])}"
    )

    try:
        text = await _call_gemma(prompt, images or None, purpose="multimodal_chat")
        logger.success(
            "ChatAgent tool success | agent=multimodal route=gemma_multimodal "
            "duration_ms={} images={} chars={}",
            round((perf_counter() - started_at) * 1000),
            len(images or []),
            len(text or ""),
        )
        return {"text": text, "route": "gemma_multimodal"}
    except RuntimeError as e:
        if saved_path and uploaded_ext in ALLOWED_IMAGE_EXTENSIONS:
            return await _image_analysis_fallback_response(
                saved_path,
                "Não consegui usar a análise multimodal da Gemma.",
            )
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.TimeoutException:
        logger.warning(
            f"Gemma multimodal timed out after {_gemma_multimodal_timeout()}s; "
            f"falling back where possible. query={repr(query[:80])}"
        )
        if saved_path and uploaded_ext in ALLOWED_IMAGE_EXTENSIONS:
            return await _image_analysis_fallback_response(
                saved_path,
                "A análise multimodal da Gemma demorou demasiado tempo.",
            )
        raise HTTPException(status_code=504, detail="Gemma multimodal request timed out")
    except httpx.HTTPStatusError as e:
        logger.error(f"Gemma API error: {e.response.status_code} {e.response.text[:200]}")
        if saved_path and uploaded_ext in ALLOWED_IMAGE_EXTENSIONS:
            return await _image_analysis_fallback_response(
                saved_path,
                f"A análise multimodal da Gemma falhou com HTTP {e.response.status_code}.",
            )
        raise HTTPException(status_code=502, detail=f"Gemma API returned {e.response.status_code}")
    except httpx.RequestError as e:
        detail = str(e) or repr(e)
        logger.error(f"Gemma request failed: {type(e).__name__}: {detail}")
        if saved_path and uploaded_ext in ALLOWED_IMAGE_EXTENSIONS:
            return await _image_analysis_fallback_response(
                saved_path,
                f"Não consegui contactar a Gemma multimodal ({type(e).__name__}).",
            )
        raise HTTPException(status_code=502, detail=f"Gemma request failed: {detail}")
    except Exception as e:
        detail = str(e) or repr(e)
        logger.error(f"Multimodal chat failed: {type(e).__name__}: {detail}")
        if saved_path and uploaded_ext in ALLOWED_IMAGE_EXTENSIONS:
            return await _image_analysis_fallback_response(
                saved_path,
                f"A análise multimodal falhou ({type(e).__name__}).",
            )
        raise HTTPException(status_code=500, detail=f"Multimodal chat failed: {detail}")
    finally:
        if saved_path and os.path.exists(saved_path):
            try:
                os.remove(saved_path)
            except OSError:
                pass


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
