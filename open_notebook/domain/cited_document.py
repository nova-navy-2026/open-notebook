"""
CitedDocument domain model.

Stores fetched navy document records used to render citation cards.
Keyed by (owner, doc_id) for fast per-user lookups.

IMPORTANT: CitedDocument must NEVER be embedded or vectorised to OpenSearch.
ObjectModel.save() has NO embedding hook (embedding is fire-and-forget via
surreal_commands in Note/Source subclasses that override save()); the base
save() here is plain DB persistence only, which is exactly what we want.
"""

from typing import Any, ClassVar, Dict, List, Optional

from open_notebook.database.repository import repo_query
from open_notebook.domain.base import ObjectModel


class CitedDocument(ObjectModel):
    """
    A cached navy document record fetched to render citation UI cards.

    Maps to the ``cited_document`` SurrealDB table (migration 22).
    Never triggers embedding; save() from ObjectModel is sufficient.
    """

    table_name: ClassVar[str] = "cited_document"
    nullable_fields: ClassVar[set] = {
        "owner",
        "document_type",
        "document_status",
        "access_scope",
        "classification_level",
        "creator_department",
        "source",
    }

    doc_id: str
    title: str
    full_text: str
    highlights: List[Dict[str, int]] = []
    segments: List[Dict[str, Any]] = []
    owner: Optional[str] = None
    document_type: Optional[str] = None
    document_status: Optional[str] = None
    access_scope: Optional[str] = None
    classification_level: Optional[int] = None
    creator_department: Optional[str] = None
    source: Optional[str] = None

    @classmethod
    async def get_by_owner_and_doc_id(
        cls, owner: Optional[str], doc_id: str
    ) -> Optional["CitedDocument"]:
        """Return the CitedDocument matching (owner, doc_id), or None.

        DB errors propagate: treating them as "not found" would make
        materialize_citation create a duplicate row for a record that
        actually exists (migration 23 makes the pair UNIQUE, so the
        duplicate would surface as a confusing index violation instead).
        """
        results = await repo_query(
            "SELECT * FROM cited_document "
            "WHERE owner = $owner AND doc_id = $doc_id "
            "LIMIT 1",
            {"owner": owner, "doc_id": doc_id},
        )
        if results:
            return cls(**results[0])
        return None
