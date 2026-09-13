# CLAUDE.md — devtools-rag-ingestion

You are working on the **ingestion service** of the Devtools RAG system.

## Read first

1. `docs/COLLABORATION.md` — the working agreement. It overrides your defaults.
   Propose before implementing. Never commit to `main`. Every change goes through
   a pull request. Every proposal names a rejected alternative.
2. `docs/ARCHITECTURE.md` — the full system: three repositories, why they are
   split, and the build order.
3. `docs/ROADMAP.md` — the phases this repository must deliver, in order.
4. `docs/adr/` — decisions already made here. System-wide decisions live in
   `devtools-rag-contracts/docs/adr/`.

## What this repository is

The write path. It accepts documents over HTTP, enforces domain rules, persists
raw content in PostgreSQL, and publishes a `DocumentIngested` event through a
transactional outbox.

The corpus is developer documentation for the system's own stack — FastAPI,
Pydantic v2, Qdrant, `uv`, Redis Streams, pytest. See ADR 0005 in the contracts
repository for why. **This service does not care what the documents are about.**
The corpus affects exactly one thing here: the metadata fields carried alongside
each document (`source_library`, `library_version`, `doc_type`, `source_url`).
Nothing else in this repository is corpus-specific, and nothing else should
become so.

It is a hexagonal-architecture service in Python: domain, ports, use cases,
adapters, with the dependency arrow pointing inward.

## What this repository is NOT

- **It knows nothing about AI.** No embeddings, no chunking, no vector store, no
  LLM client. If a proposal mentions any of these, the boundary has been crossed
  and the answer is no.
- It does not read from the retrieval service's store, and does not call it.
- It does not decide how documents are indexed. It only records that they exist.

## Rules specific to this repository

- The `domain/` package imports nothing external. No FastAPI, no SQLAlchemy, no
  Redis client. If an external type seems necessary, a port is missing.
- Ports are `typing.Protocol`, not abstract base classes.
- **Ports, use cases and adapters are synchronous.** FastAPI is async-native, so
  `async def` is the reflex; it was examined and rejected in ADR 0007. Endpoints
  are declared `def`. Bridging with `asyncio.run()` inside a request is a defect,
  not a compromise.
- Time is a port. Nothing in the domain calls `datetime.now()`; the instant is
  supplied by a `Clock`, so a test can name the moment it expects.
- The document and its outbox row are written in **the same transaction**. This
  is the single most important invariant in the service. A change that splits
  them is a defect, however clean it looks.
- The relay process is separate from the API process. They do not share a
  lifecycle.
- Domain and use-case tests use in-memory fakes. Integration tests use real
  containers. Do not mock the PostgreSQL driver. The containers are started by
  the tests themselves via `testcontainers`, and any test that starts one is
  marked `@pytest.mark.integration` so the unit suite still runs without a
  Docker daemon. ADR 0011.

## Current phase

**Phase 2 is complete.** Phases 0, 1 and 2 are merged, and Phase 4 is complete
except 4.3.

Done so far:

- **Phase 0.** Scaffold on Python 3.14 with `uv`, `ruff` (23 rule families),
  `mypy --strict` over `src` and `tests`, and `pytest`. CI runs all four on
  every pull request and every push to `main`; `main` is protected by a ruleset
  and the check is required.
- **Phase 1.** The domain: 14 modules, zero external imports. Value objects,
  entities, the ingestion rules, the `DocumentIngested` event, and the four
  ports (`DocumentRepository`, `CollectionRepository`, `EventPublisher`,
  `Clock`).
- **Phase 2.** The three use cases — `IngestDocument`, `CreateCollection`,
  `GetIngestionStatus` — running end to end against in-memory fakes with no
  infrastructure present. `tests/unit/application/test_phase_two_together.py`
  composes all three and is the phase's completion criterion in one file.
- **The schema.** Alembic scaffolding in `src/rag_ingestion/migrations`, and
  revision `0001` creating `collections`, `documents` and `outbox`. Recorded in
  ADR 0012. The first integration tests live alongside it and run against a
  real container.
- **4.1, the PostgreSQL adapter.** `PostgresDocumentRepository` and
  `PostgresCollectionRepository` in `infrastructure/postgres/`, over psycopg 3
  with hand-written SQL. **They take a connection and never commit** — ADR 0013
  says why, and that choice is what leaves 4.2 room to put the outbox row in the
  document's transaction without rewriting anything here.
- **4.2, the outbox.** `PostgresOutboxEventPublisher` writes one row per event
  on the connection it is given — the document's connection — so the two are one
  transaction. **The invariant is proved through the real `IngestDocument`**, not
  through the adapters in isolation: `TestTheDocumentAndItsOutboxRowAreAtomic`.
  ADR 0014 records the payload shape and why Phase 3 still owns the contract.
- **4.4, the HTTP layer.** `api/` with five modules: Pydantic schemas, providers
  that raise, the refusal table, three endpoints and `create_app()`. Content
  arrives base64 in JSON; `202` for an accepted document, never `201`. ADR 0015.
  **It ships wired to nothing on purpose** — the web layer and the storage chain
  meet for the first time at 4.5.
