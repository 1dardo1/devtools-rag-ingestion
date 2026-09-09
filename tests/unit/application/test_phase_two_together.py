"""The three use cases, composed, with no infrastructure present.

`ROADMAP.md` closes Phase 2 when "all three run end to end with no
infrastructure present". Each unit has its own suite proving its own rules;
this one proves they *compose* — that the id 2.2 mints is the one 2.1 accepts,
and the id 2.1 returns is the one 2.3 can answer about. Nothing here re-asserts
a rule a unit test already covers.

It is also the closest thing to Phase 4's composition root that exists yet:
`Service` wires the three use cases over one set of doubles, which is the shape
4.5 will have to produce with real adapters.
"""

from datetime import UTC, datetime

import pytest

from rag_ingestion.application.create_collection import (
    CreateCollection,
    CreateCollectionCommand,
)
from rag_ingestion.application.get_ingestion_status import GetIngestionStatus
from rag_ingestion.application.ingest_document import (
    IngestDocument,
    IngestDocumentCommand,
)
from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.errors import (
    CollectionNotFoundError,
    DuplicateDocumentError,
)
from rag_ingestion.domain.events import DocumentIngested
from rag_ingestion.domain.metadata import Metadata

INGESTED_AT = datetime(2026, 8, 30, 9, 15, tzinfo=UTC)
CONTENT = b"redis streams consumer groups"


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[DocumentId, Document] = {}
        self.content: dict[DocumentId, bytes] = {}

    def add(self, document: Document, content: bytes) -> None:
        self.documents[document.document_id] = document
        self.content[document.document_id] = content

    def get(self, document_id: DocumentId) -> Document | None:
        return self.documents.get(document_id)

    def exists_with_content_hash(
        self, collection_id: CollectionId, content_hash: ContentHash
    ) -> bool:
        return any(
            document.collection_id == collection_id
            and document.content_hash == content_hash
            and document.status is not DocumentStatus.FAILED
            for document in self.documents.values()
        )

    def count_in_collection(self, collection_id: CollectionId) -> int:
        return sum(
            document.collection_id == collection_id
            for document in self.documents.values()
        )


class InMemoryCollectionRepository:
    def __init__(self) -> None:
        self.collections: dict[CollectionId, Collection] = {}

    def add(self, collection: Collection) -> None:
        self.collections[collection.collection_id] = collection

    def get(self, collection_id: CollectionId) -> Collection | None:
        return self.collections.get(collection_id)

    def exists_with_name(self, name: str) -> bool:
        return any(collection.name == name for collection in self.collections.values())


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DocumentIngested] = []

    def publish(self, event: DocumentIngested) -> None:
        self.published.append(event)


class FixedClock:
    def now(self) -> datetime:
        return INGESTED_AT


class Service:
    """The three use cases over one set of doubles, wired as 4.5 will wire them."""

    def __init__(self) -> None:
        self.documents = InMemoryDocumentRepository()
        self.collections = InMemoryCollectionRepository()
        self.events = RecordingEventPublisher()
        self.create_collection = CreateCollection(collections=self.collections)
        self.ingest = IngestDocument(
            documents=self.documents,
            collections=self.collections,
            events=self.events,
            clock=FixedClock(),
        )
        self.status = GetIngestionStatus(documents=self.documents)


def a_command(collection_id: CollectionId, content: bytes) -> IngestDocumentCommand:
    return IngestDocumentCommand(
        collection_id=collection_id,
        content=content,
        metadata=Metadata(source_library="redis", doc_type=DocType.HOW_TO),
    )


def test_a_document_can_be_created_ingested_and_asked_about() -> None:
    """Phase 2's completion criterion, in one test and with no infrastructure."""
    service = Service()

    collection_id = service.create_collection.execute(
        CreateCollectionCommand(name="redis docs")
    )
    document_id = service.ingest.execute(a_command(collection_id, CONTENT))
    status = service.status.execute(document_id)

    assert status is not None
    assert status.collection_id == collection_id
    assert status.status is DocumentStatus.PENDING
    assert status.ingested_at == INGESTED_AT


