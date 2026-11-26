"""The backlog report against a stub port and a fixed clock, nothing real present."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from rag_ingestion.application.get_event_backlog import (
    EventBacklogReport,
    GetEventBacklog,
)
from rag_ingestion.domain.unpublished_events import UnpublishedEvents

_NOW = datetime(2026, 11, 24, 17, 30, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FixedClock:
    """The instant the test names, so an age is an equality and not a guess."""

    instant: datetime

    def now(self) -> datetime:
        return self.instant


@dataclass(frozen=True, slots=True)
class StubEventBacklog:
    """Answers with whatever the test put in it."""

    answer: UnpublishedEvents

    def unpublished(self) -> UnpublishedEvents:
        return self.answer


def _report(waiting: UnpublishedEvents) -> EventBacklogReport:
    return GetEventBacklog(
        backlog=StubEventBacklog(waiting), clock=FixedClock(_NOW)
    ).execute()


class TestWhenNothingIsWaiting:
    def test_the_count_is_zero_and_the_age_is_none(self) -> None:
        report = _report(UnpublishedEvents(count=0))

        assert report == EventBacklogReport(
            unpublished=0, oldest_unpublished_age_seconds=None
        )

    def test_none_is_not_zero(self) -> None:
        # "Nothing is waiting" and "the oldest event is brand new" are different
        # statements, and a monitor must be able to tell them apart.
        nothing = _report(UnpublishedEvents(count=0))
        brand_new = _report(UnpublishedEvents(count=1, oldest_occurred_at=_NOW))

        assert nothing.oldest_unpublished_age_seconds is None
        assert brand_new.oldest_unpublished_age_seconds == 0


class TestWhenSomethingIsWaiting:
    def test_the_age_is_now_minus_the_oldest_instant(self) -> None:
        report = _report(
            UnpublishedEvents(count=3, oldest_occurred_at=_NOW - timedelta(minutes=7))
        )

        assert report.unpublished == 3
        assert report.oldest_unpublished_age_seconds == 7 * 60

    def test_the_age_is_in_whole_seconds_rounded_down(self) -> None:
        report = _report(
            UnpublishedEvents(
                count=1,
                oldest_occurred_at=_NOW - timedelta(seconds=59, microseconds=999_999),
            )
        )

        assert report.oldest_unpublished_age_seconds == 59

    @pytest.mark.parametrize("ahead", [timedelta(seconds=1), timedelta(hours=2)])
    def test_an_instant_in_the_future_is_an_age_of_zero_never_negative(
        self, ahead: timedelta
    ) -> None:
        # A clock stepped back between an ingestion and this read.
        report = _report(UnpublishedEvents(count=1, oldest_occurred_at=_NOW + ahead))

        assert report.oldest_unpublished_age_seconds == 0

    def test_an_instant_in_another_offset_is_compared_as_the_same_instant(self) -> None:
        # 18:20 at +01:00 is 17:20 UTC, ten minutes before the clock's 17:30 UTC.
        madrid = datetime(2026, 11, 24, 18, 20, tzinfo=timezone(timedelta(hours=1)))
        report = _report(UnpublishedEvents(count=1, oldest_occurred_at=madrid))

        assert report.oldest_unpublished_age_seconds == 10 * 60


class TestTheReport:
    def test_it_is_immutable(self) -> None:
        report = _report(UnpublishedEvents(count=0))

        with pytest.raises(AttributeError):
            report.unpublished = 1  # type: ignore[misc]
