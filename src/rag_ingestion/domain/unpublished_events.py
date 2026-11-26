"""What is waiting to be announced, as a fact about the service rather than a table."""

from dataclasses import dataclass
from datetime import datetime

from rag_ingestion.domain.errors import (
    InconsistentBacklogError,
    NaiveTimestampError,
)

_OLDEST_OCCURRED_AT = "oldest_occurred_at"


@dataclass(frozen=True, slots=True)
class UnpublishedEvents:
    """How many announcements have not gone out yet, and since when.

    **It carries the instant, not the age.** An age is "now" minus something, and
    "now" belongs to a `Clock`: a value that held the age would have read the time
    itself, or been handed it, and a test could no longer name the moment it
    expects. The use case that needs an age subtracts it from the clock's answer.

    **The oldest instant is `occurred_at`, the moment of ingestion, and not an
    identity value.** ADR 0012 says outbox identities are assigned at insert, not
    at commit, so the lowest one is not reliably the earliest. The measure that
    matters is how long an event has been waiting, and that is a question about
    time.

    The two fields cannot disagree. A backlog of nothing has no oldest instant,
    and a backlog of something always has one; a half-formed value in which they
    contradict each other would make "nothing is waiting" and "something has
    waited an hour" both readable from the same object. ADR 0027.
    """

    count: int
    oldest_occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.count < 0 or (self.count == 0) != (self.oldest_occurred_at is None):
            raise InconsistentBacklogError(self.count, self.oldest_occurred_at)
        if (
            self.oldest_occurred_at is not None
            and self.oldest_occurred_at.tzinfo is None
        ):
            raise NaiveTimestampError(_OLDEST_OCCURRED_AT)
