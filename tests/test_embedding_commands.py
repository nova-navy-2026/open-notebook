import asyncio
from unittest.mock import AsyncMock

from commands import embedding_commands
from open_notebook.exceptions import NotFoundError


def test_embed_note_missing_record_is_permanent_failure(monkeypatch):
    async def missing_note(_note_id):
        raise NotFoundError("note with id note:missing not found")

    generate_embedding = AsyncMock()
    monkeypatch.setattr(embedding_commands.Note, "get", missing_note)
    monkeypatch.setattr(embedding_commands, "generate_embedding", generate_embedding)

    result = asyncio.run(
        embedding_commands.embed_note_command(
            embedding_commands.EmbedNoteInput(note_id="note:missing")
        )
    )

    assert result.success is False
    assert result.note_id == "note:missing"
    assert "not found" in result.error_message
    generate_embedding.assert_not_called()


def test_embed_source_missing_record_is_permanent_failure(monkeypatch):
    async def missing_source(_source_id):
        raise NotFoundError("source with id source:missing not found")

    generate_embeddings = AsyncMock()
    monkeypatch.setattr(embedding_commands.Source, "get", missing_source)
    monkeypatch.setattr(embedding_commands, "generate_embeddings", generate_embeddings)

    result = asyncio.run(
        embedding_commands.embed_source_command(
            embedding_commands.EmbedSourceInput(source_id="source:missing")
        )
    )

    assert result.success is False
    assert result.source_id == "source:missing"
    assert result.chunks_created == 0
    assert "not found" in result.error_message
    generate_embeddings.assert_not_called()


def test_embed_insight_missing_record_is_permanent_failure(monkeypatch):
    async def missing_insight(_insight_id):
        raise NotFoundError("source_insight with id source_insight:missing not found")

    generate_embedding = AsyncMock()
    monkeypatch.setattr(embedding_commands.SourceInsight, "get", missing_insight)
    monkeypatch.setattr(embedding_commands, "generate_embedding", generate_embedding)

    result = asyncio.run(
        embedding_commands.embed_insight_command(
            embedding_commands.EmbedInsightInput(insight_id="source_insight:missing")
        )
    )

    assert result.success is False
    assert result.insight_id == "source_insight:missing"
    assert "not found" in result.error_message
    generate_embedding.assert_not_called()
