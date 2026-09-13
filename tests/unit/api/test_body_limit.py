"""The cap that refuses a request before its body is read.

ADR 0015 recorded, as a gap rather than a trade-off, that the size limit was
enforced after the body had been read. These tests are what closes it, so they
are written to fail if the refusal ever moves back behind the read: the ones
that matter assert *that nothing was read*, not merely that the status was
`413`. A `413` arriving after 500 MB is the bug, and it looks identical from the
status line.
"""

import asyncio
import json
from http import HTTPStatus
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import Message

from rag_ingestion.api import body_limit
from rag_ingestion.api.body_limit import (
    BodySizeLimitMiddleware,
    RequestBodyTooLargeError,
    wire_size_for,
)
from rag_ingestion.config import Settings
from rag_ingestion.domain.limits import IngestionLimits

CAP = 1_000

# A module constant because `ruff`'s TRY003 and EM101 forbid a literal in a raise.
_MUST_NOT_BE_REACHED = "the application must not be reached"


class TestTheGuardThatKeepsTheTwoLimitsApart:
    """The cap is on the wire; the domain's limit is on decoded content.

    They are different numbers measuring different things, and the failure mode
    if they drift is silent: the service would answer `413` to documents the
    domain accepts, with a status indistinguishable from a legitimate refusal.
    """

    def test_the_body_cap_cannot_refuse_a_document_the_domain_accepts(self) -> None:
        largest_legal_document = IngestionLimits().max_document_size_in_bytes
        on_the_wire = wire_size_for(largest_legal_document)

        assert Settings(database_url="postgresql:///x").max_body_bytes > on_the_wire, (
            "The cap would refuse a document the domain accepts. Raise"
            " max_body_bytes, or lower the domain's max_document_size_in_bytes."
        )

    def test_base64_expansion_is_four_characters_per_three_bytes(self) -> None:
        assert wire_size_for(3) == 4
        # Padded, not truncated: one byte still costs a full quantum.
        assert wire_size_for(1) == 4
        assert wire_size_for(4) == 8


def _echo_app() -> Starlette:
    """An application that reads the body and reports how much it saw.

    Deliberately minimal. The point under test is the middleware, and the real
    application's dependencies would make "was the body read?" much harder to
    see than it is here.
    """

    async def echo(request: Request) -> JSONResponse:
        body = await request.body()
        return JSONResponse({"read": len(body)})

    return Starlette(routes=[Route("/", echo, methods=["POST"])])


def _client(app: Starlette, *, max_bytes: int = CAP) -> TestClient:
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    return TestClient(app)


class TestAnOverSizedBodyIsRefused:
    def test_a_declared_length_over_the_cap_is_refused(self) -> None:
        response = _client(_echo_app()).post("/", content=b"x" * (CAP + 1))

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert response.json()["code"] == body_limit.CODE

    def test_a_body_at_the_cap_is_allowed_through(self) -> None:
        response = _client(_echo_app()).post("/", content=b"x" * CAP)

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"read": CAP}

    def test_the_refusal_says_which_limit_was_exceeded(self) -> None:
        response = _client(_echo_app()).post("/", content=b"x" * (CAP + 1))

        assert str(CAP) in response.json()["detail"]


