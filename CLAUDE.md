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
- The document and its outbox row are written in **the same transaction**. This
  is the single most important invariant in the service. A change that splits
  them is a defect, however clean it looks.
- The relay process is separate from the API process. They do not share a
  lifecycle.
- Domain and use-case tests use in-memory fakes. Integration tests use real
  containers. Do not mock the PostgreSQL driver.

## Current phase

**Phase 0 — Environment.** Nothing built yet.

Next unit of work: project scaffold with `src/` layout, `uv`, `ruff`, strict
`mypy`, `pytest`. Done when lint, type check and one trivial test all pass.

## The gate

This service must be **deployed with a public URL and green CI** before the
retrieval repository is created. If progress stalls, the correct response is to
finish this service, not to start the next one.