- **Logging.** `observability.py`: the standard library's `logging`, one JSON
  object per line on stdout, `extra` nested under `context` so it cannot corrupt
  the envelope. ADR 0016 — which also records that this settles the *mechanism*
  only, and that making the relay's silence legible is a separate decision due
  before 4.3.
- **4.5, the composition root.** `config.py` (Pydantic Settings) and `main.py`:
  `transaction_per_request` is the service's entire transaction boundary, and
  `build()` wires all three adapters onto one per-request connection, configures
  logging and adds the request-id middleware. ADR 0017. **Phase 4's completion
  criterion is half met and machine-verified** — posting a document over HTTP
  produces the row *and* its outbox row; the Redis half is 4.3.
- **The body-size cap.** `api/body_limit.py`: a pure-ASGI middleware added *last*
  in `build` so it runs *first*, refusing an over-sized request **before reading
  it**. This closes the gap ADR 0015 recorded as "a real gap rather than a
  trade-off" and is written up in ADR 0018. Two numbers now describe sizes and
  they are not the same: `max_document_size_in_bytes` is 5 MiB of *decoded
  content* and is a domain rule; `max_body_bytes` is 7 MiB *on the wire* and is a
  transport rule, larger because base64 expands by a third. Both answer `413`;
  the `code` field is what tells `document_too_large` from `request_too_large`.
- **5.1, the container image.** A two-stage `Dockerfile` on `python:3.14-slim`,
  `uv` only in the build stage and pinned to the version CI pins, non-root user,
  one uvicorn worker, and **no migrations at container start** — replicas would
  race and a failed migration would be a crashloop instead of a visibly failed
  deploy. ADR 0019. **The image is unbuilt: this environment has a Docker client
  with no daemon, so `ROADMAP.md` 5.1's "done when: image builds" is NOT met.**
  **Closed by ADR 0020:** a second CI job, `image`, builds it *and starts it* —
  `docker run` with `DATABASE_URL` pointing at nothing, then polls
  `/openapi.json`, because ADR 0017 opens no connection until a request arrives.
  Building alone would have satisfied the roadmap's wording while leaving the
  likely defects — `PATH`, `CMD`, the non-root user's access to the venv —
  undetected. **The new job is not a required check**; that is the `main`
  ruleset, which lives in the GitHub interface.
- **uvicorn's logs were breaking ADR 0016 before the Dockerfile existed.** It
  configures `uvicorn` and `uvicorn.access` with `propagate: False` and writes
  plain text to **stderr**, so "one JSON object per line on stdout" was false in
  a container — and since nothing else in the service logs yet, the *only* lines
  a deployment emitted were the wrong-format ones. `observability.configure` now
  reclaims those loggers, and the formatter drops uvicorn's `color_message`,
  which duplicates the message with ANSI escapes inside. Verified by running the
  server: nine lines, all JSON on stdout, stderr empty.
- **5.1 is closed, and CI closed it by failing first.** ADR 0020 added an `image`
  job that builds the container and starts it. Its first run was red:
  `OSError: License file does not exist: LICENSE`, because `pyproject.toml` has
  `license = { file = "LICENSE" }` and **hatchling validates that the file
  exists**, while the `Dockerfile` copied `README.md` and not `LICENSE`. ADR 0019
  had reasoned its way to the readme and missed the licence — the same reason
  stated twice in one manifest. **The rule, not the filename: every path
  `pyproject.toml` points at has to be in the image**, because the build backend
  reads the manifest, not the `Dockerfile`.
- **5.2, the compose stack.** `compose.yaml` with `app`, `postgres` and a one-shot
  `migrate` that `app` waits on via `service_completed_successfully`. **That does
  not contradict ADR 0019:** it refused to migrate from the *image's* `CMD` because
  N replicas race and a failed migration becomes a crashloop; Compose starts
  exactly one migrator, to completion, so neither objection reaches it. No Redis
  and no relay — 4.3 is blocked, and a Redis nothing reads from passes its health
  check while making the outbox look drained. `POSTGRES_HOST_AUTH_METHOD=trust`
  with the ports bound to `127.0.0.1`: no secret in the repository because there is
  no secret. A third CI job asserts `docker compose up --wait` and then posts a
  document through the stack, which is what proves `migrate` ran. ADR 0021.
- **`docker compose up --wait` treats a service with no health check as ready when
  its container is merely running**, which is before uvicorn has bound the port. So
  `app` has a health check, probing with `python3` because the image has no `curl`.
  It uses `/openapi.json` for want of a health endpoint — a real gap, and adding
  one is an API change.
