# 17. The composition root

- **Status:** Accepted
- **Last revised:** 2026-09-12

## Context

`ROADMAP.md` 4.5 asks for "one single place where all the real pieces are plugged
into all the sockets", and `docs/BUILD-PLAN.md` explains what has been waiting
for it: the web layer and the storage chain have been built apart since 4.1 and
"meet for the first time at 4.5".

Four earlier ADRs left instructions here rather than decisions, because each
identified something only this file can get right:

- ADR 0013 and ADR 0014: all three adapters must be built from **one**
  connection, or the atomicity 4.2 provides is silently lost.
- ADR 0015: the connection and the commit must be **per request**, which is why
  the endpoints take their use cases through `Depends`; and a forgotten override
  is a runtime `500`, not a compile error.
- ADR 0016: `observability.configure` is called here, because it is deliberately
  not called on import — and the request identifier it promised belongs here too.

One thing was also still open: ADR 0012 left `alembic.ini` reading `DATABASE_URL`
and this file needs the same variable. It turned out not to be cosmetic.

## Options considered

### The configuration mechanism

`ARCHITECTURE.md` already names it — "settings via Pydantic Settings" — so the
approach was decided; `pydantic-settings` as a dependency was not, and it is one
(`pydantic` does not include it). Approved.

The value over reading `os.environ` by hand is not brevity: **a missing or
malformed setting stops the process from starting** rather than surfacing on the
first request that needed it. `extra="forbid"` extends that to a misspelled
variable, which is the failure configuration is worst at — a setting that quietly
keeps its default.

### One `DATABASE_URL`, two readers

This looked like a question about tidiness and was a real incompatibility.
`env.py` used the variable verbatim, which meant it had to hold SQLAlchemy's
`postgresql+psycopg://` form. **`psycopg.connect` rejects that form outright:**

```
ProgrammingError: missing "=" after "postgresql+psycopg://..." in connection info string
```

So one variable could not serve both readers as things stood.

- **Two variables.** Rejected: two names for one database is how they end up
  disagreeing.
- **`DATABASE_URL` holds SQLAlchemy's form and the service strips the prefix.**
  Rejected: it makes the canonical shape the one only Alembic wants, so `psql`,
  `pg_dump` and every other tool need the value edited by hand.
- **`DATABASE_URL` holds the plain libpq URL and `env.py` adds the dialect.**
  Chosen. The libpq form is what every PostgreSQL tool already accepts, so the
  shared value is the standard one and SQLAlchemy's prefix is the migration
  runner's problem.

### Where the transaction boundary lives

It began as a closure inside `build`, which works and is how most FastAPI
applications are written. **Rejected once it was clear the tests could not reach
it.** A closure can only be exercised by standing up an application and finding a
request that fails in exactly the right place — and as below, no such request
exists. `transaction_per_request(database_url)` is a module-level factory
returning the provider, so a test can advance the generator, write through the
connection, throw into it, and ask a second connection what survived.

Its return type is `Generator`, not `Iterator`: FastAPI *throws* into a `yield`
dependency when the endpoint raises, and `Iterator` makes no such promise. The
wider type would have hidden from the tests the very mechanism they depend on.

### Whether an inbound `X-Request-Id` is honoured

Rejected. Trusting one is what you want behind a gateway that already assigns
them, and it means accepting an attacker-chosen string into every log line for
that request — unbounded in length, and a correlation id a caller can forge is one
that can be made to collide with somebody else's. `json.dumps` stops it
corrupting the log *format*, which is a different problem from it being
untrustworthy content. Minting our own is the safe default while there is one
service; honouring an inbound id needs validation, and that belongs with Phase 13.

The middleware is `async def`, and it is the only async code in the service. ADR
0007 makes ports, use cases, adapters and endpoints synchronous; middleware is
none of those — it is the ASGI pipeline, where there is no synchronous
alternative. It does no blocking work, and `test_every_endpoint_is_synchronous`
still holds for every endpoint.

### `mypy` and `Settings()`

`Settings()` with no arguments is a false positive: `database_url` is required and
`pydantic-settings` fills it from the environment, which `mypy` cannot see.

- **`plugins = ["pydantic.mypy"]`.** The fix the library ships, and it removes the
  warning cleanly. **Rejected on evidence.** With the plugin enabled, `mypy`
  stopped reporting a genuinely wrong argument type to a model constructor
  (`CreateCollectionRequest(name=123)`), which plain `mypy` catches. It trades one
  false positive for a lost true one, which is the wrong direction.
- **One `# type: ignore[call-arg]`** at the single construction site. Chosen,
  with the reason written beside it.

## Decision

`config.py` holds `Settings`. `main.py` holds `transaction_per_request` and
`build(settings=None)` — taking settings as an argument so a test supplies them
rather than arranging an environment, with `None` meaning "read the environment",
which is what a deployment does.

`build` configures logging, creates the app, adds the request-id middleware, and
overrides all three providers. Each provider depends on `unit_of_work`, and
FastAPI caches a dependency per request, so all three adapters receive the **same**
connection.

`SystemClock` is the `Clock` port's production implementation: three lines,
always UTC.

## Consequences

**Positive.** Phase 4's completion criterion is now half met and verified by
machine rather than by hand: `ROADMAP.md` asks that "posting a document over HTTP
produces a row in Postgres and a message in Redis", and
`test_a_document_posted_over_http_reaches_postgres_with_its_outbox_row` proves
the PostgreSQL half, outbox row included, with `published_at` still null. The
Redis half is 4.3.

**Mutations confirm the wiring claims.** Building the publisher on its own
connection fails two tests; never committing fails six.

**Negative, and it corrected a test that was lying.** An earlier version of this
work had two tests called `..._leaves_nothing_behind` which were presented as
proving the rollback. They did not: **every domain refusal is raised before the
first write** — `IngestDocument` checks the rules before it stores anything — so
there was nothing to roll back, and removing the rollback left them green. They
have been renamed to claim only what they prove, and
`TestTheTransactionBoundaryItself` drives the generator directly to cover the
rollback for real.

**Negative: the explicit `rollback()` is redundant.** `close()` in the `finally`
already discards an open transaction — verified against a real server — so
removing the `rollback()` changes nothing observable and no test can distinguish
the two. It is kept as documentation at the point of decision, not as behaviour,
and this paragraph exists so nobody later mistakes it for load-bearing.

**Negative: no connection pool.** One connection per request means a TCP
connection and authentication handshake each time. Deferred on principle 10 of
`ARCHITECTURE.md` — "no optimization before measurement" — and there is nothing
to measure yet. `psycopg-pool` is the obvious answer when there is.

**Negative: a forgotten override is still only caught at runtime.** The test that
touches all three routes is the whole of the protection, and it works by
exercising every route rather than by anything structural.
