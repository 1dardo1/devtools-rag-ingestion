"""A named group of documents."""

from dataclasses import dataclass

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.errors import MissingCollectionNameError


@dataclass(eq=False, slots=True)
class Collection:
    """The box documents are ingested into.

    An entity for the same reason `Document` is: renaming a collection does not
    make it a different collection, so identity rather than contents decides
    equality.

    It does not hold its documents. A collection with ten thousand documents
    would otherwise be unloadable without them, and every rule that spans the
    two — deduplication within a collection, a limit on how many it may hold —
    is expressed against the repository in unit 1.3 rather than against a list
    the entity carries around.

    Limits are likewise not here. How large a collection may grow is policy,
    and policy that changes should not require touching the entity.
    """

    collection_id: CollectionId
    name: str

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise MissingCollectionNameError
        self.name = name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Collection):
            return NotImplemented
        return self.collection_id == other.collection_id

    def __hash__(self) -> int:
        return hash(self.collection_id)
