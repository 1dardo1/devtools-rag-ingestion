"""Accepting a document: three checks, one record, one announcement."""

from dataclasses import dataclass, field

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.errors import CollectionNotFoundError
from rag_ingestion.domain.events import DocumentIngested
from rag_ingestion.domain.ingestion_policy import IngestionPolicy
from rag_ingestion.domain.metadata import Metadata
from rag_ingestion.domain.ports import (
    Clock,
    CollectionRepository,
    DocumentRepository,
    EventPublisher,
)


@dataclass(frozen=True, slots=True)
class IngestDocumentCommand:
    """What a caller must supply to submit a document.

    The content arrives as bytes rather than as a hash and a size. The use case
    derives both, so a caller cannot claim a fingerprint that does not match
    what it sent — which matters because deduplication trusts that fingerprint.
    """

    collection_id: CollectionId
    content: bytes
    metadata: Metadata


@dataclass(frozen=True, slots=True)
class IngestDocument:
    """Run the ingestion rules, store the document, announce that it arrived.

    Everything it touches is a port, so the whole use case runs against
    in-memory fakes with no infrastructure present — which is what `ROADMAP.md`
    2.1 asks for, and the point of proving the port shapes before Phase 4
    commits to a technology.

    It is synchronous, per ADR 0007.
    """

    documents: DocumentRepository
    collections: CollectionRepository
    events: EventPublisher
    clock: Clock
    policy: IngestionPolicy = field(default_factory=IngestionPolicy)

    def execute(self, command: IngestDocumentCommand) -> DocumentId:
        """Accept a document, or raise a `DomainError` explaining why not.

        The checks run cheapest first: size needs nothing, the room check costs
        one query, and the duplicate check costs another. A submission that is
        too large is refused without touching the database at all.

        The document is stored before the event is published. The order is not
        an implementation detail — the outbox depends on it. An announcement
        about a document that was never written is exactly the inconsistency
        `EventPublisher`'s Phase 4 implementation exists to make impossible,
        and it binds both writes to one transaction.
        """
        if self.collections.get(command.collection_id) is None:
            raise CollectionNotFoundError(str(command.collection_id))

        content_hash = ContentHash.of(command.content)
        size_in_bytes = len(command.content)

        self.policy.ensure_document_fits(size_in_bytes)
        self.policy.ensure_collection_has_room(
            self.documents.count_in_collection(command.collection_id)
        )
        self.policy.ensure_content_is_new(
            content_hash,
            command.collection_id,
            already_present=self.documents.exists_with_content_hash(
                command.collection_id, content_hash
            ),
        )

        document = Document(
            document_id=DocumentId.generate(),
            collection_id=command.collection_id,
            content_hash=content_hash,
            size_in_bytes=size_in_bytes,
            metadata=command.metadata,
            ingested_at=self.clock.now(),
        )
        self.documents.add(document, command.content)
        self.events.publish(DocumentIngested.about(document))
        return document.document_id
