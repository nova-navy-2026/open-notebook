"""
OpenSearch reindex command.

Reads all existing embeddings from SurrealDB and bulk-indexes them into
OpenSearch.  Useful for:
- Initial migration when enabling OpenSearch for the first time
- Rebuilding the OpenSearch index after a dimension change
- Recovering from OpenSearch data loss
"""

import time
from typing import Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.database.repository import repo_query
from open_notebook.search.indexer import (
    bulk_index,
    delete_index,
    refresh_index,
)


class ReindexOpenSearchInput(CommandInput):
    """Input for the reindex_opensearch command."""

    delete_existing: bool = True  # Delete and recreate the index first


class ReindexOpenSearchOutput(CommandOutput):
    """Output from the reindex_opensearch command."""

    success: bool
    source_embeddings_indexed: int = 0
    insights_indexed: int = 0
    notes_indexed: int = 0
    total_indexed: int = 0
    processing_time: float = 0.0
    error_message: Optional[str] = None


@command("reindex_opensearch", app="open_notebook", retry=None)
async def reindex_opensearch_command(
    input_data: ReindexOpenSearchInput,
) -> ReindexOpenSearchOutput:
    """
    Bulk-reindex all embeddings from SurrealDB into OpenSearch.

    Flow:
    1. Optionally delete the existing OpenSearch index
    2. Query all source_embedding records (with source metadata)
    3. Query all source_insight records (with source metadata)
    4. Query all note records with embeddings
    5. Bulk-index everything into OpenSearch
    6. Refresh the index

    This command does NOT regenerate embeddings — it just copies the
    existing vectors from SurrealDB into OpenSearch.
    """
    start_time = time.time()

    try:
        logger.info("=" * 60)
        logger.info("Starting OpenSearch reindex from SurrealDB")
        logger.info("=" * 60)

        # 1. Delete existing index if requested
        if input_data.delete_existing:
            logger.info("Deleting existing OpenSearch index...")
            await delete_index()

        # 2. Query source embeddings with parent source metadata
        logger.info("Querying source embeddings...")
        source_embeddings = await repo_query(
            """
            SELECT
                id,
                content,
                embedding,
                order,
                source.id as source_id,
                source.title as source_title,
                source.owner as owner
            FROM source_embedding
            WHERE embedding != none AND array::len(embedding) > 0
            """
        )
        logger.info(f"Found {len(source_embeddings)} source embeddings")

        # 3. Query source insights with parent source metadata
        logger.info("Querying source insights...")
        insights = await repo_query(
            """
            SELECT
                id,
                insight_type,
                content,
                embedding,
                source.id as source_id,
                source.title as source_title,
                owner
            FROM source_insight
            WHERE embedding != none AND array::len(embedding) > 0
            """
        )
        logger.info(f"Found {len(insights)} source insights")

        # 4. Query notes with embeddings
        logger.info("Querying notes...")
        notes = await repo_query(
            """
            SELECT id, title, content, embedding, owner
            FROM note
            WHERE embedding != none AND array::len(embedding) > 0
            """
        )
        logger.info(f"Found {len(notes)} notes")

        # 5. Build document list for bulk indexing
        docs = []

        for se in source_embeddings:
            if not se.get("embedding"):
                continue
            docs.append(
                {
                    "doc_id": str(se["id"]),
                    "doc_type": "source_embedding",
                    "parent_id": str(se.get("source_id", "")),
                    "title": se.get("source_title") or "",
                    "content": se.get("content", ""),
                    "embedding": se["embedding"],
                    "owner": se.get("owner"),
                    "chunk_order": se.get("order"),
                }
            )

        for ins in insights:
            if not ins.get("embedding"):
                continue
            source_title = ins.get("source_title") or ""
            insight_type = ins.get("insight_type", "")
            docs.append(
                {
                    "doc_id": str(ins["id"]),
                    "doc_type": "source_insight",
                    "parent_id": str(ins.get("source_id", "")),
                    "title": f"{insight_type} - {source_title}",
                    "content": ins.get("content", ""),
                    "embedding": ins["embedding"],
                    "owner": ins.get("owner"),
                    "insight_type": insight_type,
                }
            )

        for note in notes:
            if not note.get("embedding"):
                continue
            docs.append(
                {
                    "doc_id": str(note["id"]),
                    "doc_type": "note",
                    "parent_id": str(note["id"]),
                    "title": note.get("title") or "",
                    "content": note.get("content") or "",
                    "embedding": note["embedding"],
                    "owner": note.get("owner"),
                }
            )

        total_docs = len(docs)
        logger.info(f"Total documents to index: {total_docs}")

        if total_docs == 0:
            processing_time = time.time() - start_time
            return ReindexOpenSearchOutput(
                success=True,
                processing_time=processing_time,
            )

        # 6. Bulk index
        logger.info("Bulk indexing into OpenSearch...")
        indexed = await bulk_index(docs)
        logger.info(f"Indexed {indexed}/{total_docs} documents")

        # 7. Refresh
        await refresh_index()

        processing_time = time.time() - start_time

        logger.info("=" * 60)
        logger.info("REINDEX COMPLETE")
        logger.info(f"  Source embeddings: {len(source_embeddings)}")
        logger.info(f"  Source insights:   {len(insights)}")
        logger.info(f"  Notes:             {len(notes)}")
        logger.info(f"  Total indexed:     {indexed}")
        logger.info(f"  Time:              {processing_time:.2f}s")
        logger.info("=" * 60)

        return ReindexOpenSearchOutput(
            success=True,
            source_embeddings_indexed=len(source_embeddings),
            insights_indexed=len(insights),
            notes_indexed=len(notes),
            total_indexed=indexed,
            processing_time=processing_time,
        )

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"OpenSearch reindex failed: {e}")
        logger.exception(e)

        return ReindexOpenSearchOutput(
            success=False,
            processing_time=processing_time,
            error_message=str(e),
        )
