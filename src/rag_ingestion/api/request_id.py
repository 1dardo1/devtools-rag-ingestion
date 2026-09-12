"""Tagging every log line from one request with the same identifier.

ADR 0016 named 4.5 as this belongs here and said why it was not done earlier:
a correlation id with one call site logging is scaffolding. Now there is a
request to correlate.
"""

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from rag_ingestion import observability

HEADER = "X-Request-Id"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Mint an identifier per request and put it in the logs and the response.

    **An inbound `X-Request-Id` is ignored, not honoured.** Trusting one is what
    you want behind a gateway that already assigns them, and it means accepting
    an attacker-chosen string into every log line for that request — unbounded
    in length, and a correlation id a caller can forge is a correlation id that
    can be made to collide with somebody else's. `json.dumps` stops it
    corrupting the log *format*, which is a different problem from it being
    untrustworthy content. Minting our own is the safe default while there is
    exactly one service; honouring an inbound id needs validation first, and
    that belongs with the Phase 13 hardening.

    **`async def`, and it is the only async code in the service.** ADR 0007
    makes ports, use cases, adapters and endpoints synchronous; middleware is
    none of those — it is the ASGI pipeline itself, where there is no
    synchronous alternative. It does no blocking work, so it does not stall the
    event loop, and `test_every_endpoint_is_synchronous` still holds for every
    endpoint.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Set the identifier for the duration of one request."""
        identifier = str(uuid.uuid4())
        token = observability.request_id.set(identifier)
        try:
            response = await call_next(request)
        finally:
            # Reset rather than leave it set: the context is reused, and a stale
            # id on a later request is worse than none at all.
            observability.request_id.reset(token)
        response.headers[HEADER] = identifier
        return response
