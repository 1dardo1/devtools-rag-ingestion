# 18. The body-size cap

- **Status:** Accepted
- **Last revised:** 2026-09-13

## Context

ADR 0015 recorded one of its consequences as a gap rather than a trade-off:

> the size limit is enforced after the body has been read. `DocumentTooLargeError`
> is raised by the domain, which means the bytes are already in memory; a caller
> sending 500 MB gets a `413` *after* the service has read 500 MB. A status code
> is not a defence.

It also said where the fix belonged and when it was needed: "a body-size cap
belongs at the server or proxy, and Phase 13 is where security hardening lives —
but it is worth saying plainly that nothing here protects against that today, and
that 5.1 deploying this behind something is not optional."

Phase 13 is a long way off and **the gate is a public URL**. The day that URL
exists, "nothing here protects against that today" stops being a note and becomes
an exposure, so the cap is taken now rather than deferred to the phase that owns
hardening in general.

One fact settles the "at the server" half: **`uvicorn` cannot do this.** Its
documented options are `--limit-concurrency`, `--limit-max-requests`,
`--limit-max-requests-jitter`, `--backlog`, `--ws-max-size` (WebSockets only) and
`--h11-max-incomplete-event-size`, which bounds the buffer of an *incomplete
event* — headers — not the body, because h11 delivers the body in chunks. Checked
against uvicorn's own settings documentation rather than assumed.

## Options considered

### Where the cap lives

- **A pure-ASGI middleware in this repository, with the number in `Settings`.**
  Chosen. It is the only option that lives where the tests can see it and does
  not depend on which platform ends up hosting the service.
- **A reverse proxy only** — `client_max_body_size` in a Caddy or nginx in front
  of the service, and whatever the deployment platform imposes in production.
  Architecturally the right home, and free. Rejected because it ends as **two
  numbers**: the one in the compose file and the one the platform enforces, which
  on free tiers is not configurable. Two values for one rule is how they come to
  disagree, which is the failure mode ADR 0017 spent a decision avoiding with
  `DATABASE_URL`. It also puts the only defence outside the repository, where no
  test can reach it. A proxy cap remains the correct *outer* layer once there is
  a proxy; it is not a substitute for this one.
- **Defer to Phase 13 and document it.** The letter of ADR 0015. Rejected on the
  ordering above: the public URL arrives first.

### Which middleware

Starlette 1.6.0 ships `RequestBodyLimitMiddleware` and a `max_body_size` argument
on `Starlette`. **The documented route is unavailable here:** FastAPI 0.141.1
overrides `build_middleware_stack` and omits that middleware, and `FastAPI` neither
accepts `max_body_size` nor carries the attribute. Using Starlette's class means
adding it by hand with `add_middleware`, off its documented path.

Both were run against the same application and measured:

| | Starlette's | This one |
|---|---|---|
| status | `413` | `413` |
| `content-type` | `text/plain; charset=utf-8` | `application/json` |
| body | `Content Too Large` | `{"code": "request_too_large", "detail": …}` |
| application entered | yes, refuses on the first `receive` | no |
| code here to maintain | none | ~150 lines and its tests |

**Neither reads the body**, so on the exposure that matters they are equivalent.

Starlette's was rejected on one difference a client can actually observe: ADR
0015 made `{"code", "detail"}` the shape of every refusal, and said the `code`
field exists because several refusals share a status. `413` is now shared by
exactly two — the domain's `document_too_large` and the transport's
`request_too_large` — which is precisely the case that field was invented for. A
`text/plain` body leaves a client that branches on `code` with nothing for one of
them.

Rejected with its cost acknowledged, because Starlette's is better in two
respects: it is maintained upstream, and it handles a case this one does not (see
Consequences).

### The number

**Not the domain's limit, and deliberately larger.** They measure different
things: `IngestionLimits.max_document_size_in_bytes` is 5 MiB of *decoded
content* and is a domain rule; the cap here is bytes *on the wire* and is a
transport rule. Base64 costs four characters per three bytes, so the largest
legal document arrives as roughly 6.7 MiB of JSON plus its metadata. A cap set to
the domain's figure would refuse documents the domain accepts — and answer `413`
while doing it, indistinguishable from a legitimate refusal.

