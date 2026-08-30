"""Where a document has got to on its way into the index."""

from enum import StrEnum


class DocumentStatus(StrEnum):
    """The stages a document passes through after it is accepted.

    `ARCHITECTURE.md` fixes the shape: `pending → processing → indexed |
    failed`. This module only names the stages; which moves between them are
    allowed is a rule, and rules are unit 1.3.

    String values rather than integers, for the same reason as `DocType`: a
    stored or published status is readable without a lookup table, and stays
    stable if members are reordered.
    """

    PENDING = "pending"
    """Accepted and recorded, waiting for the rest of the system to notice."""

    PROCESSING = "processing"
    """The retrieval service has picked it up and is indexing it."""

    INDEXED = "indexed"
    """Successfully indexed and answerable."""

    FAILED = "failed"
    """Indexing did not succeed. Whether this is final is a rule, not a name."""