- **6.3, secrets via the environment.** `.env.example` plus three guards in
  `tests/unit/test_no_secret_is_committed.py`. **No placeholder allowance**, on
  purpose: the repository contains no credential-shaped string at all, because a
  guard that excuses `PASSWORD` is a guard that can be talked into excusing the
  real thing. It found one on its first run — `config.py`'s `database_url`
  description illustrated the shape with a literal password — and
  `test_the_guard_can_actually_see_a_secret` found a bug in the guard itself:
  **`\b` does not match inside `POSTGRES_PASSWORD`**, because `_` is a word
  character, so the assignment pattern matched nothing. ADR 0022.
- Twenty-two ADRs, in `docs/adr/`. 289 tests — 238 unit, 51 integration.

**Next: 7.2, the public deployment — and it is the gate.** `docs/BUILD-PLAN.md`'s
graph has `U52 --> U72` and `U63 --> U72`; both are now done, so nothing blocks it.
`CLAUDE.md` ranks the gate above everything else: green CI is done, the public URL
is the only half still open. Everything left in Phase 6 (coverage, more integration
tests) is polish beside it. **7.2 needs decisions only Carlos can make** — which
platform, and an account on it — plus real credentials, which is the first time this
repository has had a secret to protect and therefore the moment ADR 0022 says to
revisit the secret scanner.

**4.3, the relay, is blocked twice over.** The graph reads
`EXT3 --> U43`, so it waits on Phase 3 in `devtools-rag-contracts`, and ADR 0016
split out "making the relay's silence legible" as a decision also due before it.
**Phase 5 (containers) is not blocked** and is the nearer half of the gate: the
public URL is the only part still open.

**`!cancelled()` belongs in `checks` and not in `image`.** In `checks` the steps
are independent checks and one run should report every failure. In `image` they are
a sequence, and copying the condition there made a failed build run `docker run`
against a nonexistent image and then poll for thirty seconds, burying the real
error. ADR 0020.

**Four guards now hold rules that used to rely on review.** Two in
`tests/unit/api/test_routes.py`: `test_every_endpoint_is_synchronous` fails if
any endpoint is declared `async def` (ADR 0007), and
`test_the_application_ships_unwired` fails if 4.4 starts satisfying its own
dependencies. Two more for the cap:
`test_the_body_cap_cannot_refuse_a_document_the_domain_accepts` fails if the wire
cap is ever set where it would shadow the domain rule, and
`test_the_cap_is_the_outermost_middleware` fails if anything is added after it in
`build`. **`add_middleware` inserts at the *front* of `user_middleware`** and the
stack wraps that list in reverse, so the last middleware added is the first to
run — verified in Starlette 1.6.0's source after an earlier version of that test
asserted the opposite index and failed.

**The composition root is `main.py`, and ADR 0017 records what it had to get
right.** Two traps worth carrying forward:

1. **Every domain refusal is raised before the first write.** So a test that
   posts a duplicate and checks nothing was stored does **not** exercise the
   rollback — an earlier version of 4.5's tests claimed it did and was wrong.
   Reaching the rollback means driving the generator
   `transaction_per_request` returns, which is why it is module-level.
2. **`DATABASE_URL` holds a plain libpq URL.** `psycopg.connect` rejects
   SQLAlchemy's `postgresql+psycopg://` form outright, so `env.py` adds that
   prefix itself. One variable, one canonical shape.

**How Phase 4 reaches PostgreSQL is settled:** psycopg 3 with hand-written SQL,
migrated by Alembic running `op.execute` with no declared models. ADR 0010
records it, including why the SQLAlchemy ORM was rejected on evidence — it
cannot map these entities, because `slots=True` breaks the identity map's weak
references at runtime rather than at declaration. **The schema those migrations
create is ADR 0012**, which is the document to read before writing a line of the
adapter: it says what every constraint restates and, more usefully, what the
schema deliberately does not enforce.

**Logging is settled — the mechanism, at least.** The standard library's
`logging`, JSON on stdout, ADR 0016. Never an f-string in a logging call:
`ruff`'s G004 forbids it so that formatting is deferred to the formatter, and
structured fields go in `extra`, where they land under `context`.

**What is still open is the half ADR 0016 split out:** a crashed relay and an
idle relay both write nothing, so silence is still ambiguous. Due before 4.3,
tracked in `docs/BUILD-PLAN.md`.

**The transaction boundary is the caller's, everywhere.** No adapter commits.
If a repository or publisher calls `commit()`, the invariant above is gone and
the test that proves it is `TestTheTransactionBelongsToTheCaller`. ADR 0013.

**Migrations are run, not written from memory.** `alembic revision
--autogenerate` does not work here and never will — ADR 0010 declined declared
models, so there is no metadata to diff. Write the SQL by hand, then prove it:
upgrade, probe each constraint with a row that violates it, downgrade, upgrade
again.

**Keep this section current.** It is the first thing a new session reads, and a
stale one sends the work in the wrong direction.

## The gate

This service must be **deployed with a public URL and green CI** before the
retrieval repository is created. If progress stalls, the correct response is to
finish this service, not to start the next one.

Green CI is done (`ROADMAP.md` 0.2). The public URL is not, and it is the only
half of the gate still open.
