import asyncio
import operator
import os
import time
from typing import Any, Dict, List, Optional

# Hard timeout (seconds) on a single extract_content call. Without this,
# a hang inside content_core (e.g. docling model load, network fetch) would
# pin a worker indefinitely and only surface as a silent retry storm.
EXTRACT_CONTENT_TIMEOUT_SECONDS = 180

from content_core import extract_content
from content_core.common import ProcessSourceState
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger
from typing_extensions import Annotated, TypedDict

from open_notebook.ai.models import Model, ModelManager
from open_notebook.ai.vision import (
    generate_image_caption,
    generate_video_caption,
    guess_mime_from_filename,
    is_image_mime,
    is_video_mime,
    is_visual_mime,
)
from open_notebook.domain.content_settings import ContentSettings
from open_notebook.domain.notebook import Asset, Source
from open_notebook.domain.transformation import Transformation
from open_notebook.graphs.transformation import graph as transform_graph


class SourceState(TypedDict):
    content_state: ProcessSourceState
    apply_transformations: List[Transformation]
    source_id: str
    notebook_ids: List[str]
    source: Source
    transformation: Annotated[list, operator.add]
    embed: bool
    caption: Optional[str]


class TransformationState(TypedDict):
    source: Source
    transformation: Transformation


async def content_process(state: SourceState) -> dict:
    _t0 = time.time()
    content_settings: ContentSettings = await ContentSettings.get_instance()  # type: ignore[assignment]
    content_state: Dict[str, Any] = state["content_state"]  # type: ignore[assignment]

    content_state["url_engine"] = (
        content_settings.default_content_processing_engine_url or "auto"
    )
    content_state["document_engine"] = (
        content_settings.default_content_processing_engine_doc or "auto"
    )
    content_state["output_format"] = "markdown"

    # Add speech-to-text model configuration from Default Models
    try:
        model_manager = ModelManager()
        defaults = await model_manager.get_defaults()
        if defaults.default_speech_to_text_model:
            stt_model = await Model.get(defaults.default_speech_to_text_model)
            if stt_model:
                content_state["audio_provider"] = stt_model.provider
                content_state["audio_model"] = stt_model.name
                logger.debug(
                    f"Using speech-to-text model: {stt_model.provider}/{stt_model.name}"
                )
    except Exception as e:
        logger.warning(f"Failed to retrieve speech-to-text model configuration: {e}")
        # Continue without custom audio model (content-core will use its default)

    # Pre-flight: if a file_path was provided but it doesn't exist on disk,
    # try to rehydrate the file from the SurrealDB Source record. This handles:
    #   1. Cross-process file-visibility issues on Docker Desktop's 9p mount
    #      (Windows host) where the API just wrote the file but the worker
    #      can't see it yet.
    #   2. delete_source=True having consumed the file on a previous attempt.
    #   3. Future deployments where the API doesn't write a temp file at all.
    fp = content_state.get("file_path")
    if fp and not os.path.isfile(fp):
        rehydrated = False
        source_id = state.get("source_id")
        if source_id:
            try:
                src_for_bytes = await Source.get(source_id)
                file_bytes = (
                    src_for_bytes.get_file_bytes() if src_for_bytes else None
                )
                if file_bytes:
                    # Write to /tmp (container overlay FS, not the 9p mount)
                    # using the original filename so content_core's extension
                    # detection still routes to the correct processor.
                    import tempfile
                    suffix = os.path.splitext(fp)[1] or ""
                    tmp_dir = tempfile.mkdtemp(prefix="onb_source_")
                    rehydrated_path = os.path.join(
                        tmp_dir, os.path.basename(fp) or f"source{suffix}"
                    )
                    with open(rehydrated_path, "wb") as fh:
                        fh.write(file_bytes)
                    logger.info(
                        f"[source_graph] content_process: rehydrated "
                        f"{len(file_bytes)} bytes from DB to {rehydrated_path} "
                        f"(original path '{fp}' was missing on disk)"
                    )
                    content_state["file_path"] = rehydrated_path
                    fp = rehydrated_path
                    rehydrated = True
            except Exception as rehydrate_err:
                logger.warning(
                    f"[source_graph] content_process: failed to rehydrate "
                    f"source {source_id} from DB: {rehydrate_err}"
                )

        if not rehydrated:
            raise ValueError(
                f"Input file not found at '{fp}' and no DB-stored bytes "
                f"available for source {source_id}. The upload may have "
                f"failed or the file was consumed by a previous attempt."
            )

    logger.info(
        f"[source_graph] content_process: starting extract_content "
        f"(url_engine={content_state.get('url_engine')}, "
        f"document_engine={content_state.get('document_engine')})"
    )
    _extract_t0 = time.time()
    try:
        processed_state = await asyncio.wait_for(
            extract_content(content_state),
            timeout=EXTRACT_CONTENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(
            f"[source_graph] content_process: extract_content TIMED OUT after "
            f"{EXTRACT_CONTENT_TIMEOUT_SECONDS}s "
            f"(url_engine={content_state.get('url_engine')}, "
            f"document_engine={content_state.get('document_engine')}, "
            f"file_path={content_state.get('file_path')}, "
            f"url={content_state.get('url')})"
        )
        # Raise ValueError so source_commands stop_on prevents retry storm.
        raise ValueError(
            f"Content extraction timed out after "
            f"{EXTRACT_CONTENT_TIMEOUT_SECONDS}s. The source may be too large "
            f"or the configured engine may be hanging. Try a different "
            f"document/url engine in Settings."
        )
    logger.info(
        f"[source_graph] content_process: extract_content took "
        f"{time.time() - _extract_t0:.2f}s"
    )

    if not processed_state.content or not processed_state.content.strip():
        url = processed_state.url or ""
        if url and ("youtube.com" in url or "youtu.be" in url):
            raise ValueError(
                "Could not extract content from this YouTube video. "
                "No transcript or subtitles are available. "
                "Try configuring a Speech-to-Text model in Settings "
                "to transcribe the audio instead."
            )
        raise ValueError(
            "Could not extract any text content from this source. "
            "The content may be empty, inaccessible, or in an unsupported format."
        )

    logger.info(
        f"[source_graph] content_process: total {time.time() - _t0:.2f}s, "
        f"extracted {len(processed_state.content or '')} chars"
    )
    return {"content_state": processed_state}


async def route_by_content_type(state: SourceState) -> str:
    """Route to vision processing for images/video, normal processing otherwise."""
    # Check source's file_mime (set during upload via store_file)
    try:
        source = await Source.get(state["source_id"])
        if source and source.file_mime and is_visual_mime(source.file_mime):
            logger.info(
                f"Routing source {source.id} to vision processing (mime: {source.file_mime})"
            )
            return "vision_process"
    except Exception as e:
        logger.warning(f"Could not check source for vision routing: {e}")

    # Check file_path extension as fallback
    content_state: Dict[str, Any] = state.get("content_state", {})  # type: ignore[assignment]
    file_path = content_state.get("file_path", "")
    if file_path:
        mime = guess_mime_from_filename(file_path)
        if is_visual_mime(mime):
            logger.info(f"Routing to vision processing (file: {file_path}, mime: {mime})")
            return "vision_process"

    # Check URL extension as fallback
    url = content_state.get("url", "")
    if url:
        mime = guess_mime_from_filename(url.split("?")[0])  # strip query params
        if is_visual_mime(mime):
            logger.info(f"Routing to vision processing (url: {url}, mime: {mime})")
            return "vision_process"

    return "content_process"


async def vision_process(state: SourceState) -> dict:
    """Process visual content (images, video) by generating a caption via vision LLM."""
    import base64

    source = await Source.get(state["source_id"])
    if not source:
        raise ValueError(f"Source with ID {state['source_id']} not found")

    content_state: Dict[str, Any] = state.get("content_state", {})  # type: ignore[assignment]

    # Determine MIME type
    mime_type = source.file_mime or "image/jpeg"

    # Get image/video bytes — prefer the file on disk (temp file from upload),
    # then fall back to the DB-stored file_data
    image_bytes: Optional[bytes] = None

    file_path = content_state.get("file_path")
    if file_path:
        try:
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            logger.debug(f"Read {len(image_bytes)} bytes from disk: {file_path}")
        except Exception as e:
            logger.warning(f"Could not read file from disk: {e}")

    if not image_bytes and source.file_data:
        try:
            image_bytes = base64.b64decode(source.file_data)
            logger.debug(f"Read {len(image_bytes)} bytes from DB file_data")
        except Exception as e:
            logger.warning(f"Could not decode file_data from DB: {e}")

    if not image_bytes:
        raise ValueError(
            "No image data available for vision processing. "
            "The file may not have been uploaded correctly."
        )

    # Generate caption
    try:
        if is_video_mime(mime_type):
            caption = await generate_video_caption(
                video_bytes=image_bytes, mime_type=mime_type
            )
        else:
            caption = await generate_image_caption(
                image_bytes=image_bytes, mime_type=mime_type
            )
    except Exception as e:
        logger.error(f"Vision captioning failed: {e}")
        raise ValueError(
            f"Failed to generate caption for visual content: {e}. "
            "Ensure a vision-capable model is configured in Settings → Models."
        ) from e

    logger.info(f"Generated caption ({len(caption)} chars) for source {source.id}")

    # Build a ProcessSourceState-compatible result so save_source can use it
    processed_state = ProcessSourceState(
        content=caption,
        title=source.file_name or source.title or "Visual Content",
        file_path=content_state.get("file_path", ""),
        url=content_state.get("url", ""),
    )

    # Clean up temp file if needed
    if content_state.get("delete_source") and file_path:
        import os

        try:
            os.remove(file_path)
            logger.debug(f"Deleted temp file: {file_path}")
        except Exception as e:
            logger.warning(f"Could not delete temp file: {e}")

    return {"content_state": processed_state, "caption": caption}


async def save_source(state: SourceState) -> dict:
    _t0 = time.time()
    content_state = state["content_state"]

    # Get existing source using the provided source_id
    source = await Source.get(state["source_id"])
    if not source:
        raise ValueError(f"Source with ID {state['source_id']} not found")

    # Update the source with processed content
    source.asset = Asset(url=content_state.url, file_path=content_state.file_path)
    source.full_text = content_state.content

    # Preserve existing title if none provided in processed content
    if content_state.title:
        source.title = content_state.title

    # Set caption if generated by vision processing
    caption = state.get("caption")
    if caption:
        source.caption = caption

    await source.save()

    # NOTE: Notebook associations are created by the API immediately for UI responsiveness
    # No need to create them here to avoid duplicate edges

    if state["embed"]:
        if source.full_text and source.full_text.strip():
            logger.debug("Embedding content for vector search")
            await source.vectorize()
        else:
            logger.warning(
                f"Source {source.id} has no text content to embed, skipping vectorization"
            )

    logger.info(
        f"[source_graph] save_source: total {time.time() - _t0:.2f}s "
        f"(embed_submitted={state['embed']})"
    )
    return {"source": source}


def trigger_transformations(state: SourceState, config: RunnableConfig) -> List[Send]:
    if len(state["apply_transformations"]) == 0:
        return []

    to_apply = state["apply_transformations"]
    logger.debug(f"Applying transformations {to_apply}")

    return [
        Send(
            "transform_content",
            {
                "source": state["source"],
                "transformation": t,
            },
        )
        for t in to_apply
    ]


async def transform_content(state: TransformationState) -> Optional[dict]:
    source = state["source"]
    content = source.full_text
    if not content:
        return None
    transformation: Transformation = state["transformation"]

    logger.info(
        f"[source_graph] transform_content: starting transformation "
        f"'{transformation.name}' on {len(content)} chars"
    )
    _t0 = time.time()
    result = await transform_graph.ainvoke(
        dict(input_text=content, transformation=transformation)  # type: ignore[arg-type]
    )
    logger.info(
        f"[source_graph] transform_content: transformation '{transformation.name}' "
        f"took {time.time() - _t0:.2f}s"
    )
    await source.add_insight(transformation.title, result["output"])
    return {
        "transformation": [
            {
                "output": result["output"],
                "transformation_name": transformation.name,
            }
        ]
    }


# Create and compile the workflow
workflow = StateGraph(SourceState)

# Add nodes
workflow.add_node("content_process", content_process)
workflow.add_node("vision_process", vision_process)
workflow.add_node("save_source", save_source)
workflow.add_node("transform_content", transform_content)
# Define the graph edges
# Route from START based on content type (image/video → vision, else → content_core)
workflow.add_conditional_edges(
    START,
    route_by_content_type,
    {"content_process": "content_process", "vision_process": "vision_process"},
)
workflow.add_edge("content_process", "save_source")
workflow.add_edge("vision_process", "save_source")
workflow.add_conditional_edges(
    "save_source", trigger_transformations, ["transform_content"]
)
workflow.add_edge("transform_content", END)

# Compile the graph
source_graph = workflow.compile()
