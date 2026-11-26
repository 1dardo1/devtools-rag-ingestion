"""One relay run against in-memory fakes, with no database, broker or waiting."""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from rag_ingestion.application.relay_outbox import RelayOutbox, RelayReport
from rag_ingestion.domain.errors import (
    EventBrokerError,
    InvalidBatchSizeError,
    RelayFailedError,
)
from rag_ingestion.domain.outbox_row import OutboxRow
from rag_ingestion.domain.ports import Clock, EventBroker, Outbox

_OCCURRED_AT = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
_NOW = datetime(2026, 11, 26, 9, 5, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return _NOW


class InMemoryOutbox:
    """Hands out unpublished rows oldest first and remembers what was marked."""

    def __init__(self, rows: Sequence[OutboxRow], log: list[str]) -> None:
        self.rows = list(rows)
        self.marked: list[tuple[list[int], datetime]] = []
        self._log = log

    def claim_unpublished(self, limit: int) -> Sequence[OutboxRow]:
        self._log.append("claim")
        return sorted(self.rows, key=lambda row: row.outbox_id)[:limit]

    def mark_published(self, outbox_ids: Sequence[int], published_at: datetime) -> None:
        self._log.append("mark")
        self.marked.append((list(outbox_ids), published_at))


class InMemoryBroker:
    """Records each attempt; fails a row as many times as the test says."""

    def __init__(self, log: list[str], failures: dict[int, int] | None = None) -> None:
        self.attempts: list[int] = []
        self._failures = dict(failures or {})
        self._log = log

    def publish(self, row: OutboxRow) -> None:
        self._log.append(f"publish {row.outbox_id}")
        self.attempts.append(row.outbox_id)
        if self._failures.get(row.outbox_id, 0) > 0:
            self._failures[row.outbox_id] -= 1
            raise EventBrokerError


def _row(outbox_id: int) -> OutboxRow:
    return OutboxRow(
        outbox_id=outbox_id,
        event_type="DocumentIngested",
        payload={"n": outbox_id},
        occurred_at=_OCCURRED_AT,
    )


class _Run:
    def __init__(
        self,
        row_ids: Sequence[int],
        *,
        failures: dict[int, int] | None = None,
        batch_size: int = 100,
    ) -> None:
        self.log: list[str] = []
        self.sleeps: list[float] = []
        self.outbox = InMemoryOutbox([_row(i) for i in row_ids], self.log)
        self.broker = InMemoryBroker(self.log, failures)
        # Assigning to the port types is the check that the fakes still match.
        outbox: Outbox = self.outbox
        broker: EventBroker = self.broker
        clock: Clock = FixedClock()
        self.relay = RelayOutbox(
            outbox=outbox,
            broker=broker,
            clock=clock,
            sleep=self.sleeps.append,
            batch_size=batch_size,
        )


class TestPublishingAndMarking:
    def test_every_row_is_published_before_the_batch_is_marked(self) -> None:
        run = _Run([1, 2, 3])

        report = run.relay.execute()

        assert report == RelayReport(published=3)
        assert run.log == ["claim", "publish 1", "publish 2", "publish 3", "mark"]

    def test_the_batch_is_marked_whole_with_the_clocks_instant(self) -> None:
        run = _Run([1, 2])

        run.relay.execute()

        assert run.outbox.marked == [([1, 2], _NOW)]

    def test_rows_go_out_in_outbox_id_order(self) -> None:
        run = _Run([3, 1, 2])

        run.relay.execute()

        assert run.broker.attempts == [1, 2, 3]

    def test_an_empty_outbox_does_nothing(self) -> None:
        run = _Run([])

        report = run.relay.execute()

        assert report == RelayReport(published=0)
        assert run.log == ["claim"]
        assert run.sleeps == []

    def test_no_more_than_the_batch_size_is_taken(self) -> None:
        run = _Run([1, 2, 3, 4, 5], batch_size=2)

        report = run.relay.execute()

        assert report == RelayReport(published=2)
        assert run.broker.attempts == [1, 2]
        assert run.outbox.marked == [([1, 2], _NOW)]

    @pytest.mark.parametrize("size", [0, -1])
    def test_a_batch_must_hold_a_row(self, size: int) -> None:
        with pytest.raises(InvalidBatchSizeError):
            _Run([1], batch_size=size)


class TestRetries:
    def test_a_row_that_succeeds_at_once_is_never_waited_for(self) -> None:
        run = _Run([1])

        run.relay.execute()

        assert run.sleeps == []

    def test_success_after_two_failures_waits_one_then_two_seconds(self) -> None:
        run = _Run([1, 2], failures={1: 2})

        report = run.relay.execute()

        assert report == RelayReport(published=2)
        assert run.broker.attempts == [1, 1, 1, 2]
        assert run.sleeps == [1.0, 2.0]
        assert run.outbox.marked == [([1, 2], _NOW)]

    def test_success_on_the_last_retry_waits_one_two_and_four_seconds(self) -> None:
        run = _Run([1], failures={1: 3})

        run.relay.execute()

        assert run.broker.attempts == [1, 1, 1, 1]
        assert run.sleeps == [1.0, 2.0, 4.0]

    def test_a_row_that_keeps_failing_is_tried_four_times_then_given_up(
        self,
    ) -> None:
        run = _Run([1], failures={1: 99})

        with pytest.raises(RelayFailedError):
            run.relay.execute()

        assert run.broker.attempts == [1, 1, 1, 1]
        assert run.sleeps == [1.0, 2.0, 4.0]


class TestWhenARowCannotBeSent:
    def test_the_error_names_the_failing_row(self) -> None:
        run = _Run([1, 2, 3], failures={2: 99})

        with pytest.raises(RelayFailedError) as raised:
            run.relay.execute()

        assert raised.value.outbox_id == 2
        assert "2" in str(raised.value)
        assert isinstance(raised.value.__cause__, EventBrokerError)

    def test_nothing_is_marked_not_even_the_rows_already_sent(self) -> None:
        run = _Run([1, 2, 3], failures={2: 99})

        with pytest.raises(RelayFailedError):
            run.relay.execute()

        assert run.outbox.marked == []
        assert "mark" not in run.log

    def test_the_rows_after_the_failing_one_are_not_attempted(self) -> None:
        run = _Run([1, 2, 3], failures={2: 99})

        with pytest.raises(RelayFailedError):
            run.relay.execute()

        assert 3 not in run.broker.attempts

    def test_an_error_that_is_not_the_brokers_is_not_retried(self) -> None:
        run = _Run([1])

        def explode(row: OutboxRow) -> None:
            raise ZeroDivisionError

        run.broker.publish = explode  # type: ignore[method-assign]

        with pytest.raises(ZeroDivisionError):
            run.relay.execute()

        assert run.sleeps == []
