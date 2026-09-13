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

# The one library-specific exclusion in this module, and it is here rather than in
# `_RESERVED` because it is not a `LogRecord` attribute: `uvicorn` passes
# `color_message` in `extra` on several of its lines, holding the same message
# again with ANSI escape sequences in it. Nested under `context` it is neither
# context nor readable — it is a second rendering of `message`, escape codes and
# all, in a log that is meant to be machine-read. Dropped rather than rendered.
# ADR 0019.
_NOISE = frozenset({"color_message"})

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
            key: value
            for key, value in vars(record).items()
            if key not in _RESERVED and key not in _NOISE
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

    It also reclaims the server's own loggers, so that the JSON-on-stdout promise
    above covers everything the process says rather than only the parts this
    repository wrote. See `_reclaim`.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    _reclaim(_SERVER_LOGGERS)


# uvicorn's own loggers, which it configures before it calls the application
# factory — verified, which is what makes reclaiming them here possible at all.
_SERVER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _reclaim(names: tuple[str, ...]) -> None:
    """Take back loggers another library configured for itself.

    **Why this is needed at all.** `uvicorn` installs its own handlers on these
    loggers with `propagate = False`, writing plain text to **stderr**. Left
    alone, a container's output is our JSON on stdout interleaved with uvicorn's
    prose on stderr — two formats and two streams, which is precisely what ADR
    0016 chose one of each to avoid. And since nothing in this service logs
    anything yet, in practice the *only* lines a deployment emitted would be the
    ones in the wrong format.

    Clearing the handlers and restoring propagation routes those records through
    the root handler configured above, so "one JSON object per line on stdout"
    is true of everything the process says, not only of the parts we wrote.

    **This reaches into another library's configuration, which is the cost.** It
    is done here rather than through uvicorn's `--log-config` because that would
    be a second place configuring logging — a `dictConfig` file duplicating this
    module. ADR 0019. It depends on uvicorn configuring logging *before* the
    factory runs, which is its behaviour today and not a promise it makes, so
    `test_the_server_loggers_are_reclaimed` fails if that stops holding.
    """
    for name in names:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
