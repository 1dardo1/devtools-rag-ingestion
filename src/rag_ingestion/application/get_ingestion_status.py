"""Answering "what happened to my document?" without handing out the document."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.ports import DocumentRepository


@dataclass(frozen=True, slots=True)
class IngestionStatus:
    """What a caller is told about a document it submitted.

    **Not the `Document` itself, and the difference is not ceremony.** The
    entity carries `start_processing`, `mark_indexed` and `mark_failed`, and
    its own docstring admits that code assigning to `status` directly is
    bypassing the rules and that "review is what catches that". Handing the
    entity to the HTTP layer would put those three methods one attribute
    access away from a request handler. This is frozen and has no methods, so
    the same mistake stops compiling.

    It carries less than the entity on purpose. `content_hash` and
    `size_in_bytes` are what the service deduplicates and limits by, not what
    a caller asked about; they can be added when something needs them rather
    than because the entity happens to have them.

    `ingested_at` is the reason this is worth returning at all. "Pending" on
    its own is barely an answer; "pending, received at 09:15" is one.
    """

    document_id: DocumentId
    collection_id: CollectionId
    status: DocumentStatus
    ingested_at: datetime

    @classmethod
    def of(cls, document: Document) -> Self:
        """Describe a document without exposing it."""
        return cls(
            document_id=document.document_id,
            collection_id=document.collection_id,
            status=document.status,
            ingested_at=document.ingested_at,
        )


@dataclass(frozen=True, slots=True)
class GetIngestionStatus:
    """Report on a document the service was asked to take.

    It reads no clock. The instant it reports was stamped when the document
    was accepted, so asking twice gives the same answer — see ADR 0009.

    It takes one collaborator, and that is the whole point of the unit: the
    read path needs nothing but the repository, which is worth knowing before
    Phase 4 builds one.
    """

    documents: DocumentRepository

    def execute(self, document_id: DocumentId) -> IngestionStatus | None:
        """Describe a document, or `None` when there is no such document.

        `None` rather than an error, matching `DocumentRepository.get`. The
        distinction against `IngestDocument`, which raises
        `CollectionNotFoundError`, is deliberate: writing into a collection
        that does not exist is a caller mistake, while asking after a document
        that does not exist is a query with an empty result. The HTTP layer in
        4.4 is where an empty result becomes a 404 — a status code is not a
        domain concern.
        """
        document = self.documents.get(document_id)
        return None if document is None else IngestionStatus.of(document)
