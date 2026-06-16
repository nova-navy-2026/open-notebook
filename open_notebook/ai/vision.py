"""
Vision / Image Captioning Module

Generates text descriptions of images using a vision-capable LLM.
Works with any provider whose LangChain model supports multimodal
HumanMessage content (OpenAI GPT-4o, Anthropic Claude 3+, Google Gemini,
Ollama llava, etc.).

The module uses the `default_vision_model` setting (falls back to the
default chat model) and sends the image as a base64 data-URL inside a
standard LangChain `HumanMessage`.
"""

import base64
import io
import mimetypes
from typing import Optional

from langchain_core.messages import HumanMessage
from loguru import logger
from PIL import Image, ImageOps, UnidentifiedImageError

from open_notebook.ai.models import ModelManager
from open_notebook.exceptions import ConfigurationError

# MIME types we can caption directly
IMAGE_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/tiff",
    }
)

# MIME types that are video (need frame extraction before captioning)
VIDEO_MIME_TYPES = frozenset(
    {
        "video/mp4",
        "video/mpeg",
        "video/quicktime",
        "video/x-msvideo",
        "video/webm",
        "video/x-matroska",
    }
)

# Default prompt for image captioning
DEFAULT_CAPTION_PROMPT = (
    "Describe this image in detail. Include:\n"
    "- What the image shows (objects, people, scenes)\n"
    "- Any visible text, labels, diagrams, or charts\n"
    "- The overall context or purpose of the image\n"
    "- Colors, layout, and any notable visual elements\n\n"
    "Be thorough but concise. This description will be used for search indexing."
)

LANGUAGE_NAMES = {
    "en": "English",
    "pt": "European Portuguese (pt-PT)",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "de": "German",
    "nl": "Dutch",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "bn": "Bengali",
}

MAX_CAPTION_IMAGE_DIMENSION = 2048


def caption_language_name(language: Optional[str]) -> Optional[str]:
    """Return a human-readable language name from a locale/header value."""
    if not language:
        return None

    primary = language.split(",", 1)[0].strip()
    if not primary:
        return None

    code = primary.split(";", 1)[0].split("-", 1)[0].split("_", 1)[0].lower()
    return LANGUAGE_NAMES.get(code, primary)


def build_caption_prompt(language: Optional[str] = None) -> str:
    """Build the source-caption prompt in the user's requested language."""
    language_name = caption_language_name(language)
    language_instruction = (
        f"Write the entire caption in {language_name}."
        if language_name
        else "Write the caption in English."
    )
    if language_name == "European Portuguese (pt-PT)":
        language_instruction += (
            " Use European Portuguese vocabulary and grammar, not Brazilian Portuguese. "
            "Avoid Brazilian forms such as 'você', 'usuário', 'arquivo', 'mídia', "
            "'tela', 'ônibus', and 'celular'; prefer pt-PT forms such as 'tu'/'o utilizador' "
            "when needed, 'ficheiro', 'media', 'ecrã', 'autocarro', and 'telemóvel'."
        )
    return (
        f"{language_instruction}\n\n"
        "Analyze this visual source for use as searchable notebook context.\n"
        "Include:\n"
        "- A concise summary of what the image shows\n"
        "- The important objects, people, scenes, diagrams, charts, or UI elements\n"
        "- Any visible text, labels, numbers, tables, legends, or headings; transcribe them as accurately as possible\n"
        "- The likely purpose or context of the image\n"
        "- Notable colors, layout, spatial relationships, and details that could matter for later questions\n\n"
        "If text is unclear, say that it is unclear instead of inventing it. "
        "Be detailed enough for search and question answering, but do not add facts that are not visible."
    )


def _normalize_pil_image(image: Image.Image) -> Image.Image:
    """Normalize a Pillow image for stable LLM vision ingestion."""
    image = ImageOps.exif_transpose(image)
    try:
        image.seek(0)
    except EOFError:
        pass

    if max(image.size) > MAX_CAPTION_IMAGE_DIMENSION:
        image.thumbnail((MAX_CAPTION_IMAGE_DIMENSION, MAX_CAPTION_IMAGE_DIMENSION))

    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba_image = image.convert("RGBA")
        background = Image.new("RGBA", rgba_image.size, (255, 255, 255, 255))
        background.alpha_composite(rgba_image)
        return background.convert("RGB")

    if image.mode != "RGB":
        return image.convert("RGB")

    return image


