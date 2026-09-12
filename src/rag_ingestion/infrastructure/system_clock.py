"""The clock production uses."""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Reads the real time, in UTC.

    The entire implementation of the `Clock` port, and ADR 0009 argues it is
    worth a port anyway: reading a clock is I/O wearing a disguise, and the
    alternative to this three-line class is every test that asserts on a
    timestamp either becoming non-deterministic or patching `datetime`.

    **Always UTC, never naive.** `Document` and `DocumentIngested` both refuse a
    datetime without a timezone, and `ruff`'s `DTZ` family refuses to let
    `datetime.now()` be written without one — so this cannot drift into local
    time by accident.
    """

    def now(self) -> datetime:
        """Return the current instant, with a timezone attached."""
        return datetime.now(UTC)
