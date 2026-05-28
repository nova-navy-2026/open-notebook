"""
Vision API router - endpoints for image analysis via MCP researcher.

Uses NOVA-Researcher GPTResearcher with the vision MCP config
(mcp_vision.py → SAM3) to analyze uploaded images.
"""

import base64
import asyncio
import json
import os
import re
import subprocess
import sys
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


def _gemma_multimodal_timeout() -> float:
    try:
        return float(os.environ.get("GEMMA_MULTIMODAL_TIMEOUT", "75"))
    except ValueError:
        return 75.0


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
    - videos: extract first frame as JPEG
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
            frame = _first_frame_as_jpeg(asset_path)
            if frame:
                results.append((frame, "image/jpeg"))
                logger.info(f"Extracted first frame from video asset: {filename}")
            else:
                logger.warning(f"Could not extract first frame from: {filename}")
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
    async with httpx.AsyncClient(timeout=_gemma_multimodal_timeout()) as client:
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

_DETECTION_WORDS = {
    "detect", "detecta", "detetar", "detectar", "detection",
    "identify", "identifica", "identificar", "identification",
    "find", "encontra", "encontrar", "locate", "localiza", "localizar",
    "count", "conta", "contar", "segment", "segmenta", "segmentar",
    "track", "segue", "seguir", "rastreia", "rastrear",
}

_OCR_WORDS = {
    "ocr", "texto", "text", "ler", "read", "extrair", "extract",
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
            return "sam3", target or _normalise_query_text(query) or None
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
        text = await _call_gemma(prompt, images, max_tokens=_gemma_ocr_max_tokens())
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
            return {
                "text": (
                    "OCR concluído com Docling.\n\n"
                    f"{text}"
                ),
                "route": "ocr",
                "engine": "docling",
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
    prompt = query
    if context and context.strip():
        prompt = f"{query}\n\n---\nContext:\n\n{context.strip()}"

    # Collect images: user-uploaded image first, then assets embedded in context.
    # Video uploads are handled by the video tracking agent when the request is
    # detection/tracking-like; otherwise Gemma receives the first frame.
    images: List[Tuple[bytes, str]] = []
    saved_path: Optional[str] = None
    uploaded_ext: Optional[str] = None

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
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            try:
                return await _run_ocr_with_fallback(
                    query=query,
                    image_path=saved_path,
                    images=[(file_bytes, mime_map.get(ext, "image/jpeg"))],
                    context=context,
                    media_kind="imagem",
                )
            finally:
                try:
                    os.remove(saved_path)
                except OSError:
                    pass

        if ext in ALLOWED_IMAGE_EXTENSIONS and _looks_like_detection_task(query):
            engine, target = _choose_visual_engine(query)
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
                return {
                    "text": text,
                    "route": "image_analysis",
                    "engine": engine,
                    "image_base64": result.get("image_base64"),
                }
            finally:
                try:
                    os.remove(saved_path)
                except OSError:
                    pass

        if ext in ALLOWED_VIDEO_EXTENSIONS and _looks_like_detection_task(query):
            engine, target = _choose_visual_engine(query)
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
                return {
                    "text": text,
                    "route": "video_tracking",
                    "engine": engine,
                    "video_base64": video_base64,
                }
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
                    frame_id = uuid.uuid4().hex[:12]
                    frame_path = os.path.abspath(
                        os.path.join(VISION_UPLOADS_DIR, f"{frame_id}.jpg")
                    )
                    with open(frame_path, "wb") as f:
                        f.write(frame)
                    try:
                        return await _run_ocr_with_fallback(
                            query=query,
                            image_path=frame_path,
                            images=[(frame, "image/jpeg")],
                            context=context,
                            media_kind="primeiro fotograma do vídeo",
                        )
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
        f"context_len={len(context) if context else 0}, query={repr(query[:80])}"
    )

    try:
        text = await _call_gemma(prompt, images or None)
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
