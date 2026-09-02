"""The identity of a collection."""

from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4

from rag_ingestion.domain.errors import InvalidCollectionIdError


@dataclass(frozen=True, slots=True)
class CollectionId:
    """A collection's identity.

    Deliberately a separate type from `DocumentId` rather than a shared generic
    identity: the two are never interchangeable, and keeping them distinct is
    what stops a document identifier being passed where a collection is meant.
    The cost is a near-duplicate of twenty lines, which is cheaper than the bug
    it prevents.
    """

    value: UUID

    @classmethod
    def generate(cls) -> Self:
        """Mint a new identity for a collection being created."""
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> Self:
        """Rebuild an identity from its textual form, as stored or received."""
        try:
            return cls(UUID(value))
        except ValueError as error:
            raise InvalidCollectionIdError(value) from error

    def __str__(self) -> str:
        return str(self.value)
