"""A document moves forwards through its stages, and only forwards."""

from collections.abc import Callable

import pytest

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.errors import DomainError, IllegalStatusTransitionError
from rag_ingestion.domain.metadata import Metadata


def a_document(status: DocumentStatus = DocumentStatus.PENDING) -> Document:
    return Document(
        document_id=DocumentId.generate(),
        collection_id=CollectionId.generate(),
        content_hash=ContentHash.of(b"redis streams consumer groups"),
        size_in_bytes=29,
        metadata=Metadata(source_library="redis", doc_type=DocType.REFERENCE),
        status=status,
    )


def test_a_pending_document_can_be_picked_up() -> None:
    document = a_document()

    document.start_processing()

    assert document.status is DocumentStatus.PROCESSING


def test_a_document_being_processed_can_be_indexed() -> None:
    document = a_document(status=DocumentStatus.PROCESSING)

    document.mark_indexed()

    assert document.status is DocumentStatus.INDEXED


def test_processing_may_end_in_failure() -> None:
    document = a_document(status=DocumentStatus.PROCESSING)

    document.mark_failed()

    assert document.status is DocumentStatus.FAILED


TRANSITIONS: dict[str, Callable[[Document], None]] = {
    "start_processing": lambda document: document.start_processing(),
    "mark_indexed": lambda document: document.mark_indexed(),
    "mark_failed": lambda document: document.mark_failed(),
}

FORBIDDEN = [
    (DocumentStatus.PENDING, "mark_indexed"),
    (DocumentStatus.PENDING, "mark_failed"),
    (DocumentStatus.PROCESSING, "start_processing"),
    (DocumentStatus.INDEXED, "start_processing"),
    (DocumentStatus.INDEXED, "mark_indexed"),
    (DocumentStatus.INDEXED, "mark_failed"),
    (DocumentStatus.FAILED, "start_processing"),
    (DocumentStatus.FAILED, "mark_indexed"),
    (DocumentStatus.FAILED, "mark_failed"),
]


@pytest.mark.parametrize(
    ("status", "transition"),
    [pytest.param(s, t, id=f"{s.value} cannot {t}") for s, t in FORBIDDEN],
)
def test_every_forbidden_move_is_refused(
    status: DocumentStatus, transition: str
) -> None:
    document = a_document(status=status)

    with pytest.raises(IllegalStatusTransitionError):
        TRANSITIONS[transition](document)

    assert document.status is status, "a refused move must leave the status alone"


def test_indexing_cannot_be_skipped() -> None:
    """A document must be picked up before it can be reported as indexed."""
    document = a_document()

    with pytest.raises(IllegalStatusTransitionError):
        document.mark_indexed()


@pytest.mark.parametrize(
    "terminal", [DocumentStatus.INDEXED, DocumentStatus.FAILED], ids=lambda s: s.value
)
def test_the_terminal_statuses_lead_nowhere(terminal: DocumentStatus) -> None:
    document = a_document(status=terminal)

    for transition in TRANSITIONS.values():
        with pytest.raises(IllegalStatusTransitionError):
            transition(document)


def test_a_failed_document_is_not_revived() -> None:
    """Recovery is a fresh submission, not a transition. See `mark_failed`."""
    document = a_document(status=DocumentStatus.FAILED)

    with pytest.raises(IllegalStatusTransitionError):
        document.start_processing()


def test_the_refusal_is_a_domain_error() -> None:
    with pytest.raises(DomainError):
        a_document().mark_indexed()


def test_the_refusal_names_both_statuses() -> None:
    with pytest.raises(IllegalStatusTransitionError, match=r"pending.*indexed"):
        a_document().mark_indexed()
