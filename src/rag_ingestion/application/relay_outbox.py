"""One run of the relay: send a batch of outbox rows, then mark them sent."""

from collections.abc import Callable
from dataclasses import dataclass

from rag_ingestion.domain.errors import (
    EventBrokerError,
    InvalidBatchSizeError,
    RelayFailedError,
)
from rag_ingestion.domain.outbox_row import OutboxRow
from rag_ingestion.domain.ports import Clock, EventBroker, Outbox

# Three retries after the first attempt, waiting 1, 2 and 4 seconds before each.
# Four attempts in all. ADR 0028.
RETRY_DELAYS_IN_SECONDS = (1.0, 2.0, 4.0)


@dataclass(frozen=True, slots=True)
class RelayReport:
    """How many rows one run sent."""

    published: int


@dataclass(frozen=True, slots=True)
class RelayOutbox:
    """Claim a batch, publish each row, then mark the batch published.

    **Publish, then mark, and never the other way round** (ADR 0028): a row is
    marked only after the broker has taken it, so a crash can repeat an
    announcement but never lose one.

    **The use case owns the unit of work and the caller owns the transaction.**
    Claiming, sending and marking happen in this one call, so they cannot be split
    across transactions by a caller who misunderstands them. But it never commits
    or rolls back, because no collaborator here may (ADR 0013): when it returns,
    the caller commits; when it raises, the caller rolls back, which unmarks
    nothing because nothing was marked, and releases the locks on the claimed
    rows. A row sent before the failing one is therefore sent again on the next
    run, which is the at-least-once delivery ADR 0003 accepts.

    **`sleep` is injected**, like the clock, so a test does not wait seven
    seconds to prove the backoff. The waits happen while the batch's row locks are
    held, which ADR 0028 records as a cost.

    **`published_at` comes from the `Clock`, read once after the last send**, not
    from the database's `now()` (ADR 0009, ADR 0012). It is read after the
    sends so that it is never earlier than a row's announcement.
    """

    outbox: Outbox
    broker: EventBroker
    clock: Clock
    sleep: Callable[[float], None]
    batch_size: int

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise InvalidBatchSizeError(self.batch_size)

    def execute(self) -> RelayReport:
        """Relay one batch; raise `RelayFailedError` if a row cannot be sent."""
        rows = self.outbox.claim_unpublished(self.batch_size)
        if not rows:
            return RelayReport(published=0)
        for row in rows:
            self._publish_with_retries(row)
        self.outbox.mark_published(
            [row.outbox_id for row in rows], published_at=self.clock.now()
        )
        return RelayReport(published=len(rows))

    def _publish_with_retries(self, row: OutboxRow) -> None:
        for delay in RETRY_DELAYS_IN_SECONDS:
            try:
                self.broker.publish(row)
            except EventBrokerError:
                self.sleep(delay)
            else:
                return
        try:
            self.broker.publish(row)
        except EventBrokerError as error:
            raise RelayFailedError(
                row.outbox_id, attempts=len(RETRY_DELAYS_IN_SECONDS) + 1
            ) from error
