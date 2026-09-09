"""2.2 against a fake repository, with no infrastructure present."""

import pytest

from rag_ingestion.application.create_collection import (
    CreateCollection,
    CreateCollectionCommand,
)
from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.errors import (
    DomainError,
    DuplicateCollectionNameError,
    MissingCollectionNameError,
)


class InMemoryCollectionRepository:
    def __init__(self) -> None:
        self.collections: dict[CollectionId, Collection] = {}

    def add(self, collection: Collection) -> None:
        self.collections[collection.collection_id] = collection

    def get(self, collection_id: CollectionId) -> Collection | None:
        return self.collections.get(collection_id)

    def exists_with_name(self, name: str) -> bool:
        return any(collection.name == name for collection in self.collections.values())


def a_use_case(
    repository: InMemoryCollectionRepository,
) -> CreateCollection:
    return CreateCollection(collections=repository)


def test_a_collection_is_created_under_the_name_requested() -> None:
    repository = InMemoryCollectionRepository()

    collection_id = a_use_case(repository).execute(
        CreateCollectionCommand(name="uv docs")
    )

    stored = repository.get(collection_id)
    assert stored is not None
    assert stored.name == "uv docs"


def test_each_collection_gets_its_own_identity() -> None:
    """The caller does not choose the id, so it cannot collide with one."""
    repository = InMemoryCollectionRepository()
    use_case = a_use_case(repository)

    first = use_case.execute(CreateCollectionCommand(name="uv docs"))
    second = use_case.execute(CreateCollectionCommand(name="pytest docs"))

    assert first != second
    assert len(repository.collections) == 2


def test_a_name_already_taken_is_refused() -> None:
    repository = InMemoryCollectionRepository()
    use_case = a_use_case(repository)
    use_case.execute(CreateCollectionCommand(name="uv docs"))

    with pytest.raises(DuplicateCollectionNameError):
        use_case.execute(CreateCollectionCommand(name="uv docs"))


def test_the_refusal_names_the_collection() -> None:
    repository = InMemoryCollectionRepository()
    use_case = a_use_case(repository)
    use_case.execute(CreateCollectionCommand(name="uv docs"))

    with pytest.raises(DuplicateCollectionNameError, match="uv docs"):
        use_case.execute(CreateCollectionCommand(name="uv docs"))


def test_a_refused_name_leaves_nothing_behind() -> None:
    repository = InMemoryCollectionRepository()
    use_case = a_use_case(repository)
    use_case.execute(CreateCollectionCommand(name="uv docs"))

    with pytest.raises(DuplicateCollectionNameError):
        use_case.execute(CreateCollectionCommand(name="uv docs"))

    assert len(repository.collections) == 1


def test_uniqueness_is_checked_against_the_stored_name_not_the_submitted_one() -> None:
    """`Collection` strips the name, so the question must use the stripped one."""
    repository = InMemoryCollectionRepository()
    use_case = a_use_case(repository)
    use_case.execute(CreateCollectionCommand(name="uv docs"))

    with pytest.raises(DuplicateCollectionNameError):
        use_case.execute(CreateCollectionCommand(name="   uv docs   "))


def test_the_stored_name_is_stripped() -> None:
    repository = InMemoryCollectionRepository()

    collection_id = a_use_case(repository).execute(
        CreateCollectionCommand(name="  redis docs  ")
    )

    stored = repository.get(collection_id)
    assert stored is not None
    assert stored.name == "redis docs"


def test_names_differing_only_in_case_are_two_collections() -> None:
    """Exact match: the entity normalises whitespace and nothing else."""
    repository = InMemoryCollectionRepository()
    use_case = a_use_case(repository)

    use_case.execute(CreateCollectionCommand(name="uv docs"))
    use_case.execute(CreateCollectionCommand(name="UV Docs"))

    assert len(repository.collections) == 2


def test_a_blank_name_is_refused_by_the_entity() -> None:
    """The use case adds no check of its own; `Collection` already has one."""
    repository = InMemoryCollectionRepository()

    with pytest.raises(MissingCollectionNameError):
        a_use_case(repository).execute(CreateCollectionCommand(name="   "))


def test_a_blank_name_leaves_nothing_behind() -> None:
    repository = InMemoryCollectionRepository()

    with pytest.raises(DomainError):
        a_use_case(repository).execute(CreateCollectionCommand(name=""))

    assert repository.collections == {}
