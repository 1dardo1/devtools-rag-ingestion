"""That the real application's cap runs before anything else it does.

A unit test, with no database anywhere near it, and that is the evidence rather
than a convenience: `build` is given a connection string pointing at nothing. If
an over-sized request is answered `413` anyway, the refusal happened **before**
`psycopg.connect` was reached — and therefore before the body was read, before a
transaction was opened, and before any use case existed.

Run against the real `build`, not a hand-assembled application, because the thing
that can break is the ordering in `main.py`: Starlette applies middleware in
reverse, so the cap has to be added *last* to run *first*, and nothing in the
type system says so.
"""

import logging
from collections.abc import Iterator
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from rag_ingestion.api import body_limit
from rag_ingestion.api.body_limit import BodySizeLimitMiddleware
from rag_ingestion.api.request_id import HEADER
from rag_ingestion.config import Settings
from rag_ingestion.main import build

# Pointing at nothing, on purpose. Any test here that reaches the database fails
# with a connection error rather than quietly passing for the wrong reason.
NOWHERE = "postgresql://nobody@127.0.0.1:1/nothing"

CAP = 2_048


@pytest.fixture(autouse=True)
def _leave_the_root_logger_as_it_was() -> Iterator[None]:
    """Put the root logger back exactly as it was found, handlers and level.

    `build` calls `observability.configure`, so every test in this file mutates
    the root logger. The same guard as `tests/unit/test_observability.py`, and
    for the same reason: a handler left bound to `pytest`'s capture buffer prints
    "I/O operation on closed file" after a green run, which is how PR #33
    shipped a defect past green CI.
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
def client() -> TestClient:
    """The real service, wired to a database that is not there."""
    settings = Settings(database_url=NOWHERE, max_body_bytes=CAP)
    return TestClient(build(settings))


class TestTheCapRunsBeforeAnythingReadsTheBody:
    def test_an_over_sized_document_is_refused_without_reaching_the_database(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/collections/11111111-1111-4111-8111-111111111111/documents",
            content=b"x" * (CAP + 1),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert response.json()["code"] == body_limit.CODE

    def test_the_cap_is_the_outermost_middleware(self, client: TestClient) -> None:
        """Structural, and it is what the behavioural test above depends on.

        `add_middleware` inserts each middleware at the front of
        `user_middleware`, and the stack is built by wrapping that list in
        reverse — so the front of the list is the outermost layer, and the
        *last* middleware added is the *first* to run.
        """
        added = [entry.cls for entry in client.app.user_middleware]  # type: ignore[attr-defined]

        # Index 0, not -1: `add_middleware` *inserts at the front*, and
        # `build_middleware_stack` wraps the list in reverse, so the front of the
        # list is the outermost layer. Verified in Starlette 1.6.0's source
        # rather than assumed — an earlier version of this test asserted `[-1]`
        # and failed.
        assert added[0] is BodySizeLimitMiddleware, (
            "the cap is no longer the outermost middleware, so something now runs"
            f" before it: {added}"
        )

    def test_a_request_under_the_cap_gets_past_the_cap(
        self, client: TestClient
    ) -> None:
        """The cap must not be the thing that refuses a legitimate request.

        This one *is* expected to reach the database and fail there, and that
        failure is the assertion: `TestClient` re-raises a server-side exception,
        so a connection error escaping proves the request was allowed through to
        the point of opening a transaction. A `413` here would mean the cap fired
        on a request it should have passed.
        """
        with pytest.raises(Exception, match="connect"):
            client.post(
                "/collections/11111111-1111-4111-8111-111111111111/documents",
                content=b'{"not": "valid"}',
                headers={"content-type": "application/json"},
            )

    def test_the_refusal_carries_no_request_identifier(
        self, client: TestClient
    ) -> None:
        """The one cost of putting the cap outermost, stated rather than hidden.

        `RequestIdMiddleware` runs *inside* the cap, so a request the cap refuses
        never reaches it and the response carries no `X-Request-Id`. That is the
        trade made knowingly: reading the body to tag it would defeat the cap.
        Asserted so the behaviour is recorded and a future change to the ordering
        has to come past this test.
        """
        response = client.post(
            "/collections/11111111-1111-4111-8111-111111111111/documents",
            content=b"x" * (CAP + 1),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert HEADER not in response.headers
