"""2.3 against a fake repository, with no infrastructure present."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from rag_ingestion.application.get_ingestion_status import (
    GetIngestionStatus,
    IngestionStatus,
)
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.metadata import Metadata

INGESTED_AT = datetime(2026, 8, 30, 9, 15, tzinfo=UTC)


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
            for document in self.documents.values()
        )

    def count_in_collection(self, collection_id: CollectionId) -> int:
        return sum(
            document.collection_id == collection_id
            for document in self.documents.values()
        )


def a_document() -> Document:
    return Document(
        document_id=DocumentId.generate(),
        collection_id=CollectionId.generate(),
        content_hash=ContentHash.of(b"pydantic model config"),
        size_in_bytes=21,
        metadata=Metadata(source_library="pydantic", doc_type=DocType.REFERENCE),
        ingested_at=INGESTED_AT,
    )


def a_use_case(
    repository: InMemoryDocumentRepository,
) -> GetIngestionStatus:
    return GetIngestionStatus(documents=repository)


def test_a_stored_document_is_described() -> None:
    repository = InMemoryDocumentRepository()
    document = a_document()
    repository.add(document, b"pydantic model config")

    status = a_use_case(repository).execute(document.document_id)

    assert status == IngestionStatus(
        document_id=document.document_id,
        collection_id=document.collection_id,
        status=DocumentStatus.PENDING,
        ingested_at=INGESTED_AT,
    )


def test_a_document_the_service_never_took_is_reported_as_absent() -> None:
    """`None`, not an error: an empty result is an ordinary query outcome."""
    repository = InMemoryDocumentRepository()

    assert a_use_case(repository).execute(DocumentId.generate()) is None


def test_the_reported_instant_is_the_one_stamped_at_ingestion() -> None:
    """No clock is read here, so the answer does not move between calls."""
    repository = InMemoryDocumentRepository()
    document = a_document()
    repository.add(document, b"pydantic model config")
    use_case = a_use_case(repository)

    first = use_case.execute(document.document_id)
    second = use_case.execute(document.document_id)

    assert first == second
    assert first is not None
    assert first.ingested_at == INGESTED_AT


def test_the_report_follows_the_document_through_its_statuses() -> None:
    repository = InMemoryDocumentRepository()
    document = a_document()
    repository.add(document, b"pydantic model config")
    document.start_processing()

    status = a_use_case(repository).execute(document.document_id)

    assert status is not None
    assert status.status is DocumentStatus.PROCESSING


def test_a_failed_document_is_reported_as_failed() -> None:
    repository = InMemoryDocumentRepository()
    document = a_document()
    repository.add(document, b"pydantic model config")
    document.start_processing()
    document.mark_failed()

    status = a_use_case(repository).execute(document.document_id)

    assert status is not None
    assert status.status is DocumentStatus.FAILED


def test_the_report_cannot_move_the_document_on() -> None:
    """The entity's three transitions must not reach a request handler."""
    repository = InMemoryDocumentRepository()
    document = a_document()
    repository.add(document, b"pydantic model config")

    status = a_use_case(repository).execute(document.document_id)

    assert not hasattr(status, "start_processing")
    assert not hasattr(status, "mark_indexed")
    assert not hasattr(status, "mark_failed")


def test_the_report_cannot_be_edited() -> None:
    repository = InMemoryDocumentRepository()
    document = a_document()
    repository.add(document, b"pydantic model config")

    status = a_use_case(repository).execute(document.document_id)

    assert status is not None
    with pytest.raises(FrozenInstanceError):
        # Deliberately breaking the frozen contract: the assignment is the
        # behaviour under test, so mypy is right to object and is silenced.
        status.status = DocumentStatus.INDEXED  # type: ignore[misc]


def test_the_report_does_not_carry_what_a_caller_did_not_ask_about() -> None:
    """Deduplication and limits are the service's business, not the caller's."""
    repository = InMemoryDocumentRepository()
    document = a_document()
    repository.add(document, b"pydantic model config")

    status = a_use_case(repository).execute(document.document_id)

    assert not hasattr(status, "content_hash")
    assert not hasattr(status, "size_in_bytes")


def test_two_documents_are_reported_apart() -> None:
    repository = InMemoryDocumentRepository()
    mine, theirs = a_document(), a_document()
    repository.add(mine, b"mine")
    repository.add(theirs, b"theirs")
    use_case = a_use_case(repository)

    reported = use_case.execute(mine.document_id)

    assert reported is not None
    assert reported.document_id == mine.document_id
    assert reported.document_id != theirs.document_id
