"""A document that has been accepted into a collection."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.errors import (
    IllegalStatusTransitionError,
    NegativeDocumentSizeError,
)
from rag_ingestion.domain.metadata import Metadata

_ALLOWED_TRANSITIONS: Final[Mapping[DocumentStatus, frozenset[DocumentStatus]]] = {
    DocumentStatus.PENDING: frozenset({DocumentStatus.PROCESSING}),
    DocumentStatus.PROCESSING: frozenset(
        {DocumentStatus.INDEXED, DocumentStatus.FAILED}
    ),
    DocumentStatus.INDEXED: frozenset(),
    DocumentStatus.FAILED: frozenset(),
}


@dataclass(eq=False, slots=True)
class Document:
    """A document the service has taken responsibility for.

    An entity, not a value object: it has an identity that outlives any of its
    attributes, and two documents are the same document when their identities
    match, whatever else differs. That is why equality and hashing are defined
    on `document_id` alone — a document whose status has moved on is still the
    same document, and a set or dictionary must agree.

    **It does not hold the content.** Only the fingerprint and the size. The
    domain never needs to read the bytes: it deduplicates by hash and enforces
    limits by size. Keeping megabytes inside an entity that is copied,
    compared and passed between layers would cost memory for no decision it
    enables. The bytes are the adapter's business, in Phase 4.

    A document moves through its statuses only by the three methods below.
    `status` remains an ordinary field so that a repository can rebuild a
    stored document in whatever state it was left in; business logic that
    assigns to it directly is bypassing the rules, and review is what catches
    that.
    """

    document_id: DocumentId
    collection_id: CollectionId
    content_hash: ContentHash
    size_in_bytes: int
    metadata: Metadata
    status: DocumentStatus = field(default=DocumentStatus.PENDING)

    def __post_init__(self) -> None:
        if self.size_in_bytes < 0:
            raise NegativeDocumentSizeError(self.size_in_bytes)

    def start_processing(self) -> None:
        """The retrieval service has picked this document up."""
        self._transition_to(DocumentStatus.PROCESSING)

    def mark_indexed(self) -> None:
        """Indexing succeeded and the document is answerable."""
        self._transition_to(DocumentStatus.INDEXED)

    def mark_failed(self) -> None:
        """Indexing did not succeed.

        Terminal, matching the state machine `ARCHITECTURE.md` fixes. A failed
        document is recovered by submitting it again, not by reviving this one:
        a retry path would need a retry count and a give-up rule to avoid
        looping forever, and neither has been decided.
        """
        self._transition_to(DocumentStatus.FAILED)

    def _transition_to(self, target: DocumentStatus) -> None:
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise IllegalStatusTransitionError(self.status, target)
        self.status = target

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return NotImplemented
        return self.document_id == other.document_id

    def __hash__(self) -> int:
        return hash(self.document_id)
