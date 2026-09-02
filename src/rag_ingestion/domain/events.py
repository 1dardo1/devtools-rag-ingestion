"""What this service announces to the rest of the system."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.errors import NaiveTimestampError
from rag_ingestion.domain.metadata import Metadata

_OCCURRED_AT = "occurred_at"


@dataclass(frozen=True, slots=True)
class DocumentIngested:
    """A document has been accepted and is ready to be indexed.

    Frozen, because an event is a statement about something that already
    happened. A fact that can be edited after the fact is not a fact.

    **It does not carry the content.** A consumer that needs the bytes fetches
    them by `document_id`; putting them in the message would push megabytes
    through the broker for every document, and Redis Streams is not a content
    store. What the event carries is what a consumer needs in order to decide
    whether it cares and how to file the result: which document, which
    collection, what the content fingerprint is, and the metadata it will
    filter on.

    `content_hash` travels with the event for a second reason. Delivery is
    at-least-once, so the same event will sometimes arrive twice, and principle
    4.7 requires the consumer to be idempotent. `document_id` plus
    `content_hash` is enough to recognise a repeat without asking this service
    anything.

    This shape is what `ROADMAP.md` 1.4 requires be agreed before Phase 3
    turns it into the published schema in the contracts repository.
    """

    document_id: DocumentId
    collection_id: CollectionId
    content_hash: ContentHash
    metadata: Metadata
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise NaiveTimestampError(_OCCURRED_AT)

    @classmethod
    def about(cls, document: Document, occurred_at: datetime) -> Self:
        """Announce a document that has just been accepted.

        The instant is supplied rather than read from the clock here: a domain
        object that calls `datetime.now()` cannot be tested without freezing
        time, and reading a clock is I/O wearing a disguise. Phase 2 decides
        where the instant comes from.
        """
        return cls(
            document_id=document.document_id,
            collection_id=document.collection_id,
            content_hash=document.content_hash,
            metadata=document.metadata,
            occurred_at=occurred_at,
        )
