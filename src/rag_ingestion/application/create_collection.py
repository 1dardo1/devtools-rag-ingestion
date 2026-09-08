"""Making a box for documents to go into."""

from dataclasses import dataclass

from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.errors import DuplicateCollectionNameError
from rag_ingestion.domain.ports import CollectionRepository


@dataclass(frozen=True, slots=True)
class CreateCollectionCommand:
    """What a caller must supply to create a collection.

    Only a name. The identity is minted here rather than accepted, so a caller
    cannot choose an id and cannot collide with one that already exists.
    """

    name: str


@dataclass(frozen=True, slots=True)
class CreateCollection:
    """Create a collection, refusing a name that is already taken.

    It publishes no event. Nothing outside this service needs to know that a
    box was made — the retrieval service learns about collections through the
    documents that arrive in them, and inventing an event nobody consumes
    would put a schema in the contracts repository for no reader.

    It reads no clock either. `Collection` records no instant, and giving it
    one now would be guessing at a question nothing has asked.
    """

    collections: CollectionRepository

    def execute(self, command: CreateCollectionCommand) -> CollectionId:
        """Create a collection, or raise a `DomainError` explaining why not.

        The entity is built before the name is checked, and that order is the
        point: `Collection` strips the name and refuses an empty one, so the
        uniqueness question is asked with the value that would actually be
        stored. Checking `command.name` instead would let `"uv docs "` and
        `"uv docs"` both through as different collections.

        The check is exact, not case-insensitive. `Collection` normalises
        whitespace and nothing else, and a rule that folded case here would
        claim a normalisation the entity does not perform — and would need a
        collation decision in Phase 4 to mean the same thing in the database.
        """
        collection = Collection(
            collection_id=CollectionId.generate(), name=command.name
        )
        if self.collections.exists_with_name(collection.name):
            raise DuplicateCollectionNameError(collection.name)

        self.collections.add(collection)
        return collection.collection_id
