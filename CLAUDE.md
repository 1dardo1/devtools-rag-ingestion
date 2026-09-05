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

**Phase 2 — Use cases.** Phases 0 and 1 are complete and merged.

Done so far:

- **Phase 0.** Scaffold on Python 3.14 with `uv`, `ruff` (23 rule families),
  `mypy --strict` over `src` and `tests`, and `pytest`. CI runs all four on
  every pull request and every push to `main`; `main` is protected and the
  check is required.
- **Phase 1.** The domain: 14 modules, zero external imports, 132 tests. Value
  objects, entities, the ingestion rules, the `DocumentIngested` event, and the
  four ports (`DocumentRepository`, `CollectionRepository`, `EventPublisher`,
  `Clock`).
- Eight ADRs, in `docs/adr/`.

Next unit of work: **2.1 `IngestDocument`** — the use case that runs the three
policy checks against the repository's answers, stores the document and
publishes the event. Done when it runs end to end against in-memory fakes with
no infrastructure present.

Two questions were deliberately deferred out of Phase 1 and are due here:
whether `Document` needs a `created_at`, and whether `EventPublisher` receives a
built event or stamps `occurred_at` itself.

**Keep this section current.** It is the first thing a new session reads, and a
stale one sends the work in the wrong direction.

## The gate

This service must be **deployed with a public URL and green CI** before the
retrieval repository is created. If progress stalls, the correct response is to
finish this service, not to start the next one.

Green CI is done (`ROADMAP.md` 0.2). The public URL is not, and it is the only
half of the gate still open.
