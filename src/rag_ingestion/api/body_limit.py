"""Refusing a request that is too big to read, before reading it.

ADR 0015 recorded a gap rather than a trade-off: `DocumentTooLargeError` is
raised by the domain, which means the bytes are already in memory, so a caller
sending 500 MB got a `413` *after* the service had read 500 MB. A status code is
not a defence. This module is that defence.

**This does not replace the domain's limit, and the two numbers are deliberately
different.** They measure different things:

- `IngestionLimits.max_document_size_in_bytes` is a rule about a *document*, in
  decoded content bytes. It belongs to the domain and is enforced there.
- The cap here is a rule about a *request*, in bytes on the wire. It belongs to
  the transport, and its only job is to stop the process spending memory on
  something it has already decided to refuse.

The wire is larger than the content: base64 costs four characters per three
bytes, so a document at the domain's 5 MiB limit arrives as roughly 6.7 MiB of
JSON, plus the metadata around it. A cap set to the domain's number would
therefore refuse perfectly legal documents — which is why
`test_the_body_cap_cannot_refuse_a_document_the_domain_accepts` exists and is
the guard that keeps the two in a workable relationship as either changes.

**Pure ASGI, not `BaseHTTPMiddleware`.** Counting a body as it streams means
wrapping `receive`, and `BaseHTTPMiddleware` does not hand that over. Like
`RequestIdMiddleware` this is `async def`: ADR 0007 governs ports, use cases,
adapters and endpoints, and middleware is none of those — it is the ASGI
pipeline, where there is no synchronous alternative.
"""

import json
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CODE = "request_too_large"

_STATUS = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class RequestBodyTooLargeError(Exception):
    """A request body exceeded the cap while it was being read.

    Raised out of the wrapped `receive`, which means it surfaces inside the
    application's own call stack — wherever Starlette is reading the body — and
    so an exception handler registered on the application answers it. That is
    why this is a plain `Exception` and not a `DomainError`: the domain has a
    rule about document size and this is not it. Putting it in the refusal table
    in `error_handling.py` would say the domain refused, when what happened is
    that the transport stopped listening.
    """

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"Request body exceeds the {max_bytes} byte limit.")
        self.max_bytes = max_bytes


class BodySizeLimitMiddleware:
    """Refuse an over-sized request body without buffering it.

    Two paths, because a caller controls which one applies:

    1. **`Content-Length` present and over the cap.** Answered immediately, with
       nothing read. This is the path that matters: it is the one a large upload
       actually takes, and the one that makes the refusal cost nothing.
    2. **No `Content-Length`, or one that lies.** `Transfer-Encoding: chunked`
       declares no length at all, so the only way to know is to count. The bytes
       are counted as they arrive and the request is cut off at the cap, so the
       exposure is bounded by the cap rather than by the caller's honesty.

    A refusal on path 1 replies before the client has finished sending, which
    HTTP allows and which is the entire point; the body is deliberately not
    drained first, since draining it is the work being avoided.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Guard one HTTP request, and stay out of the way of anything else."""
        if scope["type"] != "http":
            # Lifespan and websocket scopes carry no body this could cap.
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _refuse(send, self.max_bytes)
            return

        await self.app(scope, _counting(receive, self.max_bytes), send)


def wire_size_for(content_bytes: int) -> int:
    """How many bytes of base64 a payload of `content_bytes` becomes.

    Four characters per three bytes, rounded up, because base64 pads. This is
    the *content* alone — the JSON envelope and the metadata strings sit on top
    of it, which is why the cap is set above this rather than to it.
    """
    return 4 * ((content_bytes + 2) // 3)


def _declared_length(scope: Scope) -> int | None:
    """Read `Content-Length` from the scope, or `None` if it is absent or junk."""
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                # A malformed header is not a length. Fall through to counting
                # rather than trusting it or refusing on it: the server below
                # will reject the framing, and guessing here would answer the
                # wrong question.
                return None
    return None


def _counting(receive: Receive, max_bytes: int) -> Receive:
    """Wrap `receive` so the body is cut off at the cap as it streams."""
    seen = 0

    async def counted() -> Message:
        nonlocal seen
        message = await receive()
        if message["type"] == "http.request":
            seen += len(message.get("body", b""))
            if seen > max_bytes:
                raise RequestBodyTooLargeError(max_bytes)
        return message

    return counted


async def _refuse(send: Send, max_bytes: int) -> None:
    """Answer `413` directly, in the shape every other refusal takes."""
    body = json.dumps(
        {"code": CODE, "detail": RequestBodyTooLargeError(max_bytes).args[0]}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": int(_STATUS),
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def register(app: FastAPI) -> None:
    """Teach an application to answer the streaming path's refusal.

    Registered on the application rather than added to the refusal table in
    `error_handling.py`, for the reason `RequestBodyTooLargeError` gives: that
    table maps *domain* refusals, and this is the transport refusing.

    Needed only for path 2. Path 1 answers through `send` without the
    application ever being called, so no handler can be involved.
    """
    app.add_exception_handler(RequestBodyTooLargeError, _handle_too_large)


def _handle_too_large(
    request: Request,  # noqa: ARG001 - Starlette's handler signature requires it
    exc: Exception,
) -> JSONResponse:
    """Answer `413` in the same shape as every other refusal.

    Synchronous, like `_handle_domain_error`: Starlette accepts either, and a
    handler that does no awaiting has no reason to be a coroutine.
    """
    return JSONResponse(
        status_code=int(_STATUS), content={"code": CODE, "detail": str(exc)}
    )
