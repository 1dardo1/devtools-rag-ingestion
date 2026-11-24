"""`PostgresEventBacklog` against a real database.

The outbox is filled by direct `INSERT`, not through the publisher: what is under
test is how the backlog is *read*, and a row with a chosen `occurred_at` and a
chosen `published_at` is the only way to make the oldest one differ from the
lowest identity. ADR 0027.
"""

from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from rag_ingestion.infrastructure.postgres.event_backlog import PostgresEventBacklog

pytestmark = pytest.mark.integration

type Connection = psycopg.Connection[TupleRow]

_INSERT = (
    "INSERT INTO outbox (event_type, payload, occurred_at, published_at)"
    " VALUES ('DocumentIngested', %s, %s, %s)"
)

_EARLY = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
_MIDDLE = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
_LATE = datetime(2026, 11, 24, 11, 0, tzinfo=UTC)
_SENT_AT = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _add(
    connection: Connection, occurred_at: datetime, published_at: datetime | None = None
) -> None:
    connection.execute(_INSERT, (Jsonb({}), occurred_at, published_at))


class TestWhatTheBacklogIs:
    def test_an_empty_outbox_has_nothing_waiting(self, migrated: Connection) -> None:
        backlog = PostgresEventBacklog(migrated).unpublished()

        assert backlog.count == 0
        assert backlog.oldest_occurred_at is None

    def test_unpublished_rows_are_counted_and_the_oldest_is_found(
        self, migrated: Connection
    ) -> None:
        _add(migrated, _MIDDLE)
        _add(migrated, _EARLY)
        _add(migrated, _LATE)

        backlog = PostgresEventBacklog(migrated).unpublished()

        assert backlog.count == 3
        assert backlog.oldest_occurred_at == _EARLY

    def test_rows_the_relay_has_sent_are_not_part_of_the_backlog(
        self, migrated: Connection
    ) -> None:
        _add(migrated, _EARLY, published_at=_SENT_AT)
        _add(migrated, _MIDDLE, published_at=_SENT_AT)
        _add(migrated, _LATE)

        backlog = PostgresEventBacklog(migrated).unpublished()

        assert backlog.count == 1
        assert backlog.oldest_occurred_at == _LATE

    def test_a_backlog_that_has_all_been_sent_is_empty(
        self, migrated: Connection
    ) -> None:
        _add(migrated, _EARLY, published_at=_SENT_AT)

        backlog = PostgresEventBacklog(migrated).unpublished()

        assert backlog.count == 0
        assert backlog.oldest_occurred_at is None

    def test_the_oldest_is_by_time_and_not_by_the_identity_the_database_assigned(
        self, migrated: Connection
    ) -> None:
        # ADR 0012: identities are assigned at insert, not at commit, so the lowest
        # `outbox_id` is not reliably the earliest. Here it plainly is not.
        _add(migrated, _LATE)
        _add(migrated, _EARLY)
        lowest_id_first = migrated.execute(
            "SELECT occurred_at FROM outbox ORDER BY outbox_id LIMIT 1"
        ).fetchone()
        assert lowest_id_first == (_LATE,)

        backlog = PostgresEventBacklog(migrated).unpublished()

        assert backlog.oldest_occurred_at == _EARLY

    def test_the_instant_comes_back_with_its_timezone(
        self, migrated: Connection
    ) -> None:
        _add(migrated, _EARLY)

        oldest = PostgresEventBacklog(migrated).unpublished().oldest_occurred_at

        assert oldest is not None
        assert oldest.utcoffset() is not None


class TestTheTransactionBelongsToTheCaller:
    """No adapter commits, and this one is no exception. ADR 0013."""

    def test_reading_the_backlog_leaves_the_callers_transaction_open(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        # NOT autocommit: this connection plays the part the composition root plays.
        with psycopg.connect(postgres_url) as caller:
            PostgresEventBacklog(caller).unpublished()

            # A commit would have ended it and left the connection idle.
            assert (
                caller.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
            )
            caller.rollback()
