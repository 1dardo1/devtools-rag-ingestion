"""The logging mechanism: one JSON object per line, and nothing lost on the way."""

import io
import json
import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest

from rag_ingestion.observability import configure


@pytest.fixture(autouse=True)
def _leave_the_root_logger_as_it_was() -> Iterator[None]:
    """Put the root logger back exactly as it was found, handlers and level.

    `logging.basicConfig(force=True)` looks like the obvious reset and is not
    good enough. It *installs a new handler* bound to whatever `sys.stderr` is
    at that moment, which under `pytest` is a capture buffer the session closes
    when it ends. Anything logged after that — `testcontainers` reaping a
    container at interpreter exit — then dies with "I/O operation on closed
    file", printed after a green run.

    It was also leaving the root level at whatever the last test set, which is
    what let third-party `DEBUG` records through in the first place.

    Restoring the snapshot adds no handler of its own, so nothing ends up bound
    to a stream that is about to be closed.
    """
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


@pytest.fixture
def stream() -> io.StringIO:
    """A configured logger writing somewhere a test can read."""
    captured = io.StringIO()
    configure(stream=captured)
    return captured


def _lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_a_record_becomes_one_json_object(stream: io.StringIO) -> None:
    logging.getLogger("rag_ingestion.test").info("a document arrived")

    lines = _lines(stream)

    assert len(lines) == 1
    assert lines[0]["level"] == "INFO"
    assert lines[0]["logger"] == "rag_ingestion.test"
    assert lines[0]["message"] == "a document arrived"
    assert lines[0]["timestamp"].endswith("+00:00")


def test_percent_style_arguments_are_rendered(stream: io.StringIO) -> None:
    # `ruff`'s G004 forbids f-strings in logging calls so that formatting is
    # deferred to the formatter. This is the test that the formatter does it.
    logging.getLogger("rag_ingestion.test").info("stored %s in %s", "doc", "redis-docs")

    assert _lines(stream)[0]["message"] == "stored doc in redis-docs"


def test_extra_fields_are_nested_under_context(stream: io.StringIO) -> None:
    document_id = uuid4()

    logging.getLogger("rag_ingestion.test").info(
        "ingested", extra={"document_id": str(document_id), "size_in_bytes": 42}
    )

    line = _lines(stream)[0]
    assert line["context"] == {
        "document_id": str(document_id),
        "size_in_bytes": 42,
    }


def test_an_extra_cannot_corrupt_the_envelope(stream: io.StringIO) -> None:
    logging.getLogger("rag_ingestion.test").warning(
        "careless", extra={"level": "SHOUTING", "logger": "somewhere-else"}
    )

    line = _lines(stream)[0]
    # Nesting is what makes this structural rather than a documented hazard.
    assert line["level"] == "WARNING"
    assert line["logger"] == "rag_ingestion.test"
    assert line["context"]["level"] == "SHOUTING"


def test_context_is_absent_rather_than_empty(stream: io.StringIO) -> None:
    logging.getLogger("rag_ingestion.test").info("nothing to add")

    assert "context" not in _lines(stream)[0]


def test_an_unserialisable_value_does_not_raise(stream: io.StringIO) -> None:
    class Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    logging.getLogger("rag_ingestion.test").info("odd", extra={"thing": Opaque()})

    # Lossy on purpose: a logging call that throws takes down the request it
    # was describing.
    assert _lines(stream)[0]["context"]["thing"] == "<opaque>"


_BROKER_DOWN = "the broker is down"


def test_an_exception_is_logged_with_its_traceback(stream: io.StringIO) -> None:
    try:
        raise RuntimeError(_BROKER_DOWN)  # noqa: TRY301 - raising is the test
    except RuntimeError:
        logging.getLogger("rag_ingestion.test").exception("could not publish")

    line = _lines(stream)[0]
    assert line["level"] == "ERROR"
    assert "RuntimeError: the broker is down" in line["exception"]
    assert "Traceback" in line["exception"]


def test_a_newline_in_a_message_does_not_break_the_line_per_record_contract(
    stream: io.StringIO,
) -> None:
    logging.getLogger("rag_ingestion.test").info("first\nsecond")

    # One record must stay one line, or a log shipper reading line by line
    # would see half a JSON object.
    assert len(stream.getvalue().splitlines()) == 1
    assert _lines(stream)[0]["message"] == "first\nsecond"


def test_a_level_below_the_threshold_is_not_logged(stream: io.StringIO) -> None:
    logging.getLogger("rag_ingestion.test").debug("too quiet to hear")

    assert _lines(stream) == []


def test_configuring_twice_does_not_log_twice() -> None:
    captured = io.StringIO()
    configure(stream=captured)
    configure(stream=captured)

    logging.getLogger("rag_ingestion.test").info("once")

    # Alembic's env.py also configures logging when migrations run in-process,
    # so this is not a hypothetical. The autouse fixture restores the root
    # logger afterwards; this test must not reset it by hand.
    assert len(_lines(captured)) == 1


def test_the_level_can_be_lowered(stream: io.StringIO) -> None:
    configure(level=logging.DEBUG, stream=stream)

    logging.getLogger("rag_ingestion.test").debug("now audible")

    assert _lines(stream)[0]["level"] == "DEBUG"
