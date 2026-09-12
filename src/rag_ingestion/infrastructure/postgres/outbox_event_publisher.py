"""The outbox: an announcement written in the document's own transaction.

**This is the piece `ROADMAP.md` calls the deliverable rather than the
plumbing.** It does not talk to Redis. It writes a row to the `outbox` table on
the connection it was given, which is the same connection the document was
written on, so the two are one transaction and it becomes impossible to have
stored a document that nobody was ever told about.

A separate relay process publishes those rows later — unit 4.3, which is the
only part of this chain that Phase 3 in `devtools-rag-contracts` blocks.
"""

from dataclasses import dataclass

import psycopg
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from rag_ingestion.domain.events import DocumentIngested

# Spelled out rather than taken from `type(event).__name__`. The class name is
# Python's, and a rename is a refactor; this string is on the wire, where a
# rename is a breaking change for every consumer. Deriving one from the other
# would let a refactor silently publish a different event type.
_EVENT_TYPE = "DocumentIngested"

# `published_at` is left out of the column list, not set to NULL: the relay owns
# it, and absent is how the row says "not yet sent". `outbox_id` is an identity
# column the database assigns, which is what gives the relay an order to publish
# in. ADR 0012.
_INSERT = "INSERT INTO outbox (event_type, payload, occurred_at) VALUES (%s, %s, %s)"


@dataclass(frozen=True, slots=True)
class PostgresOutboxEventPublisher:
    """Where announcements go: a table, not a broker.

    Takes a connection and never commits, exactly as the repositories do and
    for the reason they do it — except that here it is the whole point rather
    than a precaution. Hand this publisher and `PostgresDocumentRepository` the
    same connection and the document and its announcement are atomic; commit
    once, and either both are durable or neither is. ADR 0013 and ADR 0014.
    """

    connection: psycopg.Connection[TupleRow]

    def publish(self, event: DocumentIngested) -> None:
        """Record that a document was ingested, for the relay to send on.

        One statement, on the caller's open transaction. Nothing is flushed,
        nothing is committed, and no broker is contacted — if this method ever
        grows a network call, the invariant is gone, because a socket cannot be
        rolled back.
        """
        self.connection.execute(
            _INSERT, (_EVENT_TYPE, Jsonb(_as_payload(event)), event.occurred_at)
        )


def _as_payload(event: DocumentIngested) -> dict[str, object]:
    """Turn the event into the JSON object a consumer will read.

    **The field names are the domain's own**, which is deliberate rather than
    lazy: `ROADMAP.md` 1.4 already agreed this shape, and Phase 3 turns that
    agreement into the published schema in `devtools-rag-contracts`. Writing
    anything else down here would be inventing a second shape for Phase 3 to
    reconcile. **Phase 3 owns the contract** — a version field, renamed keys, a
    formal schema — and when it lands, this function is the only thing that
    changes.

    The conversions are explicit because they have to be: psycopg's `Jsonb`
    refuses a raw `UUID` and a raw `datetime` outright, which is a good refusal.
    It forces the wire representation to be chosen rather than inherited from
    whatever `json` happened to do.

    `occurred_at` appears here as well as in its own column, and that is not
    duplication to be tidied away. The column is the envelope's, and the relay
    orders and reasons about it; this copy is the contract's, and a consumer
    reading only the payload needs it. Both are written from the same value in
    one statement, so they cannot disagree — and keeping it here is what lets
    the relay in 4.3 stay a dumb pipe instead of a thing that shapes messages.
    """
    return {
        "document_id": str(event.document_id),
        "collection_id": str(event.collection_id),
        "content_hash": str(event.content_hash),
        "occurred_at": event.occurred_at.isoformat(),
        "metadata": {
            "source_library": event.metadata.source_library,
            "doc_type": event.metadata.doc_type.value,
            "library_version": event.metadata.library_version,
            "source_url": event.metadata.source_url,
        },
    }
