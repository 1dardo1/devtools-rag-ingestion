"""A document that has been accepted into a collection."""

from dataclasses import dataclass, field

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.errors import NegativeDocumentSizeError
from rag_ingestion.domain.metadata import Metadata


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

    Transitions between statuses are not defined here. Which moves are allowed
    is a rule, and rules are unit 1.3; this unit fixes the shape a rule will
    later operate on.
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

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return NotImplemented
        return self.document_id == other.document_id

    def __hash__(self) -> int:
        return hash(self.document_id)
