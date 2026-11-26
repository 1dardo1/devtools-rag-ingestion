"""Answering "is anything waiting too long to be announced?"."""

from dataclasses import dataclass

from rag_ingestion.domain.ports import Clock, EventBacklog


@dataclass(frozen=True, slots=True)
class EventBacklogReport:
    """What a caller is told about the announcements still waiting.

    **The age is in whole seconds, rounded down, and `None` when nothing waits.**
    Seconds because the thresholds anyone will act on are minutes; whole because a
    fraction of a second of backlog means nothing; and `None` rather than `0`
    because "nothing is waiting" and "the oldest event is brand new" are different
    statements, and a monitor reading a bare number could not tell them apart.
    """

    unpublished: int
    oldest_unpublished_age_seconds: int | None


@dataclass(frozen=True, slots=True)
class GetEventBacklog:
    """Report how many announcements are waiting and how long the oldest has.

    **It reads the clock, which the status use case does not.** An age is "now"
    minus a stamp, so the answer changes while nothing else does, and "now" has to
    come from the port for a test to name the moment it expects. Nothing here calls
    `datetime.now()`.

    Two clients use it, the HTTP endpoint and the relay, so both measure the same
    thing. ADR 0027.
    """

    backlog: EventBacklog
    clock: Clock

    def execute(self) -> EventBacklogReport:
        """Describe the backlog as of now."""
        waiting = self.backlog.unpublished()
        if waiting.oldest_occurred_at is None:
            return EventBacklogReport(
                unpublished=waiting.count, oldest_unpublished_age_seconds=None
            )
        age = self.clock.now() - waiting.oldest_occurred_at
        # Never negative. Both instants are stamped by this service's own clock, so
        # they should agree, but a clock stepped back between an ingestion and this
        # read would otherwise report an age below zero, which no threshold is
        # written for.
        return EventBacklogReport(
            unpublished=waiting.count,
            oldest_unpublished_age_seconds=max(0, int(age.total_seconds())),
        )