def _encode_image_for_caption(
    image_bytes: bytes,
    image_format: str,
) -> tuple[bytes, str]:
    """Decode uploaded bytes and re-encode to a simple image format."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = _normalize_pil_image(image)
        output = io.BytesIO()
        if image_format == "JPEG":
            image.save(output, format="JPEG", quality=90, optimize=True)
            return output.getvalue(), "image/jpeg"
        image.save(output, format="PNG", optimize=True)
        return output.getvalue(), "image/png"


def prepare_image_for_caption(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> tuple[bytes, str]:
    """Normalize uploaded images into a vision-backend-friendly JPEG.

    Some local/OpenAI-compatible vision servers fail on camera JPEGs with EXIF
    orientation, CMYK color, unusual metadata, or animated/legacy formats. We
    decode locally and re-encode a plain RGB JPEG before sending it to the LLM.
    If Pillow cannot identify the image, return the original bytes so the model
    error still surfaces with the provider's details.
    """
    try:
        normalized, normalized_mime = _encode_image_for_caption(image_bytes, "JPEG")

        if normalized and normalized != image_bytes:
            logger.debug(
                "Normalized image for captioning: "
                f"{len(image_bytes) / 1024:.1f} KB {mime_type} -> "
                f"{len(normalized) / 1024:.1f} KB {normalized_mime}"
            )
            return normalized, normalized_mime

    except (UnidentifiedImageError, OSError, ValueError) as e:
        logger.warning(
            f"Could not normalize uploaded image before captioning: {e}. "
            "Sending original bytes to the vision model."
        )

    return image_bytes, mime_type


def prepare_caption_image_payloads(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> list[tuple[str, bytes, str]]:
    """Return ordered image byte variants to try with vision providers."""
    payloads: list[tuple[str, bytes, str]] = []

    primary_bytes, primary_mime = prepare_image_for_caption(image_bytes, mime_type)
    payloads.append(("jpeg", primary_bytes, primary_mime))

    try:
        png_bytes, png_mime = _encode_image_for_caption(image_bytes, "PNG")
        if png_bytes != primary_bytes:
            payloads.append(("png", png_bytes, png_mime))
    except (UnidentifiedImageError, OSError, ValueError) as e:
        logger.debug(f"Could not create PNG image fallback for captioning: {e}")

    return payloads


def is_provider_image_decode_error(error: Exception) -> bool:
    """Return True for provider errors caused by image payload decoding."""
    text = str(error).lower()
    return (
        "cannot identify image file" in text
        or "failed to load image" in text
        or "invalid image" in text
        or "image decode" in text
    )


def is_image_mime(mime_type: Optional[str]) -> bool:
    """Check whether a MIME type is a directly-captionable image."""
    return mime_type in IMAGE_MIME_TYPES if mime_type else False


def is_video_mime(mime_type: Optional[str]) -> bool:
    """Check whether a MIME type is a video (needs frame extraction)."""
    return mime_type in VIDEO_MIME_TYPES if mime_type else False


def is_visual_mime(mime_type: Optional[str]) -> bool:
    """Check whether a MIME type is any visual content (image or video)."""
    return is_image_mime(mime_type) or is_video_mime(mime_type)


def guess_mime_from_filename(filename: Optional[str]) -> Optional[str]:
    """Guess MIME type from a filename."""
    if not filename:
        return None
    guessed, _ = mimetypes.guess_type(filename)
    return guessed


async def generate_image_caption(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    prompt: Optional[str] = None,
    model_id: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    """Generate a text description of an image using a vision-capable LLM.

    Args:
        image_bytes: Raw image file content.
        mime_type: MIME type of the image (e.g. "image/jpeg").
        prompt: Custom prompt override. Uses DEFAULT_CAPTION_PROMPT if None.
        model_id: Specific model ID to use. Falls back to default_vision_model
                  (then default_chat_model) if None.

    Returns:
        The generated caption text.

    Raises:
        ConfigurationError: If no vision model is configured.
        ValueError: If the model doesn't support vision or the image is empty.
    """
    if not image_bytes:
        raise ValueError("Empty image data")

    caption_prompt = prompt or build_caption_prompt(language)

    # Provision the vision model via ModelManager → .to_langchain()
    model_manager = ModelManager()

    if model_id:
        esperanto_model = await model_manager.get_model(model_id)
    else:
        esperanto_model = await model_manager.get_default_model("vision")

    if esperanto_model is None:
        raise ConfigurationError(
            "No vision model configured. "
            "Please go to Settings → Models and set a Vision Model "
            "(any language model that supports image input, e.g. GPT-4o, Claude Sonnet, Gemini)."
        )

    # Convert to LangChain model — the native LangChain models
    # (ChatOpenAI, ChatAnthropic, etc.) support multimodal messages directly.
    llm = esperanto_model.to_langchain()

    image_payloads = prepare_caption_image_payloads(image_bytes, mime_type)
    content_variants = []
    for image_label, payload_bytes, payload_mime in image_payloads:
        b64_data = base64.b64encode(payload_bytes).decode("utf-8")
        data_url = f"data:{payload_mime};base64,{b64_data}"
        content_variants.extend(
            [
                (
                    f"{image_label}_data_url",
                    payload_bytes,
                    payload_mime,
                    [
                        {"type": "text", "text": caption_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                ),
                (
                    f"{image_label}_raw_base64",
                    payload_bytes,
                    payload_mime,
                    [
                        {"type": "text", "text": caption_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": b64_data},
                        },
                    ],
                ),
                (
                    f"{image_label}_string_data_url",
                    payload_bytes,
                    payload_mime,
                    [
                        {"type": "text", "text": caption_prompt},
                        {
                            "type": "image_url",
                            "image_url": data_url,
                        },
                    ],
                ),
            ]
        )

    logger.info(
        "Generating caption for image "
        f"({len(image_payloads[0][1]) / 1024:.1f} KB, {image_payloads[0][2]}, "
        f"fallbacks={len(content_variants)})"
    )

    last_error: Optional[Exception] = None
    for variant_name, payload_bytes, payload_mime, content in content_variants:
        message = HumanMessage(content=content)

        try:
            response = await llm.ainvoke([message])
            caption = response.content

            if isinstance(caption, list):
                # Some models return list of content blocks
                caption = " ".join(
                    block.get("text", str(block))
                    if isinstance(block, dict)
                    else str(block)
                    for block in caption
                )

            caption = str(caption).strip()
            logger.info(
                f"Generated caption ({len(caption)} chars, "
                f"image_format={variant_name}, "
                f"image_size_kb={len(payload_bytes) / 1024:.1f}, "
                f"mime={payload_mime})"
            )
            return caption

        except Exception as e:
            last_error = e
            if variant_name != content_variants[-1][0] and is_provider_image_decode_error(e):
                logger.warning(
                    "Vision model could not decode image with "
                    f"{variant_name}; retrying alternate payload format: {e}"
                )
                continue

            logger.error(f"Vision model failed to generate caption: {e}")
            raise ValueError(
                f"Failed to generate image caption: {e}. "
                "Ensure your vision model supports image input."
            ) from e

    if last_error:
        raise ValueError(
            f"Failed to generate image caption: {last_error}. "
            "Ensure your vision model supports image input."
        ) from last_error

    raise ValueError("Failed to generate image caption")


async def generate_video_caption(
    video_bytes: bytes,
    mime_type: str = "video/mp4",
    max_frames: Optional[int] = None,
    prompt: Optional[str] = None,
    model_id: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    """Generate a text description of a video by captioning sampled frames.

    Extracts up to `max_frames` evenly-spaced frames from the video and
    captions each one, then combines them into a single description.

    Requires ffmpeg to be available on the system PATH.

    Args:
        video_bytes: Raw video file content.
        mime_type: MIME type of the video.
        max_frames: Maximum number of frames to extract and caption.
        prompt: Custom prompt per frame. Uses DEFAULT_CAPTION_PROMPT if None.
        model_id: Specific model ID to use.

    Returns:
        Combined caption text from all sampled frames.
    """
    import subprocess
    import tempfile

    if not video_bytes:
        raise ValueError("Empty video data")

    if max_frames is None:
        from open_notebook.config import VIDEO_CAPTION_MAX_FRAMES

        max_frames = VIDEO_CAPTION_MAX_FRAMES

    frames: list[bytes] = []

    # Write video to temp file for ffmpeg
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp_video:
        tmp_video.write(video_bytes)
        tmp_video.flush()

        # Get video duration
        try:
            probe_result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    tmp_video.name,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            duration = float(probe_result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
            logger.warning(f"Could not probe video duration: {e}. Using single frame.")
            duration = 0

        # Calculate timestamps for evenly-spaced frames
        if duration > 0 and max_frames > 1:
            timestamps = [
                duration * i / (max_frames + 1) for i in range(1, max_frames + 1)
            ]
        else:
            timestamps = [0]  # Just grab the first frame

        # Extract each frame as JPEG
        for ts in timestamps:
            try:
                frame_result = subprocess.run(
                    [
                        "ffmpeg",
                        "-ss",
                        str(ts),
                        "-i",
                        tmp_video.name,
                        "-vframes",
                        "1",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "mjpeg",
                        "-q:v",
                        "2",
                        "-",
                    ],
                    capture_output=True,
                    timeout=30,
                )
                if frame_result.stdout:
                    frames.append(frame_result.stdout)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.warning(f"Failed to extract frame at {ts}s: {e}")

    if not frames:
        raise ValueError(
            "Could not extract any frames from video. "
            "Ensure ffmpeg is installed and the video format is supported."
        )

    logger.info(f"Extracted {len(frames)} frames from video for captioning")

    # Caption each frame
    captions: list[str] = []
    for i, frame_bytes in enumerate(frames):
        frame_prompt = prompt or (
            f"This is frame {i + 1} of {len(frames)} from a video. "
            f"{build_caption_prompt(language)}"
        )
        try:
            caption = await generate_image_caption(
                image_bytes=frame_bytes,
                mime_type="image/jpeg",
                prompt=frame_prompt,
                model_id=model_id,
                language=language,
            )
            captions.append(f"[{i + 1}/{len(frames)}] {caption}")
        except Exception as e:
            logger.warning(f"Failed to caption frame {i + 1}: {e}")

    if not captions:
        raise ValueError("Failed to generate captions for any video frames")

    combined = "\n\n".join(captions)
    logger.info(
        f"Generated video caption from {len(captions)} frames ({len(combined)} chars)"
    )
    return combined
