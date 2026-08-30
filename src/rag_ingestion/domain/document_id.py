"""The identity of a document, independent of its contents."""

from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4

from rag_ingestion.domain.errors import InvalidDocumentIdError


@dataclass(frozen=True, slots=True)
class DocumentId:
    """A document's identity.

    The domain generates it rather than accepting one from the caller: identity
    is a domain concern, and letting a client choose the identifier would make
    it responsible for uniqueness. Repeated submissions of the same document
    are recognised by `ContentHash` instead.

    Wrapping `UUID` rather than `str` means a function that wants a document
    identity cannot be handed an arbitrary string by mistake.
    """

    value: UUID

    @classmethod
    def generate(cls) -> Self:
        """Mint a new identity for a document that has just arrived."""
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> Self:
        """Rebuild an identity from its textual form, as stored or received."""
        try:
            return cls(UUID(value))
        except ValueError as error:
            raise InvalidDocumentIdError(value) from error

    def __str__(self) -> str:
        return str(self.value)
