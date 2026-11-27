"""One announcement waiting in the outbox, as the relay sees it."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from rag_ingestion.domain.errors import NaiveTimestampError

_OCCURRED_AT = "occurred_at"


@dataclass(frozen=True, slots=True)
class OutboxRow:
    """An outbox row no relay has sent yet.

    **It carries what the relay needs to send and to name a failure, and nothing
    more.** `outbox_id` is the row's identity and the order a batch is taken in;
    `event_type` and `payload` are the envelope's content; `occurred_at` is the
    instant of ingestion, kept because a broker adapter may stamp it onto the
    message. `published_at` is absent on purpose: a row held here is by
    definition not published, and the relay is the only thing that sets it.

    **The payload is a JSON-compatible mapping and the domain does not look
    inside it.** Its shape belongs to the contracts package (ADR 0026), which the
    domain does not import. The relay moves it and never reads a field.

    The instant must carry a timezone, like every other instant here (ADR 0009).
    ADR 0028.
    """

    outbox_id: int
    event_type: str
    payload: Mapping[str, object]
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise NaiveTimestampError(_OCCURRED_AT)
