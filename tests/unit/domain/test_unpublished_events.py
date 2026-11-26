"""`UnpublishedEvents`: a count and an instant that cannot contradict each other."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from rag_ingestion.domain.errors import (
    DomainError,
    InconsistentBacklogError,
    NaiveTimestampError,
)
from rag_ingestion.domain.unpublished_events import UnpublishedEvents

_AT = datetime(2026, 11, 24, 17, 0, tzinfo=UTC)


class TestAValidBacklog:
    def test_nothing_waiting_has_no_oldest_instant(self) -> None:
        backlog = UnpublishedEvents(count=0)

        assert backlog.count == 0
        assert backlog.oldest_occurred_at is None

    def test_something_waiting_has_an_oldest_instant(self) -> None:
        backlog = UnpublishedEvents(count=3, oldest_occurred_at=_AT)

        assert backlog.count == 3
        assert backlog.oldest_occurred_at == _AT

    def test_it_is_immutable(self) -> None:
        backlog = UnpublishedEvents(count=1, oldest_occurred_at=_AT)

        with pytest.raises(FrozenInstanceError):
            backlog.count = 2  # type: ignore[misc]


class TestACountAndAnInstantThatContradictEachOther:
    def test_waiting_events_without_an_instant_are_refused(self) -> None:
        with pytest.raises(InconsistentBacklogError):
            UnpublishedEvents(count=2)

    def test_an_instant_with_nothing_waiting_is_refused(self) -> None:
        with pytest.raises(InconsistentBacklogError):
            UnpublishedEvents(count=0, oldest_occurred_at=_AT)

    def test_a_negative_count_is_refused(self) -> None:
        with pytest.raises(InconsistentBacklogError):
            UnpublishedEvents(count=-1, oldest_occurred_at=_AT)

    def test_the_refusal_is_a_domain_error_that_names_both_values(self) -> None:
        with pytest.raises(DomainError, match=r"backlog of 2 .* None"):
            UnpublishedEvents(count=2)


class TestTheInstant:
    def test_a_naive_instant_is_refused(self) -> None:
        with pytest.raises(NaiveTimestampError):
            UnpublishedEvents(count=1, oldest_occurred_at=datetime(2026, 11, 24, 17, 0))  # noqa: DTZ001
