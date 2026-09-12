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

**Phase 2 is complete.** Phases 0, 1 and 2 are merged.

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
- Fifteen ADRs, in `docs/adr/`. 240 tests — 203 unit, 37 integration.

**Next: 4.5, the composition root.** **4.3, the relay, is blocked** — the graph
reads `EXT3 --> U43`, so it waits on Phase 3 in `devtools-rag-contracts`.

**Two guards now hold rules that used to rely on review**, both in
`tests/unit/api/test_routes.py`: `test_every_endpoint_is_synchronous` fails if
any endpoint is declared `async def` (ADR 0007), and
`test_the_application_ships_unwired` fails if 4.4 starts satisfying its own
dependencies.

**Read ADR 0014 and ADR 0015 before building 4.5.** Three things it must get
right, none of which the type checker can check:

1. The atomicity 4.2 proves is only as strong as the wiring — a publisher and a
   repository on two *different* connections typecheck perfectly and are not
   atomic. Build all three adapters from **one** connection and commit once.
2. The connection and the commit must be **per request**, which is why the
   endpoints take their use cases through `Depends` rather than holding them.
3. A dependency override it forgets is a runtime `500`, not a compile error.

**How Phase 4 reaches PostgreSQL is settled:** psycopg 3 with hand-written SQL,
migrated by Alembic running `op.execute` with no declared models. ADR 0010
records it, including why the SQLAlchemy ORM was rejected on evidence — it
cannot map these entities, because `slots=True` breaks the identity map's weak
references at runtime rather than at declaration. **The schema those migrations
create is ADR 0012**, which is the document to read before writing a line of the
adapter: it says what every constraint restates and, more usefully, what the
schema deliberately does not enforce.

**One decision is still due before Phase 4 finishes: logging and error
reporting**, before 4.5, recorded as a `[+]` item in `docs/BUILD-PLAN.md`. The
relay in 4.3 runs unattended, where silence and success look identical.

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
