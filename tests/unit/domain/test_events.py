"""An event is a fact: fixed, and carrying only what a consumer needs."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.errors import DomainError, NaiveTimestampError
from rag_ingestion.domain.events import DocumentIngested
from rag_ingestion.domain.metadata import Metadata

AN_INSTANT = datetime(2026, 8, 30, 9, 15, tzinfo=UTC)


def a_document(ingested_at: datetime = AN_INSTANT) -> Document:
    return Document(
        document_id=DocumentId.generate(),
        collection_id=CollectionId.generate(),
        content_hash=ContentHash.of(b"qdrant hybrid search"),
        size_in_bytes=20,
        metadata=Metadata(
            source_library="qdrant",
            doc_type=DocType.EXPLANATION,
            library_version="1.12",
            source_url="https://qdrant.tech/documentation/concepts/hybrid-queries/",
        ),
        ingested_at=ingested_at,
    )


def an_event(occurred_at: datetime) -> DocumentIngested:
    """Build the event directly, bypassing the document that would validate."""
    document = a_document()
    return DocumentIngested(
        document_id=document.document_id,
        collection_id=document.collection_id,
        content_hash=document.content_hash,
        metadata=document.metadata,
        occurred_at=occurred_at,
    )


def test_the_event_describes_the_document_it_is_about() -> None:
    document = a_document()

    event = DocumentIngested.about(document)

    assert event.document_id == document.document_id
    assert event.collection_id == document.collection_id
    assert event.content_hash == document.content_hash
    assert event.metadata == document.metadata
    assert event.occurred_at == AN_INSTANT


def test_the_event_does_not_carry_the_content() -> None:
    """Consumers fetch the bytes by identifier; the broker is not a content store."""
    event = DocumentIngested.about(a_document())

    assert not hasattr(event, "content")


def test_an_event_cannot_be_edited_after_the_fact() -> None:
    event = DocumentIngested.about(a_document())

    with pytest.raises(FrozenInstanceError):
        # Deliberately breaking the frozen contract: the assignment is the
        # behaviour under test, so mypy is right to object and is silenced here.
        event.occurred_at = AN_INSTANT  # type: ignore[misc]


def test_two_events_about_the_same_facts_are_equal() -> None:
    document = a_document()

    assert DocumentIngested.about(document) == DocumentIngested.about(document)


def test_the_event_takes_its_instant_from_the_document() -> None:
    """One value, one source: the record and the announcement cannot disagree."""
    document = a_document()

    assert DocumentIngested.about(document).occurred_at == document.ingested_at


def test_a_naive_timestamp_is_refused() -> None:
    """A timestamp without a timezone is ambiguous the moment it leaves here.

    `about` can no longer produce this, because a `Document` refuses a naive
    instant first. Direct construction is the remaining way in, and is what
    this guard exists for.
    """
    with pytest.raises(NaiveTimestampError, match="occurred_at"):
        an_event(occurred_at=datetime(2026, 8, 30, 9, 15))  # noqa: DTZ001


def test_the_refusal_is_a_domain_error() -> None:
    with pytest.raises(DomainError):
        an_event(occurred_at=datetime(2026, 8, 30))  # noqa: DTZ001


def test_a_timestamp_in_any_timezone_is_accepted() -> None:
    """The domain requires an unambiguous instant, not a particular offset."""
    madrid_summer = datetime(2026, 8, 30, 11, 15, tzinfo=timezone(timedelta(hours=2)))

    event = DocumentIngested.about(a_document(ingested_at=madrid_summer))

    assert event.occurred_at == AN_INSTANT


def test_the_event_carries_the_hash_so_a_repeat_can_be_recognised() -> None:
    """Delivery is at-least-once; the consumer must be able to spot a redelivery."""
    document = a_document()

    event = DocumentIngested.about(document)

    assert (event.document_id, event.content_hash) == (
        document.document_id,
        document.content_hash,
    )