def test_the_announcement_matches_what_the_status_reports() -> None:
    """The consumer and the caller are told the same thing about the same document."""
    service = Service()
    collection_id = service.create_collection.execute(
        CreateCollectionCommand(name="redis docs")
    )

    document_id = service.ingest.execute(a_command(collection_id, CONTENT))

    event = service.events.published[0]
    status = service.status.execute(document_id)
    assert status is not None
    assert (event.document_id, event.collection_id, event.occurred_at) == (
        status.document_id,
        status.collection_id,
        status.ingested_at,
    )


def test_a_collection_2_2_never_made_is_not_a_place_to_ingest() -> None:
    """2.1 trusts 2.2 for the boundary; an unminted id is not one."""
    service = Service()

    with pytest.raises(CollectionNotFoundError):
        service.ingest.execute(a_command(CollectionId.generate(), CONTENT))


def test_deduplication_is_scoped_to_the_collection_2_2_made() -> None:
    """The same page may live in two collections; it may not live twice in one."""
    service = Service()
    mine = service.create_collection.execute(CreateCollectionCommand(name="mine"))
    theirs = service.create_collection.execute(CreateCollectionCommand(name="theirs"))
    service.ingest.execute(a_command(mine, CONTENT))

    service.ingest.execute(a_command(theirs, CONTENT))

    with pytest.raises(DuplicateDocumentError):
        service.ingest.execute(a_command(mine, CONTENT))


def test_a_document_moved_on_is_reported_where_it_now_is() -> None:
    """2.3 reads live state, not a copy taken at ingestion."""
    service = Service()
    collection_id = service.create_collection.execute(
        CreateCollectionCommand(name="redis docs")
    )
    document_id = service.ingest.execute(a_command(collection_id, CONTENT))

    stored = service.documents.get(document_id)
    assert stored is not None
    stored.start_processing()
    stored.mark_indexed()

    status = service.status.execute(document_id)
    assert status is not None
    assert status.status is DocumentStatus.INDEXED
    assert status.ingested_at == INGESTED_AT


def test_nothing_in_the_three_use_cases_touches_infrastructure() -> None:
    """The completion criterion, asserted rather than asserted about.

    Every collaborator above is a plain object defined in this file. If any use
    case reached for a database, a broker or the system clock, it would have to
    import one — and `Service` supplies none.
    """
    service = Service()
    collection_id = service.create_collection.execute(
        CreateCollectionCommand(name="uv docs")
    )
    service.ingest.execute(a_command(collection_id, CONTENT))

    assert len(service.collections.collections) == 1
    assert len(service.documents.documents) == 1
    assert len(service.documents.content) == 1
    assert len(service.events.published) == 1


def test_a_document_that_failed_can_be_submitted_again() -> None:
    """`Document.mark_failed` says recovery is resubmission. This is that.

    Before the deduplication question learned to ignore failures, the failed
    attempt counted as a duplicate of itself and the content could never be
    ingested into that collection again without deleting a row by hand.
    """
    service = Service()
    collection_id = service.create_collection.execute(
        CreateCollectionCommand(name="redis docs")
    )
    first = service.ingest.execute(a_command(collection_id, CONTENT))
    stored = service.documents.get(first)
    assert stored is not None
    stored.start_processing()
    stored.mark_failed()

    second = service.ingest.execute(a_command(collection_id, CONTENT))

    assert second != first
    status = service.status.execute(second)
    assert status is not None
    assert status.status is DocumentStatus.PENDING


def test_the_failed_attempt_is_still_there_to_be_asked_about() -> None:
    """Resubmission does not erase the evidence that the first try failed."""
    service = Service()
    collection_id = service.create_collection.execute(
        CreateCollectionCommand(name="redis docs")
    )
    first = service.ingest.execute(a_command(collection_id, CONTENT))
    stored = service.documents.get(first)
    assert stored is not None
    stored.start_processing()
    stored.mark_failed()

    service.ingest.execute(a_command(collection_id, CONTENT))

    failed_status = service.status.execute(first)
    assert failed_status is not None
    assert failed_status.status is DocumentStatus.FAILED
