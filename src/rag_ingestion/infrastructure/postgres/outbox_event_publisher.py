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
from typing import Any

import psycopg
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb
from rag_contracts.events import EVENT_TYPE
from rag_contracts.events import DocumentIngested as DocumentIngestedPayload

from rag_ingestion.domain.events import DocumentIngested

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
            _INSERT, (EVENT_TYPE, Jsonb(_as_payload(event)), event.occurred_at)
        )


def _as_payload(event: DocumentIngested) -> dict[str, Any]:
    """Turn the event into the JSON object a consumer will read.

    **The shape is not decided here.** It is `rag_contracts.events.DocumentIngested`,
    the schema both services install, and this function only fills it in from the
    domain's event and writes it out. Building the contract model is also what
    validates it, *before* the outbox row is written: an event the contract would
    refuse raises here, inside the document's transaction, and rolls the document
    back with it, instead of sitting in the outbox for the relay to republish for
    ever. ADR 0026.

    The values go in as strings and are parsed, which is what a consumer does with
    them. It means the conversion this function performs is the one the wire
    carries, not a second one that happens to agree.

    `occurred_at` appears here as well as in its own column, and that is not
    duplication to be tidied away. The column is the envelope's, and the relay
    orders and reasons about it; this copy is the contract's, and a consumer
    reading only the payload needs it. The contract writes it in UTC, whatever
    offset the domain's instant carries.
    """
    contract = DocumentIngestedPayload.model_validate(
        {
            "document_id": str(event.document_id),
            "collection_id": str(event.collection_id),
            "content_hash": str(event.content_hash),
            "occurred_at": event.occurred_at,
            "metadata": {
                "source_library": event.metadata.source_library,
                "doc_type": event.metadata.doc_type.value,
                "library_version": event.metadata.library_version,
                "source_url": event.metadata.source_url,
            },
        }
    )
    return contract.model_dump(mode="json")
