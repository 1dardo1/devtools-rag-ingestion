"""A fingerprint is computed here, so equal fingerprints mean equal bytes."""

import hashlib

import pytest

from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.errors import DomainError, InvalidContentHashError


def test_the_same_content_always_produces_the_same_fingerprint() -> None:
    content = b"FastAPI dependency injection"

    assert ContentHash.of(content) == ContentHash.of(content)


def test_different_content_produces_different_fingerprints() -> None:
    assert ContentHash.of(b"Pydantic v1") != ContentHash.of(b"Pydantic v2")


def test_a_single_changed_byte_changes_the_fingerprint() -> None:
    assert ContentHash.of(b"redis streams") != ContentHash.of(b"redis stream")


def test_the_fingerprint_is_a_sha256_digest() -> None:
    content = b"uv sync"

    assert str(ContentHash.of(content)) == hashlib.sha256(content).hexdigest()


def test_empty_content_is_fingerprinted_rather_than_refused() -> None:
    """Whether a document may be empty is a size limit, and belongs to 1.3."""
    assert ContentHash.of(b"") == ContentHash.of(b"")


def test_a_fingerprint_cannot_be_mutated() -> None:
    fingerprint = ContentHash.of(b"pytest fixtures")

    with pytest.raises(AttributeError):
        # Deliberately breaking the frozen contract: the assignment is the
        # behaviour under test, so mypy is right to object and is silenced here.
        fingerprint.value = "0" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("0" * 63, id="one character short"),
        pytest.param("0" * 65, id="one character too long"),
        pytest.param("g" * 64, id="non-hexadecimal characters"),
        pytest.param("A" * 64, id="uppercase hexadecimal"),
        pytest.param(" " + "0" * 63, id="leading space"),
        pytest.param("not a digest at all", id="arbitrary text"),
    ],
)
def test_a_string_that_is_not_a_digest_is_rejected(value: str) -> None:
    with pytest.raises(InvalidContentHashError):
        ContentHash(value)


def test_the_rejection_is_a_domain_error() -> None:
    with pytest.raises(DomainError):
        ContentHash("nonsense")


def test_a_genuine_digest_is_accepted_directly() -> None:
    digest = hashlib.sha256(b"qdrant").hexdigest()

    assert ContentHash(digest).value == digest
