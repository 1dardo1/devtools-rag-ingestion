# 7. Keep this service's ports synchronous

- **Status:** Accepted
- **Last revised:** 2026-08-30

## Context

FastAPI is async-native, so the reflexive choice is `async def` everywhere. That
reflex deserves examination here, because in Python the choice propagates: an
`async` function can only be awaited from another `async` function, so async
ports make every use case, every test, every in-memory fake and the composition
root async with them. The decision is expensive to reverse in either direction,
and Phase 2 is the last point at which it is cheap in this one.

**Where the waiting actually happens** decides it. One ingestion request is a
single PostgreSQL transaction of four short statements — does this content hash
already exist in the collection, how many documents does it hold, insert the
document, insert the outbox row — each a local round trip of single-digit
milliseconds. The relay process is a loop that reads unpublished rows, writes to
Redis, and marks them sent. **Nothing in this service makes a slow call to a
third party.** No language model, no embedding service, no fetching of remote
documents.

The two deployment models differ less than they appear:

| | Synchronous | Asynchronous |
|---|---|---|
| Concurrency ceiling | the endpoint threadpool, 40 workers by default | the PostgreSQL connection pool |
| Cost of one waiting request | a blocked thread | a suspended coroutine, bytes |

Note where the queue ends up in both cases. With a pool of twenty connections,
an async service can hold thousands of requests in flight but still runs twenty
transactions at a time; the rest are waiting for a connection rather than for a
thread. **Async does not remove the queue, it moves it** — and makes waiting in
it far cheaper. For transactions measured in milliseconds, that saving is real
and small.

`docs/ARCHITECTURE.md` section 2 justifies splitting the system in two on
exactly this ground: ingestion "arrives in bursts, tolerates latency, and is
write-heavy against a relational store", while retrieval "must respond in low
single-digit seconds, is read-heavy, and scales with query volume". The two
services were separated because their load profiles are opposite.

## Options considered

- **Asynchronous ports.** The concurrency ceiling moves from the threadpool to
  the connection pool, and a waiting request costs almost nothing. It is what a
  reader expects of a FastAPI service, which has some presentation value in
  itself. Rejected because the benefit is small for a workload of millisecond
  transactions with no slow outbound calls, while the cost is paid everywhere:
  every use case and every test becomes async, an async test plugin joins the
  toolchain, and stack traces get harder to read at exactly the moment something
  is going wrong.

- **Mixed — synchronous ports with an async adapter,** bridging with
  `asyncio.run()` per call. Rejected outright: it creates and tears down an
  event loop inside a request, and inside an already-running loop it raises.
  This is not a compromise, it is a defect.

- **Synchronous ports.** Chosen.

## Decision

The ports in `rag_ingestion.domain.ports` are synchronous, and so are the use
cases in Phase 2 and the adapters in Phase 4. FastAPI endpoints are declared
`def` rather than `async def`, which makes Starlette run them in its worker
threadpool.

**The retrieval service should be asynchronous**, and for the same reason this
one is not: its queries wait seconds on a language model, which is precisely
where a suspended coroutine beats a blocked thread by orders of magnitude. That
these two services differ here is not an inconsistency — it is the same analysis
applied to two opposite load profiles, and it is the concrete payoff of having
split them.

## Consequences

**Positive.** The use cases stay ordinary functions, testable without a plugin,
a fixture or an event loop, and a failing test produces a stack trace that reads
top to bottom. No new dependency enters the toolchain. Nothing is coloured: any
helper can call any port. The domain was already synchronous and pure, so the
layers agree.

**Negative.** The endpoint threadpool is the concurrency ceiling, and its
default is forty workers. Beyond that, requests queue before reaching the
database, and tail latency grows sooner than it would under async. Each blocked
thread costs a stack.

The sharper risk is a change of workload rather than of volume. If ingestion
ever acquires a slow outbound call — validating against an external service,
fetching a document by URL, calling an antivirus scanner — a single such call
holds a thread for its whole duration, and the ceiling that was comfortable
becomes the bottleneck immediately. Migrating then means rewriting every use
case, every adapter and every test: mechanical work, but wide, and it will
arrive under pressure rather than at leisure.

That is the trade being made: a smaller ceiling now, in exchange for no
complexity and no dependency, on a service whose own architecture document says
it tolerates latency.
