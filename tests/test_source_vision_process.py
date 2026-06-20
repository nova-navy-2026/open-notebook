import asyncio
import base64
import io

from api.routers import chat as chat_router
from PIL import Image

from open_notebook.ai.vision import (
    build_caption_prompt,
    caption_language_name,
    generate_image_caption,
    prepare_image_for_caption,
)
from open_notebook.domain.notebook import Notebook, Source
from open_notebook.graphs import source as source_graph


def test_vision_process_uses_db_file_data_before_stale_file_path(monkeypatch):
    video_bytes = b"fake video bytes"
    source = Source(
        id="source:video",
        title="Video",
        file_data=base64.b64encode(video_bytes).decode("utf-8"),
        file_name="video.mp4",
        file_mime="video/mp4",
    )

    async def get_source(_source_id):
        return source

    async def generate_video_caption(video_bytes, mime_type, language=None):
        assert video_bytes == b"fake video bytes"
        assert mime_type == "video/mp4"
        assert language is None
        return "caption from video"

    monkeypatch.setattr(source_graph.Source, "get", get_source)
    monkeypatch.setattr(source_graph, "generate_video_caption", generate_video_caption)

    result = asyncio.run(
        source_graph.vision_process(
            {
                "source_id": "source:video",
                "content_state": {
                    "file_path": "/tmp/does-not-exist/video.mp4",
                    "delete_source": True,
                },
            }
        )
    )

    assert result["caption"] == "caption from video"
    assert result["content_state"].content == "caption from video"


def test_vision_process_passes_caption_language_for_images(monkeypatch):
    image_bytes = b"fake image bytes"
    source = Source(
        id="source:image",
        title="Image",
        file_data=base64.b64encode(image_bytes).decode("utf-8"),
        file_name="image.png",
        file_mime="image/png",
    )

    async def get_source(_source_id):
        return source

    async def generate_image_caption(image_bytes, mime_type, language=None):
        assert image_bytes == b"fake image bytes"
        assert mime_type == "image/png"
        assert language == "pt-PT"
        return "legenda em portugues"

    monkeypatch.setattr(source_graph.Source, "get", get_source)
    monkeypatch.setattr(source_graph, "generate_image_caption", generate_image_caption)

    result = asyncio.run(
        source_graph.vision_process(
            {
                "source_id": "source:image",
                "content_state": {},
                "caption_language": "pt-PT",
            }
        )
    )

    assert result["caption"] == "legenda em portugues"
    assert result["content_state"].content == "legenda em portugues"


def test_caption_prompt_uses_requested_locale_language():
    assert caption_language_name("pt-PT") == "European Portuguese (pt-PT)"
    assert caption_language_name("fr-FR,fr;q=0.9") == "French"

    prompt = build_caption_prompt("pt-PT")

    assert "Write the entire caption in European Portuguese (pt-PT)" in prompt
    assert "not Brazilian Portuguese" in prompt
    assert "transcribe them as accurately as possible" in prompt


def test_prepare_image_for_caption_normalizes_mislabeled_png():
    png_buffer = io.BytesIO()
    Image.new("RGBA", (16, 16), (255, 0, 0, 128)).save(png_buffer, format="PNG")

    normalized, mime_type = prepare_image_for_caption(
        png_buffer.getvalue(),
        "image/jpeg",
    )

    with Image.open(io.BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"

    assert mime_type == "image/jpeg"


def test_prepare_image_for_caption_keeps_unidentified_original():
    original = b"not really an image"

    normalized, mime_type = prepare_image_for_caption(original, "image/jpeg")

    assert normalized == original
    assert mime_type == "image/jpeg"


def test_generate_image_caption_retries_raw_base64_payload(monkeypatch):
    class Response:
        content = "legenda gerada"

    class FakeLLM:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, messages):
            image_url = messages[0].content[1]["image_url"]
            self.calls.append(image_url)
            if len(self.calls) == 1:
                raise Exception(
                    "Failed to load image: cannot identify image file "
                    "<_io.BytesIO object>"
                )
            return Response()

    fake_llm = FakeLLM()

    class FakeEsperantoModel:
        def to_langchain(self):
            return fake_llm

    class FakeModelManager:
        async def get_default_model(self, _model_type):
            return FakeEsperantoModel()

    image = io.BytesIO()
    Image.new("RGB", (10, 10), (0, 0, 255)).save(image, format="JPEG")

    monkeypatch.setattr(
        "open_notebook.ai.vision.ModelManager",
        lambda: FakeModelManager(),
    )

    caption = asyncio.run(
        generate_image_caption(
            image.getvalue(),
            mime_type="image/jpeg",
            language="pt-PT",
        )
    )

    assert caption == "legenda gerada"
    assert fake_llm.calls[0]["url"].startswith("data:image/jpeg;base64,")
    assert not fake_llm.calls[1]["url"].startswith("data:")


