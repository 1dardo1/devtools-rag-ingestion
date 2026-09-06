"""A document that has been accepted into a collection."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.errors import (
    IllegalStatusTransitionError,
    NaiveTimestampError,
    NegativeDocumentSizeError,
)
from rag_ingestion.domain.metadata import Metadata

_INGESTED_AT = "ingested_at"

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

    `ingested_at` is the moment this service took responsibility, not the
    moment the document was written anywhere. It is supplied rather than read:
    the domain owns no clock, so the use case reads the `Clock` port once and
    passes the same instant here and to `DocumentIngested`, which makes the
    record and the announcement agree by construction rather than by luck.

    No rule reads it, and it earns its place anyway — for the same reason
    `metadata` does. Both carry what a caller needs to be told, and 2.3
    `GetIngestionStatus` cannot answer "when" from a status enum alone. ADR
    0009 records this and the rest of how time enters the service.
    """

    document_id: DocumentId
    collection_id: CollectionId
    content_hash: ContentHash
    size_in_bytes: int
    metadata: Metadata
    ingested_at: datetime
    status: DocumentStatus = field(default=DocumentStatus.PENDING)

    def __post_init__(self) -> None:
        if self.size_in_bytes < 0:
            raise NegativeDocumentSizeError(self.size_in_bytes)
        if self.ingested_at.tzinfo is None:
            raise NaiveTimestampError(_INGESTED_AT)

    def start_processing(self) -> None:
        """Record that the retrieval service has picked this document up."""
        self._transition_to(DocumentStatus.PROCESSING)

    def mark_indexed(self) -> None:
        """Record that indexing succeeded and the document is answerable."""
        self._transition_to(DocumentStatus.INDEXED)

    def mark_failed(self) -> None:
        """Record that indexing did not succeed.

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
