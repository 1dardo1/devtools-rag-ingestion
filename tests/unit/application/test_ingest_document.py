"""2.1 end to end against fakes, with no infrastructure present.

The doubles here are not the ones in `test_ports.py`, and deliberately so.
Those exist to prove the fakes still match the ports; these exist to watch
*what the use case did and in what order*, which is the part of 2.1 that the
outbox will later depend on. A shared double would have to serve both and
would do neither well.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

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
    CollectionFullError,
    CollectionNotFoundError,
    DocumentTooLargeError,
    DuplicateDocumentError,
)
from rag_ingestion.domain.events import DocumentIngested
from rag_ingestion.domain.ingestion_policy import IngestionPolicy
from rag_ingestion.domain.limits import IngestionLimits
from rag_ingestion.domain.metadata import Metadata

INGESTED_AT = datetime(2026, 8, 30, 9, 15, tzinfo=UTC)
CONTENT = b"uv workspaces resolve a single lockfile"


@dataclass
class Journal:
    """One shared log, so a test can assert the order across collaborators."""

    entries: list[str] = field(default_factory=list)


class RecordingDocumentRepository:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.documents: dict[DocumentId, Document] = {}
        self.content: dict[DocumentId, bytes] = {}
        self.present_hashes: set[ContentHash] = set()
        self.count = 0

    def add(self, document: Document, content: bytes) -> None:
        self.journal.entries.append("document stored")
        self.documents[document.document_id] = document
        self.content[document.document_id] = content

    def get(self, document_id: DocumentId) -> Document | None:
        return self.documents.get(document_id)

    def exists_with_content_hash(
        self, collection_id: CollectionId, content_hash: ContentHash
    ) -> bool:
        self.journal.entries.append("duplicate checked")
        return content_hash in self.present_hashes

    def count_in_collection(self, collection_id: CollectionId) -> int:
        self.journal.entries.append("collection counted")
        return self.count


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
    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.published: list[DocumentIngested] = []

    def publish(self, event: DocumentIngested) -> None:
        self.journal.entries.append("event published")
        self.published.append(event)


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        self._instant = instant
        self.reads = 0

    def now(self) -> datetime:
        self.reads += 1
        return self._instant


@dataclass
class Fixture:
    use_case: IngestDocument
    documents: RecordingDocumentRepository
    collections: InMemoryCollectionRepository
    events: RecordingEventPublisher
    clock: FixedClock
    journal: Journal
    collection_id: CollectionId


def a_fixture(limits: IngestionLimits | None = None) -> Fixture:
    journal = Journal()
    documents = RecordingDocumentRepository(journal)
    collections = InMemoryCollectionRepository()
    events = RecordingEventPublisher(journal)
    clock = FixedClock(INGESTED_AT)
    collection = Collection(collection_id=CollectionId.generate(), name="uv docs")
    collections.add(collection)
    return Fixture(
        use_case=IngestDocument(
            documents=documents,
            collections=collections,
            events=events,
            clock=clock,
            policy=IngestionPolicy(limits=limits or IngestionLimits()),
        ),
        documents=documents,
        collections=collections,
        events=events,
        clock=clock,
        journal=journal,
        collection_id=collection.collection_id,
    )


def a_command(fixture: Fixture, content: bytes = CONTENT) -> IngestDocumentCommand:
    return IngestDocumentCommand(
        collection_id=fixture.collection_id,
        content=content,
        metadata=Metadata(source_library="uv", doc_type=DocType.HOW_TO),
    )


def test_an_accepted_document_is_stored() -> None:
    fixture = a_fixture()

    document_id = fixture.use_case.execute(a_command(fixture))

    assert fixture.documents.get(document_id) is not None


def test_the_content_is_stored_alongside_the_record() -> None:
    """The entity holds no bytes, so the port is the only way they persist."""
    fixture = a_fixture()

    document_id = fixture.use_case.execute(a_command(fixture))

    assert fixture.documents.content[document_id] == CONTENT


def test_the_stored_document_fingerprints_what_was_actually_sent() -> None:
    """The hash is derived here, so a caller cannot claim one that disagrees."""
    fixture = a_fixture()

    document_id = fixture.use_case.execute(a_command(fixture))

    stored = fixture.documents.get(document_id)
    assert stored is not None
    assert stored.content_hash == ContentHash.of(CONTENT)
    assert stored.size_in_bytes == len(CONTENT)


def test_a_new_document_starts_pending() -> None:
    fixture = a_fixture()

    document_id = fixture.use_case.execute(a_command(fixture))

    stored = fixture.documents.get(document_id)
    assert stored is not None
    assert stored.status is DocumentStatus.PENDING


def test_the_instant_comes_from_the_clock_port() -> None:
    """The whole reason `Clock` is a port: the test names the moment."""
    fixture = a_fixture()

    document_id = fixture.use_case.execute(a_command(fixture))

    stored = fixture.documents.get(document_id)
    assert stored is not None
    assert stored.ingested_at == INGESTED_AT


def test_an_accepted_document_is_announced() -> None:
    fixture = a_fixture()

    document_id = fixture.use_case.execute(a_command(fixture))

    assert [event.document_id for event in fixture.events.published] == [document_id]


def test_the_announcement_carries_the_instant_the_record_carries() -> None:
    """One clock read reaches both, so the two cannot drift apart."""
    fixture = a_fixture()

    fixture.use_case.execute(a_command(fixture))

    assert fixture.events.published[0].occurred_at == INGESTED_AT
    assert fixture.clock.reads == 1


def test_the_document_is_stored_before_it_is_announced() -> None:
    """The outbox depends on this order: never announce an unwritten document."""
    fixture = a_fixture()

    fixture.use_case.execute(a_command(fixture))

    assert fixture.journal.entries[-2:] == ["document stored", "event published"]


def test_a_document_for_an_unknown_collection_is_refused() -> None:
    fixture = a_fixture()
    command = IngestDocumentCommand(
        collection_id=CollectionId.generate(),
        content=CONTENT,
        metadata=Metadata(source_library="uv", doc_type=DocType.HOW_TO),
    )

    with pytest.raises(CollectionNotFoundError):
        fixture.use_case.execute(command)


def test_an_unknown_collection_is_refused_before_anything_is_counted() -> None:
    """Otherwise `count_in_collection` answers zero and every rule passes."""
    fixture = a_fixture()
    command = IngestDocumentCommand(
        collection_id=CollectionId.generate(),
        content=CONTENT,
        metadata=Metadata(source_library="uv", doc_type=DocType.HOW_TO),
    )

    with pytest.raises(CollectionNotFoundError):
        fixture.use_case.execute(command)

    assert fixture.journal.entries == []


def test_an_oversized_document_is_refused() -> None:
    fixture = a_fixture(limits=IngestionLimits(max_document_size_in_bytes=10))

    with pytest.raises(DocumentTooLargeError):
        fixture.use_case.execute(a_command(fixture))


def test_an_oversized_document_is_refused_without_touching_the_repository() -> None:
    """Cheapest check first: a submission too large costs no query."""
    fixture = a_fixture(limits=IngestionLimits(max_document_size_in_bytes=10))

    with pytest.raises(DocumentTooLargeError):
        fixture.use_case.execute(a_command(fixture))

    assert fixture.journal.entries == []


def test_a_full_collection_is_refused() -> None:
    fixture = a_fixture(limits=IngestionLimits(max_documents_per_collection=3))
    fixture.documents.count = 3

    with pytest.raises(CollectionFullError):
        fixture.use_case.execute(a_command(fixture))


def test_content_the_collection_already_holds_is_refused() -> None:
    fixture = a_fixture()
    fixture.documents.present_hashes.add(ContentHash.of(CONTENT))

    with pytest.raises(DuplicateDocumentError):
        fixture.use_case.execute(a_command(fixture))


def test_a_refused_document_is_neither_stored_nor_announced() -> None:
    """A rejection must leave no trace: no row, no event, nothing to undo."""
    fixture = a_fixture()
    fixture.documents.present_hashes.add(ContentHash.of(CONTENT))

    with pytest.raises(DuplicateDocumentError):
        fixture.use_case.execute(a_command(fixture))

    assert fixture.documents.documents == {}
    assert fixture.events.published == []


def test_two_different_documents_both_get_through() -> None:
    """Nothing in the use case carries state between calls."""
    fixture = a_fixture()

    first = fixture.use_case.execute(a_command(fixture, content=b"first page"))
    second = fixture.use_case.execute(a_command(fixture, content=b"second page"))

    assert first != second
    assert len(fixture.events.published) == 2