async def empty_insights(_source):
    return []


def test_source_short_context_includes_visual_caption(monkeypatch):
    monkeypatch.setattr(Source, "get_insights", empty_insights)
    source = Source(
        id="source:video",
        title="Video",
        full_text="Detailed video caption",
        caption="Detailed video caption",
        file_mime="video/mp4",
    )

    context = asyncio.run(source.get_context(context_size="short"))

    assert context["id"] == "source:video"
    assert context["caption"] == "Detailed video caption"
    assert context["file_mime"] == "video/mp4"
    assert "full_text" not in context


def test_chat_insights_mode_includes_visual_caption_when_no_insights(monkeypatch):
    monkeypatch.setattr(Source, "get_insights", empty_insights)
    source = Source(
        id="source:video",
        title="Video",
        full_text="Detailed video caption",
        caption="Detailed video caption",
        file_mime="video/mp4",
    )

    context = asyncio.run(
        chat_router._build_source_context_for_chat(source, "insights")
    )

    assert context["id"] == "source:video"
    assert context["caption"] == "Detailed video caption"
    assert context["full_text"] == "Detailed video caption"


def test_chat_insights_mode_keeps_visual_caption_when_insights_exist(monkeypatch):
    async def one_insight(_source):
        class Insight:
            def model_dump(self):
                return {
                    "id": "source_insight:test",
                    "title": "Auto insight",
                    "content": "Short insight only",
                }

        return [Insight()]

    monkeypatch.setattr(Source, "get_insights", one_insight)
    source = Source(
        id="source:video",
        title="GHXW6489.MP4",
        full_text="The video shows a patrol vessel entering harbor.",
        caption="The video shows a patrol vessel entering harbor.",
        file_mime="video/mp4",
    )

    context = asyncio.run(
        chat_router._build_source_context_for_chat(source, "insights")
    )

    assert context["id"] == "source:video"
    assert context["title"] == "GHXW6489.MP4"
    assert context["content_type"] == "video"
    assert context["visual_content"] == "The video shows a patrol vessel entering harbor."
    assert context["full_text"] == "The video shows a patrol vessel entering harbor."


def test_chat_visual_source_without_caption_reports_processing_status(monkeypatch):
    monkeypatch.setattr(Source, "get_insights", empty_insights)
    source = Source(
        id="source:video",
        title="GHXW6489.MP4",
        file_mime="video/mp4",
    )

    context = asyncio.run(
        chat_router._build_source_context_for_chat(source, "insights")
    )

    assert context["content_type"] == "video"
    assert "caption processing has not completed" in context["processing_status"]
    assert context["full_text"] == context["processing_status"]


def test_chat_context_combines_surrealdb_sources_and_navy_opensearch(monkeypatch):
    notebook = Notebook(
        id="notebook:test",
        name="Notebook",
        description="",
        owner="user:test",
    )
    source = Source(
        id="source:upload",
        title="Uploaded source",
        full_text="Content stored in SurrealDB",
        owner="user:test",
    )

    async def get_notebook(_notebook_id):
        return notebook

    async def get_source(_source_id):
        return source

    async def vector_search_navy_documents(query, doc_ids, k, user_id):
        assert query == "question"
        assert doc_ids == ["doc:allowed"]
        assert user_id == "navy:user"
        return [
            {
                "doc_id": "doc:allowed",
                "section_title": "Allowed section",
                "page_start": 7,
                "content": "ACL-filtered OpenSearch content",
            }
        ]

    import open_notebook.search.navy_docs as navy_docs

    monkeypatch.setattr(chat_router.Notebook, "get", get_notebook)
    monkeypatch.setattr(chat_router.Source, "get", get_source)
    monkeypatch.setattr(Source, "get_insights", empty_insights)
    monkeypatch.setattr(
        navy_docs, "vector_search_navy_documents", vector_search_navy_documents
    )

    result = asyncio.run(
        chat_router.build_context(
            chat_router.BuildContextRequest(
                notebook_id="notebook:test",
                context_config={
                    "sources": {"source:upload": "full content"},
                    "notes": {},
                    "navy_docs": {"doc_ids": ["doc:allowed"]},
                },
                query="question",
            ),
            navy_user_id="navy:user",
            auth_user_id="user:test",
        )
    )

    assert result.context["sources"][0]["id"] == "source:upload"
    assert result.context["sources"][0]["full_text"] == "Content stored in SurrealDB"
    assert (
        result.context["navy_corpus"][0]["content"]
        == "ACL-filtered OpenSearch content"
    )
