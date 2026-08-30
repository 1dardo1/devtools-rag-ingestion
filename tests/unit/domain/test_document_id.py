"""A document's identity is minted by the domain and cannot be faked from text."""

import pytest

from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.errors import DomainError, InvalidDocumentIdError


def test_generated_identities_are_unique() -> None:
    identities = {DocumentId.generate() for _ in range(1000)}

    assert len(identities) == 1000


def test_an_identity_survives_a_round_trip_through_text() -> None:
    original = DocumentId.generate()

    assert DocumentId.parse(str(original)) == original


def test_two_identities_with_the_same_value_are_equal() -> None:
    original = DocumentId.generate()

    assert DocumentId(original.value) == original


def test_an_identity_cannot_be_mutated() -> None:
    identity = DocumentId.generate()

    with pytest.raises(AttributeError):
        # Deliberately breaking the frozen contract: the assignment is the
        # behaviour under test, so mypy is right to object and is silenced here.
        identity.value = DocumentId.generate().value  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("not-a-uuid", id="arbitrary text"),
        pytest.param("123", id="digits"),
        pytest.param("3fa85f64-5717-4562-b3fc-2c963f66afa", id="one character short"),
        pytest.param(
            "3fa85f64-5717-4562-b3fc-2c963f66afa6x", id="one character too long"
        ),
        pytest.param(
            "zfa85f64-5717-4562-b3fc-2c963f66afa6", id="non-hexadecimal character"
        ),
    ],
)
def test_text_that_is_not_an_identity_is_rejected(value: str) -> None:
    with pytest.raises(InvalidDocumentIdError):
        DocumentId.parse(value)


def test_the_rejection_is_a_domain_error() -> None:
    with pytest.raises(DomainError):
        DocumentId.parse("not-a-uuid")


def test_the_rejection_names_the_offending_value() -> None:
    with pytest.raises(InvalidDocumentIdError, match="not-a-uuid"):
        DocumentId.parse("not-a-uuid")
