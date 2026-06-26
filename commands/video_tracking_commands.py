"""Background command for object tracking across video frames.

Video tracking (SAM3 / RF-DETR per-frame detection + interpolation + H.264
re-encode) can run for tens of seconds — long enough that holding the HTTP
connection open trips proxy timeouts (Cloudflare's ~100s cap, nginx
proxy_read_timeout, etc.), surfacing as "socket hang up"/ECONNRESET even when
the backend succeeds. Running it as a surreal-commands job lets the API return a
job id immediately; the frontend then polls for the result, so no single request
is ever held open long enough to be reset.

State lives in SurrealDB (the command record) and the output file in DATA/
vision_uploads, so it works identically across the 4 API workers and any Docker
replicas — never in process memory.
"""

import os
import time
from typing import Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.research.video_service import run_video_tracking


class VideoTrackingInput(CommandInput):
    video_path: str
    target: Optional[str] = None
    engine: str = "sam3"
    # When true, also generate a descriptive caption of the video (frame
    # captions + audio transcription) and append it to the result text. Done
    # here in the worker so that a notebook note saved from the chat reply
    # already carries full context for the LLM — instead of captioning live in
    # the notebook (slow). The standalone Video Tracking page leaves this off.
    include_context: bool = False
    language: Optional[str] = None


async def _safe_video_context(video_path: str, language: Optional[str]) -> Optional[str]:
    """Best-effort caption + audio transcription of a video for note context.

    Never raises: a captioning failure (LLM down, no ffmpeg, no audio, …) must
    not break the tracking/segmentation result it is meant to enrich.
    """
    try:
        from open_notebook.ai.vision import generate_video_caption

        with open(video_path, "rb") as f:
            video_bytes = f.read()
        caption = await generate_video_caption(video_bytes, language=language)
        return (caption or "").strip() or None
    except Exception as e:
        logger.warning(
            "Video context caption failed ({}); continuing with tracking summary "
            "only.",
            type(e).__name__,
        )
        return None


class VideoTrackingOutput(CommandOutput):
    success: bool
    output_path: Optional[str] = None
    text: Optional[str] = None
    # Descriptive caption + audio transcription, kept SEPARATE from `text` (the
    # raw tracking summary) so the chat status endpoint can summarise the
    # tracking result and then append this context, without the summary step
    # discarding it. None when context wasn't requested or captioning failed.
    context_caption: Optional[str] = None
    processing_time: float = 0.0
    error_message: Optional[str] = None


@command("track_video", app="open_notebook", retry={"max_attempts": 1})
async def track_video_command(
    input_data: VideoTrackingInput,
) -> VideoTrackingOutput:
    """Run video object tracking in the background worker.

    The uploaded source file is removed once processing finishes (success or
    failure); the annotated output is left on disk for the status endpoint to
    serve, then that endpoint cleans it up.
    """
    start = time.time()
    try:
        result = await run_video_tracking(
            video_path=input_data.video_path,
            target=input_data.target,
            engine=input_data.engine,
        )
        # Descriptive context (caption + audio transcription) so a saved note
        # understands the video, not just the detection counts. Kept separate
        # from the raw tracking text (the chat endpoint summarises that, then
        # appends this).
        context_caption = None
        if input_data.include_context:
            context_caption = await _safe_video_context(
                input_data.video_path, input_data.language
            )
        # Return an ABSOLUTE path. The worker and the API are separate processes
        # (and may be separate containers sharing a volume); a relative path
        # would resolve against each one's CWD. Absolute removes that ambiguity
        # as long as they share the filesystem (login node, or a shared Docker
        # volume mounted at the same path).
        out = result.get("video_path")
        return VideoTrackingOutput(
            success=True,
            output_path=os.path.abspath(out) if out else None,
            text=result.get("text"),
            context_caption=context_caption,
            processing_time=time.time() - start,
        )
    except Exception as e:
        logger.error(f"track_video command failed: {e}")
        return VideoTrackingOutput(
            success=False,
            processing_time=time.time() - start,
            error_message=str(e) or repr(e),
        )
    finally:
        # run_video_tracking reads every frame up front, so the source upload is
        # no longer needed once it returns (or raises).
        try:
            os.remove(input_data.video_path)
        except OSError:
            pass
