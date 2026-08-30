"""A fingerprint of a document's contents."""

import hashlib
from dataclasses import dataclass
from typing import Self

from rag_ingestion.domain.errors import InvalidContentHashError

_DIGEST_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class ContentHash:
    """A SHA-256 digest of a document's bytes, as lowercase hexadecimal.

    The digest is computed here rather than accepted from a caller, so two
    equal hashes are guaranteed to come from the same algorithm over the same
    bytes. The deduplication rule rests entirely on that guarantee: without it,
    "these two documents are the same" would mean only "somebody said so".

    Empty content hashes successfully. Whether a document is allowed to be
    empty is a size limit, and size limits belong to unit 1.3 — not to a value
    object whose job is to describe bytes it is handed.
    """

    value: str

    def __post_init__(self) -> None:
        if len(self.value) != _DIGEST_LENGTH or not _HEX_DIGITS.issuperset(self.value):
            raise InvalidContentHashError(self.value)

    @classmethod
    def of(cls, content: bytes) -> Self:
        """Fingerprint the given content."""
        return cls(hashlib.sha256(content).hexdigest())

    def __str__(self) -> str:
        return self.value
