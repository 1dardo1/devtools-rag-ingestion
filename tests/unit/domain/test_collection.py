"""A collection is identified by who it is, not by what it is called."""

import pytest

from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.errors import (
    DomainError,
    InvalidCollectionIdError,
    MissingCollectionNameError,
)


def test_a_collection_keeps_its_name() -> None:
    assert Collection(collection_id=CollectionId.generate(), name="fastapi").name == (
        "fastapi"
    )


def test_renaming_a_collection_does_not_make_it_a_different_collection() -> None:
    collection = Collection(collection_id=CollectionId.generate(), name="fastapi")
    same = Collection(collection_id=collection.collection_id, name="FastAPI docs")

    assert collection == same


def test_two_collections_with_different_identities_differ() -> None:
    one = Collection(collection_id=CollectionId.generate(), name="shared")
    other = Collection(collection_id=CollectionId.generate(), name="shared")

    assert one != other


def test_a_collection_is_not_equal_to_something_that_is_not_a_collection() -> None:
    assert Collection(collection_id=CollectionId.generate(), name="x") != "x"


def test_a_collection_keeps_its_place_in_a_set_when_renamed() -> None:
    collection = Collection(collection_id=CollectionId.generate(), name="before")
    collections = {collection}

    collection.name = "after"

    assert collection in collections


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="spaces only"),
        pytest.param("\t\n", id="whitespace only"),
    ],
)
def test_a_collection_must_have_a_name(name: str) -> None:
    with pytest.raises(MissingCollectionNameError):
        Collection(collection_id=CollectionId.generate(), name=name)


def test_surrounding_whitespace_is_stripped_from_the_name() -> None:
    collection = Collection(collection_id=CollectionId.generate(), name="  pytest  ")

    assert collection.name == "pytest"


def test_an_identity_survives_a_round_trip_through_text() -> None:
    original = CollectionId.generate()

    assert CollectionId.parse(str(original)) == original


def test_generated_collection_identities_are_unique() -> None:
    assert len({CollectionId.generate() for _ in range(1000)}) == 1000


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("not-a-uuid", id="arbitrary text"),
        pytest.param("3fa85f64-5717-4562-b3fc-2c963f66afa", id="one character short"),
    ],
)
def test_text_that_is_not_a_collection_identity_is_rejected(value: str) -> None:
    with pytest.raises(InvalidCollectionIdError):
        CollectionId.parse(value)


def test_a_collection_identity_is_not_a_document_identity() -> None:
    """Distinct types are the point: one cannot stand in for the other.

    The stronger half of this guarantee is static, and cannot be written as a
    runtime assertion: `CollectionId(u) != DocumentId(u)` is rejected by
    `mypy` as a non-overlapping comparison, which is the check actually
    protecting callers. What is asserted here is the runtime half — that two
    different types wrapping the same UUID are not equal — reached through a
    variable typed as `object` so the type checker permits the comparison.
    """
    shared_uuid = CollectionId.generate().value
    collection_id: object = CollectionId(shared_uuid)

    assert collection_id != DocumentId(shared_uuid)


def test_rejections_are_domain_errors() -> None:
    with pytest.raises(DomainError):
        Collection(collection_id=CollectionId.generate(), name="")
