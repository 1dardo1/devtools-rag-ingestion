"""The ports are shapes, and the type checker is what verifies them.

These tests are unusual: most of their value is realised when `mypy` reads
them, not when `pytest` runs them. Assigning a fake to a variable annotated
with the port is the assertion — it fails the type check if the fake and the
port have drifted apart, without anything being executed.

This is the mechanism ADR 0005 gave as the reason for checking `tests/` as
well as `src/`. Under structural typing nothing declares that a fake
implements a port, so a checker pointed only at `src/` would never notice a
double that has quietly stopped matching. This file is the first place that
argument is cashed in.
"""

from datetime import UTC, datetime

from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.events import DocumentIngested
from rag_ingestion.domain.metadata import Metadata
from rag_ingestion.domain.ports import (
    Clock,
    CollectionRepository,
    DocumentRepository,
    EventPublisher,
)


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[DocumentId, Document] = {}

    def add(self, document: Document) -> None:
        self.documents[document.document_id] = document

    def get(self, document_id: DocumentId) -> Document | None:
        return self.documents.get(document_id)

    def exists_with_content_hash(
        self, collection_id: CollectionId, content_hash: ContentHash
    ) -> bool:
        return any(
            document.collection_id == collection_id
            and document.content_hash == content_hash
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


class FixedClock:
    """The whole point of the port: a test can name the instant it expects."""

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DocumentIngested] = []

    def publish(self, event: DocumentIngested) -> None:
        self.published.append(event)


def test_the_in_memory_document_repository_satisfies_the_port() -> None:
    """The annotation is the assertion; `mypy` is what checks it."""
    repository: DocumentRepository = InMemoryDocumentRepository()

    assert repository.get(DocumentId.generate()) is None


def test_the_in_memory_collection_repository_satisfies_the_port() -> None:
    repository: CollectionRepository = InMemoryCollectionRepository()

    assert repository.get(CollectionId.generate()) is None


def test_the_recording_publisher_satisfies_the_port() -> None:
    publisher: EventPublisher = RecordingEventPublisher()

    assert publisher.publish is not None


def test_the_fixed_clock_satisfies_the_port() -> None:
    clock: Clock = FixedClock(datetime(2026, 8, 30, 9, 15, tzinfo=UTC))

    assert clock.now() == datetime(2026, 8, 30, 9, 15, tzinfo=UTC)


def test_a_fixed_clock_does_not_move() -> None:
    """Determinism is the reason this port exists at all."""
    clock = FixedClock(datetime(2026, 8, 30, 9, 15, tzinfo=UTC))

    assert clock.now() == clock.now()


def test_a_missing_document_is_reported_as_absent_rather_than_raising() -> None:
    """A status lookup that finds nothing is an ordinary outcome, not an error."""
    repository: DocumentRepository = InMemoryDocumentRepository()

    assert repository.get(DocumentId.generate()) is None


def test_a_collection_counts_only_its_own_documents() -> None:
    repository = InMemoryDocumentRepository()
    mine = CollectionId.generate()
    theirs = CollectionId.generate()
    repository.add(a_document(collection_id=mine))
    repository.add(a_document(collection_id=mine))
    repository.add(a_document(collection_id=theirs))

    assert repository.count_in_collection(mine) == 2


def test_content_present_in_another_collection_does_not_count_as_present() -> None:
    """Deduplication is scoped to the collection; collections must not leak."""
    repository = InMemoryDocumentRepository()
    content = ContentHash.of(b"shared page")
    repository.add(a_document(collection_id=CollectionId.generate(), content=content))

    assert not repository.exists_with_content_hash(CollectionId.generate(), content)


def a_document(
    collection_id: CollectionId, content: ContentHash | None = None
) -> Document:
    return Document(
        document_id=DocumentId.generate(),
        collection_id=collection_id,
        content_hash=content or ContentHash.of(b"pytest parametrize"),
        size_in_bytes=18,
        metadata=Metadata(source_library="pytest", doc_type=DocType.HOW_TO),
    )
