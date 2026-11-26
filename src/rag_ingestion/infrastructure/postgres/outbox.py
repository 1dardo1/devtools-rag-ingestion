"""The outbox, claimed in batches and marked once they have been sent."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import TupleRow

from rag_ingestion.domain.outbox_row import OutboxRow

# `published_at IS NULL` and `ORDER BY outbox_id` are exactly the partial index
# `outbox_unpublished` (ADR 0012), so the batch is read from the backlog and not
# from every event ever sent, and no migration is needed.
#
# `FOR UPDATE SKIP LOCKED` is what keeps two overlapping relays apart (ADR 0028):
# a row another open transaction has locked is passed over, not waited for and not
# returned twice. The lock lasts until the caller commits or rolls back.
_CLAIM = """
SELECT outbox_id, event_type, payload, occurred_at
FROM outbox
WHERE published_at IS NULL
ORDER BY outbox_id
LIMIT %s
FOR UPDATE SKIP LOCKED
"""

# The instant is a parameter and never `now()`: time enters through the `Clock`
# port (ADR 0009). `published_at IS NULL` keeps a stamp that is already there.
# `::bigint[]` because an empty list has no type the server can infer.
_MARK = """
UPDATE outbox
SET published_at = %s
WHERE outbox_id = ANY(%s::bigint[]) AND published_at IS NULL
"""


@dataclass(frozen=True, slots=True)
class PostgresOutbox:
    """The outbox as the relay reads it, through the connection it was given.

    Takes a connection and never commits, like every adapter here (ADR 0013). For
    this one the rule carries the whole design: the row locks `claim_unpublished`
    takes are released by the caller's commit or rollback, so an adapter that
    committed would release them before the batch had been sent, and one run's
    rows could be claimed again by another. The caller commits after
    `mark_published`, and rolls back if the batch failed, leaving every row
    unpublished. ADR 0028.
    """

    connection: psycopg.Connection[TupleRow]

    def claim_unpublished(self, limit: int) -> Sequence[OutboxRow]:
        """Lock and return up to `limit` unpublished rows, lowest `outbox_id` first."""
        rows = self.connection.execute(_CLAIM, (limit,)).fetchall()
        return [
            OutboxRow(
                outbox_id=outbox_id,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            )
            for outbox_id, event_type, payload, occurred_at in rows
        ]

    def mark_published(self, outbox_ids: Sequence[int], published_at: datetime) -> None:
        """Stamp these rows as sent at `published_at`, on the caller's transaction."""
        self.connection.execute(_MARK, (published_at, list(outbox_ids)))