class TestNothingIsReadBeforeTheRefusal:
    """The property the whole unit exists for.

    A test that only checked the status would pass against the behaviour ADR
    0015 called a gap, where the `413` arrives after the bytes are in memory.
    """

    def test_the_application_is_never_called_for_a_declared_over_sized_body(
        self,
    ) -> None:
        reached = False

        async def record(request: Request) -> JSONResponse:
            nonlocal reached
            reached = True
            return JSONResponse({})

        app = Starlette(routes=[Route("/", record, methods=["POST"])])

        response = _client(app).post("/", content=b"x" * (CAP + 1))

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert not reached, (
            "The request reached the application, so the body was read before"
            " being refused — which is the defect this unit closes."
        )

    def test_receive_is_not_awaited_for_a_declared_over_sized_body(self) -> None:
        """Straight at the ASGI interface, with no server in between.

        `receive` is the only way a body can arrive. If it is never awaited, no
        byte of the body was read — which is a stronger statement than any
        response-level assertion can make.
        """
        awaited = False

        async def receive() -> dict[str, Any]:
            nonlocal awaited
            awaited = True
            return {"type": "http.request", "body": b"", "more_body": False}

        sent: list[Message] = []

        async def send(message: Message) -> None:
            sent.append(message)

        async def never_called(scope: Any, receive: Any, send: Any) -> None:
            raise AssertionError(_MUST_NOT_BE_REACHED)

        middleware = BodySizeLimitMiddleware(never_called, max_bytes=CAP)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"content-length", str(CAP + 1).encode())],
        }

        asyncio.run(middleware(scope, receive, send))

        assert not awaited, "the body was read despite the declared length"
        assert sent[0]["status"] == int(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        assert json.loads(sent[1]["body"])["code"] == body_limit.CODE


class TestABodyWithNoDeclaredLength:
    """`Transfer-Encoding: chunked` declares no length, so counting is the only way.

    The exposure on this path is bounded by the cap rather than by the caller's
    honesty — which is weaker than refusing before reading, and is the honest
    shape of the problem rather than a shortcoming of the implementation.
    """

    def test_a_chunked_body_over_the_cap_is_refused(self) -> None:
        def chunks() -> Any:
            for _ in range(4):
                yield b"x" * (CAP // 2)

        app = _echo_app()
        body_limit.register(app)  # type: ignore[arg-type]
        client = _client(app)

        response = client.post("/", content=chunks())

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert response.json()["code"] == body_limit.CODE

    def test_a_chunked_body_under_the_cap_is_allowed_through(self) -> None:
        def chunks() -> Any:
            yield b"x" * 10
            yield b"x" * 10

        response = _client(_echo_app()).post("/", content=chunks())

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"read": 20}

    def test_a_lying_content_length_does_not_buy_more_than_the_cap(self) -> None:
        """A small declared length does not license a large body.

        Path 1 waves this request through, so path 2 is the only thing standing
        between a caller who lies and unbounded memory. Driven at raw ASGI
        because an HTTP client cannot be made to lie: `httpx` computes
        `Content-Length` from the body it is given.
        """
        delivered = 0

        async def greedy(scope: Any, receive: Any, send: Any) -> None:
            while True:
                await receive()

        async def receive() -> dict[str, Any]:
            nonlocal delivered
            delivered += 1
            return {"type": "http.request", "body": b"x" * CAP, "more_body": True}

        async def send(message: Message) -> None:
            return None

        middleware = BodySizeLimitMiddleware(greedy, max_bytes=CAP)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"content-length", b"1")],
        }

        with pytest.raises(RequestBodyTooLargeError):
            asyncio.run(middleware(scope, receive, send))

        assert delivered == 2, (
            "the count must trip on the chunk that crosses the cap, not later:"
            f" {delivered} chunks of {CAP} bytes were delivered"
        )


class TestWhatTheMiddlewareLeavesAlone:
    def test_a_request_with_no_body_passes_through(self) -> None:
        async def ok(request: Request) -> JSONResponse:
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/", ok, methods=["GET"])])

        response = _client(app).get("/")

        assert response.status_code == HTTPStatus.OK

    def test_a_malformed_content_length_falls_through_to_counting(self) -> None:
        """A junk header is not a length, and is not grounds for a `413` either.

        Answering `413` on it would refuse a request on a question the header
        could not answer; the framing error belongs to the server below.
        """
        assert (
            body_limit._declared_length(
                {"type": "http", "headers": [(b"content-length", b"not-a-number")]}
            )
            is None
        )

    def test_a_missing_content_length_reads_as_absent(self) -> None:
        assert body_limit._declared_length({"type": "http", "headers": []}) is None
