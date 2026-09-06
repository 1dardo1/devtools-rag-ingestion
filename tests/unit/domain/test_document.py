"""A document is the same document however much of it changes."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.errors import (
    DomainError,
    NaiveTimestampError,
    NegativeDocumentSizeError,
)
from rag_ingestion.domain.metadata import Metadata

INGESTED_AT = datetime(2026, 8, 30, 9, 15, tzinfo=UTC)


def a_document(
    document_id: DocumentId | None = None,
    collection_id: CollectionId | None = None,
    content: bytes = b"FastAPI dependency injection",
    size_in_bytes: int = 28,
    ingested_at: datetime | None = None,
) -> Document:
    return Document(
        document_id=document_id or DocumentId.generate(),
        collection_id=collection_id or CollectionId.generate(),
        content_hash=ContentHash.of(content),
        size_in_bytes=size_in_bytes,
        metadata=Metadata(source_library="fastapi", doc_type=DocType.API_REFERENCE),
        ingested_at=ingested_at or INGESTED_AT,
    )


def test_a_new_document_is_pending() -> None:
    assert a_document().status is DocumentStatus.PENDING


def test_two_documents_with_the_same_identity_are_the_same_document() -> None:
    shared_id = DocumentId.generate()

    one = a_document(document_id=shared_id, content=b"before")
    other = a_document(document_id=shared_id, content=b"after", size_in_bytes=5)
    other.start_processing()
    other.mark_indexed()

    assert one == other


def test_two_documents_with_different_identities_differ() -> None:
    assert a_document() != a_document()


def test_identical_content_does_not_make_two_documents_the_same() -> None:
    """Deduplication is a rule applied before creation, not an identity claim."""
    one = a_document(content=b"same bytes")
    other = a_document(content=b"same bytes")

    assert one.content_hash == other.content_hash
    assert one != other


def test_a_document_is_not_equal_to_something_that_is_not_a_document() -> None:
    assert a_document() != "not a document"


def test_a_document_keeps_its_place_in_a_set_when_its_status_changes() -> None:
    document = a_document()
    documents = {document}

    document.start_processing()
    document.mark_indexed()

    assert document in documents


def test_a_document_may_be_empty_here() -> None:
    """Whether an empty document is acceptable is a size limit, and is unit 1.3."""
    assert a_document(content=b"", size_in_bytes=0).size_in_bytes == 0


@pytest.mark.parametrize(
    "size_in_bytes",
    [pytest.param(-1, id="minus one"), pytest.param(-4096, id="large negative")],
)
def test_a_document_cannot_occupy_fewer_than_zero_bytes(size_in_bytes: int) -> None:
    with pytest.raises(NegativeDocumentSizeError):
        a_document(size_in_bytes=size_in_bytes)


def test_the_rejection_is_a_domain_error() -> None:
    with pytest.raises(DomainError):
        a_document(size_in_bytes=-1)


def test_a_document_remembers_when_it_was_ingested() -> None:
    """2.3 `GetIngestionStatus` answers "when", and this is where it reads it."""
    assert a_document().ingested_at == INGESTED_AT


def test_a_naive_ingestion_instant_is_refused() -> None:
    """A timestamp without a timezone is ambiguous the moment it is stored."""
    with pytest.raises(NaiveTimestampError, match="ingested_at"):
        a_document(ingested_at=datetime(2026, 8, 30, 9, 15))  # noqa: DTZ001


def test_the_naive_instant_refusal_is_a_domain_error() -> None:
    with pytest.raises(DomainError):
        a_document(ingested_at=datetime(2026, 8, 30, 9, 15))  # noqa: DTZ001


def test_a_non_utc_instant_is_accepted() -> None:
    """The rule is that an instant carries a zone, not that the zone is UTC."""
    madrid = datetime(2026, 8, 30, 11, 15, tzinfo=timezone(timedelta(hours=2)))

    assert a_document(ingested_at=madrid).ingested_at == INGESTED_AT


def test_moving_a_document_on_does_not_change_when_it_was_ingested() -> None:
    """Ingestion happened once; indexing later does not rewrite that fact."""
    document = a_document()

    document.start_processing()
    document.mark_indexed()

    assert document.ingested_at == INGESTED_AT
