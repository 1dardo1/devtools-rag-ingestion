"""`PostgresOutbox` against a real database.

Rows are inserted directly, with chosen identities of order and stamps: what is
under test is how a batch is claimed and marked, and `FOR UPDATE SKIP LOCKED` can
only be seen with two connections holding two open transactions. ADR 0028.
"""

from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from rag_ingestion.application.get_event_backlog import (
    EventBacklogReport,
    GetEventBacklog,
)
from rag_ingestion.application.relay_outbox import RelayOutbox, RelayReport
from rag_ingestion.domain.errors import EventBrokerError, RelayFailedError
from rag_ingestion.domain.outbox_row import OutboxRow
from rag_ingestion.infrastructure.postgres.event_backlog import PostgresEventBacklog
from rag_ingestion.infrastructure.postgres.outbox import PostgresOutbox

pytestmark = pytest.mark.integration

type Connection = psycopg.Connection[TupleRow]

_INSERT = (
    "INSERT INTO outbox (event_type, payload, occurred_at, published_at)"
    " VALUES ('DocumentIngested', %s, %s, %s) RETURNING outbox_id"
)

_OCCURRED_AT = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
_SENT_AT = datetime(2026, 11, 26, 9, 5, tzinfo=UTC)
_NOW = datetime(2026, 11, 26, 9, 10, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return _NOW


class RecordingBroker:
    """Accepts every row, except the ones named, which always fail."""

    def __init__(self, failing: set[int] | None = None) -> None:
        self.sent: list[int] = []
        self._failing = failing or set()

    def publish(self, row: OutboxRow) -> None:
        if row.outbox_id in self._failing:
            raise EventBrokerError
        self.sent.append(row.outbox_id)


def _add(
    connection: Connection, n: int = 0, published_at: datetime | None = None
) -> int:
    row = connection.execute(
        _INSERT, (Jsonb({"n": n}), _OCCURRED_AT, published_at)
    ).fetchone()
    assert row is not None
    outbox_id: int = row[0]
    return outbox_id


def _published_at(connection: Connection, outbox_id: int) -> datetime | None:
    row = connection.execute(
        "SELECT published_at FROM outbox WHERE outbox_id = %s", (outbox_id,)
    ).fetchone()
    assert row is not None
    stamp: datetime | None = row[0]
    return stamp


def _backlog(connection: Connection) -> EventBacklogReport:
    return GetEventBacklog(
        backlog=PostgresEventBacklog(connection), clock=FixedClock()
    ).execute()


class TestClaiming:
    def test_an_empty_outbox_yields_nothing(self, migrated: Connection) -> None:
        assert PostgresOutbox(migrated).claim_unpublished(10) == []

    def test_rows_come_back_in_outbox_id_order_with_their_content(
        self, migrated: Connection
    ) -> None:
        first = _add(migrated, n=1)
        second = _add(migrated, n=2)

        claimed = PostgresOutbox(migrated).claim_unpublished(10)

        assert [row.outbox_id for row in claimed] == [first, second]
        assert claimed[0].event_type == "DocumentIngested"
        assert claimed[0].payload == {"n": 1}
        assert claimed[0].occurred_at == _OCCURRED_AT

    def test_no_more_than_the_limit_is_taken(self, migrated: Connection) -> None:
        ids = [_add(migrated, n=n) for n in range(5)]

        claimed = PostgresOutbox(migrated).claim_unpublished(2)

        assert [row.outbox_id for row in claimed] == ids[:2]

    def test_published_rows_are_not_claimed(self, migrated: Connection) -> None:
        _add(migrated, n=1, published_at=_SENT_AT)
        waiting = _add(migrated, n=2)

        claimed = PostgresOutbox(migrated).claim_unpublished(10)

        assert [row.outbox_id for row in claimed] == [waiting]


class TestSkipLocked:
    def test_rows_another_open_transaction_holds_are_skipped(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        first, second, third = (_add(migrated, n=n) for n in range(3))

        with (
            psycopg.connect(postgres_url) as one,
            psycopg.connect(postgres_url) as two,
        ):
            held = PostgresOutbox(one).claim_unpublished(2)
            # Not blocked and not duplicated: the second run gets what is left.
            other = PostgresOutbox(two).claim_unpublished(10)

            assert [row.outbox_id for row in held] == [first, second]
            assert [row.outbox_id for row in other] == [third]
            one.rollback()
            two.rollback()

    def test_the_rows_are_claimable_again_once_the_holder_rolls_back(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        ids = [_add(migrated, n=n) for n in range(2)]

        with (
            psycopg.connect(postgres_url) as one,
            psycopg.connect(postgres_url) as two,
        ):
            PostgresOutbox(one).claim_unpublished(10)
            one.rollback()

            again = PostgresOutbox(two).claim_unpublished(10)

            assert [row.outbox_id for row in again] == ids
            two.rollback()


class TestMarking:
    def test_the_given_instant_is_written_to_the_given_rows_only(
        self, migrated: Connection
    ) -> None:
        marked, left = _add(migrated, n=1), _add(migrated, n=2)

        PostgresOutbox(migrated).mark_published([marked], _SENT_AT)

        assert _published_at(migrated, marked) == _SENT_AT
        assert _published_at(migrated, left) is None

    def test_an_earlier_stamp_is_kept(self, migrated: Connection) -> None:
        sent = _add(migrated, published_at=_SENT_AT)

        PostgresOutbox(migrated).mark_published([sent], _NOW)

        assert _published_at(migrated, sent) == _SENT_AT

    def test_marking_nothing_is_a_no_op(self, migrated: Connection) -> None:
        waiting = _add(migrated)

        PostgresOutbox(migrated).mark_published([], _SENT_AT)

        assert _published_at(migrated, waiting) is None

    def test_marked_rows_are_not_claimed_again(self, migrated: Connection) -> None:
        outbox = PostgresOutbox(migrated)
        _add(migrated, n=1)
        batch = outbox.claim_unpublished(10)

        outbox.mark_published([row.outbox_id for row in batch], _SENT_AT)

        assert outbox.claim_unpublished(10) == []


class TestTheTransactionBelongsToTheCaller:
    """No adapter commits, and this one is no exception. ADR 0013."""

    def test_claiming_and_marking_leave_the_callers_transaction_open(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        _add(migrated)

        with psycopg.connect(postgres_url) as caller:
            outbox = PostgresOutbox(caller)
            batch = outbox.claim_unpublished(10)
            outbox.mark_published([row.outbox_id for row in batch], _SENT_AT)

            assert (
                caller.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
            )
            caller.rollback()

    def test_a_rollback_leaves_every_row_unpublished(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        ids = [_add(migrated, n=n) for n in range(3)]

        with psycopg.connect(postgres_url) as caller:
            outbox = PostgresOutbox(caller)
            batch = outbox.claim_unpublished(10)
            outbox.mark_published([row.outbox_id for row in batch], _SENT_AT)
            caller.rollback()

        assert all(_published_at(migrated, outbox_id) is None for outbox_id in ids)
        assert _backlog(migrated).unpublished == 3

    def test_a_commit_publishes_the_batch(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        ids = [_add(migrated, n=n) for n in range(3)]

        with psycopg.connect(postgres_url) as caller:
            outbox = PostgresOutbox(caller)
            batch = outbox.claim_unpublished(2)
            outbox.mark_published([row.outbox_id for row in batch], _SENT_AT)
            caller.commit()

        assert [_published_at(migrated, i) for i in ids] == [_SENT_AT, _SENT_AT, None]


class TestTheBacklogAfterwards:
    def test_it_counts_only_what_was_not_marked(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        for n in range(4):
            _add(migrated, n=n)
        assert _backlog(migrated).unpublished == 4

        with psycopg.connect(postgres_url) as caller:
            outbox = PostgresOutbox(caller)
            batch = outbox.claim_unpublished(3)
            outbox.mark_published([row.outbox_id for row in batch], _SENT_AT)
            caller.commit()

        report = _backlog(migrated)
        assert report.unpublished == 1
        assert report.oldest_unpublished_age_seconds == 600

    def test_a_fully_relayed_outbox_has_no_backlog(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        _add(migrated)

        with psycopg.connect(postgres_url) as caller:
            outbox = PostgresOutbox(caller)
            batch = outbox.claim_unpublished(10)
            outbox.mark_published([row.outbox_id for row in batch], _SENT_AT)
            caller.commit()

        assert _backlog(migrated) == EventBacklogReport(
            unpublished=0, oldest_unpublished_age_seconds=None
        )


class TestMarkingIgnoresWhatIsNotWaiting:
    def test_an_id_that_does_not_exist_changes_nothing_and_raises_nothing(
        self, migrated: Connection
    ) -> None:
        waiting = _add(migrated)

        PostgresOutbox(migrated).mark_published([waiting + 1000], _SENT_AT)

        assert _published_at(migrated, waiting) is None

    def test_an_already_published_id_in_the_batch_keeps_its_stamp(
        self, migrated: Connection
    ) -> None:
        sent = _add(migrated, published_at=_SENT_AT)
        waiting = _add(migrated)

        PostgresOutbox(migrated).mark_published([sent, waiting], _NOW)

        assert _published_at(migrated, sent) == _SENT_AT
        assert _published_at(migrated, waiting) == _NOW


class TestTheRelayOverTheRealOutbox:
    def test_a_failure_on_the_second_of_three_rows_rolls_everything_back(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        ids = [_add(migrated, n=n) for n in range(3)]
        broker = RecordingBroker(failing={ids[1]})
        sleeps: list[float] = []

        with psycopg.connect(postgres_url) as caller:
            relay = RelayOutbox(
                outbox=PostgresOutbox(caller),
                broker=broker,
                clock=FixedClock(),
                sleep=sleeps.append,
                batch_size=10,
            )
            with pytest.raises(RelayFailedError) as raised:
                relay.execute()
            caller.rollback()

        assert raised.value.outbox_id == ids[1]
        assert sleeps == [1.0, 2.0, 4.0]
        assert broker.sent == [ids[0]]
        # Read through a different connection from the one that rolled back.
        with psycopg.connect(postgres_url) as observer:
            assert [_published_at(observer, i) for i in ids] == [None, None, None]
            observer.rollback()

    def test_a_successful_run_marks_the_batch_with_the_clocks_instant(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        ids = [_add(migrated, n=n) for n in range(3)]

        with psycopg.connect(postgres_url) as caller:
            report = RelayOutbox(
                outbox=PostgresOutbox(caller),
                broker=RecordingBroker(),
                clock=FixedClock(),
                sleep=lambda _: None,
                batch_size=10,
            ).execute()
            caller.commit()

        assert report == RelayReport(published=3)
        assert [_published_at(migrated, i) for i in ids] == [_NOW, _NOW, _NOW]

    def test_a_second_run_mid_publish_skips_the_rows_the_first_holds(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        ids = [_add(migrated, n=n) for n in range(3)]
        second_reports: list[RelayReport] = []
        second_broker = RecordingBroker()

        with (
            psycopg.connect(postgres_url) as first,
            psycopg.connect(postgres_url) as second,
        ):
            second_relay = RelayOutbox(
                outbox=PostgresOutbox(second),
                broker=second_broker,
                clock=FixedClock(),
                sleep=lambda _: None,
                batch_size=10,
            )

            class OverlappingBroker(RecordingBroker):
                """While the first run publishes, a second run starts."""

                def publish(self, row: OutboxRow) -> None:
                    if not second_reports:
                        second_reports.append(second_relay.execute())
                    super().publish(row)

            first_broker = OverlappingBroker()
            first_report = RelayOutbox(
                outbox=PostgresOutbox(first),
                broker=first_broker,
                clock=FixedClock(),
                sleep=lambda _: None,
                batch_size=10,
            ).execute()
            first.commit()
            second.commit()

        assert first_report == RelayReport(published=3)
        assert second_reports == [RelayReport(published=0)]
        assert second_broker.sent == []
        assert first_broker.sent == ids
        assert [_published_at(migrated, i) for i in ids] == [_NOW, _NOW, _NOW]
