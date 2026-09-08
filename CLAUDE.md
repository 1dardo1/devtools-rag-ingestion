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
  containers. Do not mock the PostgreSQL driver.

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
- Nine ADRs, in `docs/adr/`. 179 tests.

**Next: Phase 3, and it happens in `devtools-rag-contracts`, not here.** It
turns the `DocumentIngested` shape agreed in 1.4 into the published schema.
Return here afterwards for Phase 4.

Two decisions are due before Phase 4 starts, both recorded as `[+]` items in
`docs/BUILD-PLAN.md` and both cheap now:

- **A migration tool**, before 4.1. Note that it depends on a prior choice
  nobody has made: **whether the PostgreSQL adapter uses an ORM or raw SQL.**
  Nothing in the documentation decides this — the domain is forbidden from
  importing SQLAlchemy, but that is a rule about a layer, not a choice of
  technology for the adapters. Alembic is the natural answer with SQLAlchemy
  and the wrong one without it, so settle the adapter first.
- **Logging and error reporting**, before 4.5. The relay in 4.3 runs
  unattended, where silence and success look identical.

**Keep this section current.** It is the first thing a new session reads, and a
stale one sends the work in the wrong direction.

## The gate

This service must be **deployed with a public URL and green CI** before the
retrieval repository is created. If progress stalls, the correct response is to
finish this service, not to start the next one.

Green CI is done (`ROADMAP.md` 0.2). The public URL is not, and it is the only
half of the gate still open.