`max_body_bytes` is therefore 7 MiB, written as a plain number rather than
derived, because a reader of a configuration file should see the figure.
Deriving it would make disagreement impossible; a test makes disagreement
*loud*, which is the same protection with a legible number, and matches how two
other rules in this service are already held —
`test_every_endpoint_is_synchronous` and `test_the_application_ships_unwired`.

## Decision

A pure-ASGI `BodySizeLimitMiddleware` in `api/body_limit.py`, added **last** in
`main.build` so that it runs **first**, with `max_body_bytes` coming from
`Settings` and defaulting to 7 MiB.

Two paths, because the caller decides which applies:

1. **`Content-Length` over the cap** — answered immediately through `send`, with
   the application never called and no byte of the body read. This is the path a
   large upload actually takes and the one that makes the refusal free.
2. **No `Content-Length`, or one that lies** — `Transfer-Encoding: chunked`
   declares no length, so the bytes are counted as they arrive and the request is
   cut off at the cap. `RequestBodyTooLargeError` is raised out of the wrapped
   `receive`, which surfaces inside the application's call stack where an
   exception handler registered by `body_limit.register` answers it.

`RequestBodyTooLargeError` is a plain `Exception`, **not** a `DomainError`, and is
not in the refusal table in `error_handling.py`. That table maps domain refusals;
this is the transport declining to listen. The domain has a rule about document
size and this is not it.

Pure ASGI rather than `BaseHTTPMiddleware` because counting a streaming body
means wrapping `receive`, which `BaseHTTPMiddleware` does not hand over. Like
`RequestIdMiddleware` it is `async def`: ADR 0007 governs ports, use cases,
adapters and endpoints, and middleware is none of those.

## Consequences

**The gap ADR 0015 recorded is closed, and the tests are written to keep it
closed.** A test that only checked for `413` would pass against the old
behaviour, because a `413` after 500 MB looks identical from the status line. So
the tests that matter assert that *nothing was read*:
`test_receive_is_not_awaited_for_a_declared_over_sized_body` drives the raw ASGI
interface and asserts `receive` was never awaited, and
`test_an_over_sized_document_is_refused_without_reaching_the_database` runs the
real `build` against a connection string pointing at nothing — a `413` from that
proves the refusal happened before `psycopg.connect`.

**A refused request carries no `X-Request-Id`.** `RequestIdMiddleware` runs inside
the cap, so a request the cap refuses never reaches it. This is the cost of
putting the cap outermost and it is paid knowingly: reading enough of the request
to tag it would defeat the point. Asserted in
`test_the_refusal_carries_no_request_identifier` so that a change to the ordering
has to come past it.

**Negative: the streaming path does not handle a response that has already
started.** Starlette's implementation does, re-sending through `send` and
tracking `response_started`. Here the refusal is raised and answered by an
exception handler, which would fail if a response were already in flight. It
cannot arise in this service — the body is read while dependencies are being
solved, before any response starts — so the code to handle it would be
untestable. Recorded rather than written, because it is a real difference from
the upstream implementation and the next person comparing them deserves to know
which way it goes.

**Negative: on path 2 the exposure is bounded by the cap rather than by nothing.**
That is weaker than path 1, where nothing is read at all. A caller sending
chunked data still gets one chunk past the cap counted before being cut off, so
the ceiling is the cap plus one chunk, not the cap. This is the honest shape of
the problem rather than a shortcoming of the implementation: without a declared
length there is no way to know the size before reading some of it.

**Negative: a malformed `Content-Length` falls through to counting rather than
being refused.** A junk header is not a length, and answering `413` on it would
refuse a request on a question the header could not answer; the framing error
belongs to the server below. The consequence is that such a request takes the
weaker path.

**Negative: two numbers now describe sizes, and a reader has to know which is
which.** `max_document_size_in_bytes` (domain, decoded content) and
`max_body_bytes` (transport, wire) are easy to confuse, and both produce `413`.
The mitigation is the `code` field distinguishing `document_too_large` from
`request_too_large`, and
`test_the_body_cap_cannot_refuse_a_document_the_domain_accepts` failing if they
are ever set into a relationship where the wire cap shadows the domain rule.

**A proxy cap is still wanted, and is now an outer layer rather than the only
one.** When 5.2 or the deployment puts something in front of this service, a cap
there refuses even earlier — at a process that is not this one. Nothing in this
decision argues against it; what changed is that the service no longer depends on
it existing.
