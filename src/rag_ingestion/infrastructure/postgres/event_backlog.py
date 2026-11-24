"""What the outbox still holds, counted."""

from dataclasses import dataclass

import psycopg
from psycopg.rows import TupleRow

from rag_ingestion.domain.unpublished_events import UnpublishedEvents
from rag_ingestion.infrastructure.postgres._results import exactly_one_row

# `published_at IS NULL` is exactly the predicate of the partial index
# `outbox_unpublished` (ADR 0012), so this reads the backlog and not the history of
# every event ever sent. `min(occurred_at)` and not the lowest `outbox_id`: the
# identity is assigned at insert, not at commit, so it is not ordered by time.
# An aggregate always returns one row; with nothing waiting it is `(0, NULL)`.
_SELECT = """
SELECT count(*), min(occurred_at)
FROM outbox
WHERE published_at IS NULL
"""


@dataclass(frozen=True, slots=True)
class PostgresEventBacklog:
    """The outbox's backlog, read through the connection it was given.

    Takes a connection and never commits, like every adapter here (ADR 0013). It
    only reads, so nothing depends on which connection it gets, but the rule has
    no exceptions: the one adapter that was allowed to commit would be the one
    nobody remembered when the invariant broke.
    """

    connection: psycopg.Connection[TupleRow]

    def unpublished(self) -> UnpublishedEvents:
        """Count the rows no relay has sent, and find the oldest of them."""
        count, oldest = exactly_one_row(self.connection.execute(_SELECT))
        return UnpublishedEvents(count=count, oldest_occurred_at=oldest)
