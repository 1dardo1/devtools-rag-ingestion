"""The three checks between a submission and a stored document."""

import pytest

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.errors import (
    CollectionFullError,
    DocumentTooLargeError,
    DomainError,
    DuplicateDocumentError,
    InvalidLimitError,
)
from rag_ingestion.domain.ingestion_policy import IngestionPolicy
from rag_ingestion.domain.limits import IngestionLimits

SMALL = IngestionLimits(max_document_size_in_bytes=100, max_documents_per_collection=3)


def test_a_document_at_the_size_limit_is_accepted() -> None:
    IngestionPolicy(limits=SMALL).ensure_document_fits(100)


def test_a_document_over_the_size_limit_is_refused() -> None:
    with pytest.raises(DocumentTooLargeError):
        IngestionPolicy(limits=SMALL).ensure_document_fits(101)


def test_an_empty_document_passes_the_size_check() -> None:
    """Zero is within the ceiling; a floor is a separate decision nobody has made."""
    IngestionPolicy(limits=SMALL).ensure_document_fits(0)


def test_a_collection_below_its_ceiling_has_room() -> None:
    IngestionPolicy(limits=SMALL).ensure_collection_has_room(2)


def test_a_collection_at_its_ceiling_has_no_room() -> None:
    """Three documents with a limit of three means the next one does not fit."""
    with pytest.raises(CollectionFullError):
        IngestionPolicy(limits=SMALL).ensure_collection_has_room(3)


def test_content_the_collection_does_not_hold_is_new() -> None:
    IngestionPolicy().ensure_content_is_new(
        ContentHash.of(b"uv workspaces"),
        CollectionId.generate(),
        already_present=False,
    )


def test_content_the_collection_already_holds_is_refused() -> None:
    with pytest.raises(DuplicateDocumentError):
        IngestionPolicy().ensure_content_is_new(
            ContentHash.of(b"uv workspaces"),
            CollectionId.generate(),
            already_present=True,
        )


def test_the_duplicate_refusal_names_the_collection() -> None:
    collection_id = CollectionId.generate()

    with pytest.raises(DuplicateDocumentError, match=str(collection_id)):
        IngestionPolicy().ensure_content_is_new(
            ContentHash.of(b"anything"), collection_id, already_present=True
        )


def test_a_policy_without_explicit_limits_uses_the_defaults() -> None:
    policy = IngestionPolicy()

    assert policy.limits == IngestionLimits()


def test_the_default_limits_admit_an_ordinary_documentation_page() -> None:
    IngestionPolicy().ensure_document_fits(50_000)
    IngestionPolicy().ensure_collection_has_room(0)


@pytest.mark.parametrize("size", [0, -1], ids=["zero", "negative"])
def test_a_size_limit_that_admits_nothing_is_refused(size: int) -> None:
    with pytest.raises(InvalidLimitError, match="max_document_size_in_bytes"):
        IngestionLimits(max_document_size_in_bytes=size)


@pytest.mark.parametrize("count", [0, -1], ids=["zero", "negative"])
def test_a_count_limit_that_admits_nothing_is_refused(count: int) -> None:
    with pytest.raises(InvalidLimitError, match="max_documents_per_collection"):
        IngestionLimits(max_documents_per_collection=count)


def test_limit_refusals_are_domain_errors() -> None:
    with pytest.raises(DomainError):
        IngestionLimits(max_document_size_in_bytes=0)
