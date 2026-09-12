"""How the service says what it is doing, and shouts when something breaks.

`docs/BUILD-PLAN.md` carries this as a `[+]` item due before 4.5, because the
relay in 4.3 runs unattended: "a relay that has quietly stopped announcing
anything looks exactly like a relay with nothing to announce."

**This module is half of that problem.** It decides the *mechanism* — one JSON
object per line on stdout, through the standard library. It does not yet make
silence distinguishable from success, which needs something that speaks when
there is nothing to report. ADR 0016 names that as a separate decision, due
before 4.3.

The standard library rather than a logging library, and ADR 0016 gives the
reason that settled it: `ruff`'s `G` and `LOG` families have been enabled since
ADR 0006, both of them lint `logging` and nothing else. Two of the
twenty-three rule families chosen for this repository have so far been watching
code that did not exist.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import IO

# Computed from a throwaway record rather than written out, so that a Python
# release adding an attribute to `LogRecord` does not start leaking it as though
# somebody had passed it in `extra`. `message` and `asctime` are added by
# `Formatter.format` itself and are reserved for the same reason.
_RESERVED = frozenset(
    vars(
        logging.LogRecord(
            name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
        )
    )
) | {"message", "asctime"}

# Set per request by the middleware in `api/request_id.py`, read here. A
# `ContextVar` rather than an argument threaded through every call site: the
# point of a correlation id is that code which knows nothing about HTTP still
# gets tagged, and a parameter would have to reach the domain to manage that.
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    `request_id` is in the envelope rather than in `context`, because it is not
    something a caller passed in: it identifies the request every other field
    belongs to, which is what makes several lines readable as one story.

    **Anything passed in `extra` is nested under `context`, never merged into
    the top level.** Flat is more ergonomic to query and was rejected: a caller
    logging `extra={"level": ...}` would overwrite the record's real level, and
    the choice would be between silently dropping the caller's field or silently
    corrupting the envelope. Nesting makes the collision impossible instead of
    documented — the same envelope-and-payload split the outbox uses, for the
    same reason.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render one record as a single line of JSON."""
        payload: dict[str, object] = {
            # From `record.created` rather than a fresh `datetime.now()`: the
            # instant the event happened, not the instant it was formatted.
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            # `getMessage` applies the `%`-style arguments. `ruff`'s G004 forbids
            # f-strings in logging calls precisely so that formatting is
            # deferred to here, which only works if here actually does it.
            "message": record.getMessage(),
        }
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info is not None:
            payload["stack"] = self.formatStack(record.stack_info)

        context = {
            key: value for key, value in vars(record).items() if key not in _RESERVED
        }
        if context:
            payload["context"] = context

        # `default=repr` so that an unserialisable value — a `DocumentId`, a
        # `datetime` — is rendered lossily rather than raising. A logging call
        # that throws takes down the request it was describing, which is a far
        # worse outcome than an approximate field.
        return json.dumps(payload, default=repr)


def configure(level: int | str = logging.INFO, stream: IO[str] | None = None) -> None:
    """Send every log record to one stream as JSON. Safe to call twice.

    **stdout, not stderr.** In the Phase 5 container stdout *is* the log, and
    leaving stderr to the runtime's own complaints keeps the two distinguishable.

    **Not called on import.** The composition root calls it, for the same reason
    `create_app` is a factory: a module whose import reconfigures the root logger
    is a module that cannot be imported by a test that wanted different settings.

    `force=True` drops handlers a previous call installed, so configuring twice
    does not log everything twice. That matters more than it sounds: Alembic's
    `env.py` also configures logging when migrations run in-process.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
