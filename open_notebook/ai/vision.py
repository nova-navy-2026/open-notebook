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
import mimetypes
from typing import Optional

from langchain_core.messages import HumanMessage
from loguru import logger

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

    # Build base64 data URL
    b64_data = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64_data}"

    caption_prompt = prompt or DEFAULT_CAPTION_PROMPT

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

    # Build multimodal message
    message = HumanMessage(
        content=[
            {"type": "text", "text": caption_prompt},
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            },
        ]
    )

    logger.info(
        f"Generating caption for image ({len(image_bytes) / 1024:.1f} KB, {mime_type})"
    )

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
        logger.info(f"Generated caption ({len(caption)} chars)")
        return caption

    except Exception as e:
        logger.error(f"Vision model failed to generate caption: {e}")
        raise ValueError(
            f"Failed to generate image caption: {e}. "
            "Ensure your vision model supports image input."
        ) from e


async def generate_video_caption(
    video_bytes: bytes,
    mime_type: str = "video/mp4",
    max_frames: int = 4,
    prompt: Optional[str] = None,
    model_id: Optional[str] = None,
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
        frame_prompt = (
            f"This is frame {i + 1} of {len(frames)} from a video. {prompt or DEFAULT_CAPTION_PROMPT}"
        )
        try:
            caption = await generate_image_caption(
                image_bytes=frame_bytes,
                mime_type="image/jpeg",
                prompt=frame_prompt,
                model_id=model_id,
            )
            captions.append(f"[Frame {i + 1}/{len(frames)}] {caption}")
        except Exception as e:
            logger.warning(f"Failed to caption frame {i + 1}: {e}")

    if not captions:
        raise ValueError("Failed to generate captions for any video frames")

    combined = "\n\n".join(captions)
    logger.info(
        f"Generated video caption from {len(captions)} frames ({len(combined)} chars)"
    )
    return combined
