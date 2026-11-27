"""An outbox row is a fact with an instant, and the instant carries a timezone."""

from datetime import UTC, datetime

import pytest

from rag_ingestion.domain.errors import NaiveTimestampError
from rag_ingestion.domain.outbox_row import OutboxRow

_INSTANT = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)


def test_a_row_holds_what_the_relay_needs() -> None:
    row = OutboxRow(
        outbox_id=7,
        event_type="DocumentIngested",
        payload={"document_id": "x"},
        occurred_at=_INSTANT,
    )

    assert row.outbox_id == 7
    assert row.event_type == "DocumentIngested"
    assert row.payload == {"document_id": "x"}
    assert row.occurred_at == _INSTANT


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(NaiveTimestampError):
        OutboxRow(
            outbox_id=1,
            event_type="DocumentIngested",
            payload={},
            occurred_at=datetime(2026, 11, 26, 9, 0),  # noqa: DTZ001
        )
