# devtools-rag-ingestion

The write path of the Devtools RAG system: accepts technical documents, enforces
domain rules, stores them, and publishes an event when a document is ready to be
indexed.

> **Status:** early development.

## Why this exists

This service deliberately knows nothing about retrieval, embeddings or language
models. Its only job is to accept documents safely and tell the rest of the
system that they arrived.

The corpus is developer documentation for the stack this system is built on —
FastAPI, Pydantic v2, Qdrant, `uv`, Redis Streams and pytest. That choice is
recorded in
[ADR 0005](../../devtools-rag-contracts/docs/adr/0005-corpus-selection.md); it
constrains the metadata carried with each document and nothing else in this
service.

Documents and their outgoing events are written in a single database
transaction using the transactional outbox pattern, so no document is ever
stored without eventually being announced — even if the broker or the consumer
is unavailable at the time.

## Architecture

Hexagonal, with the dependency arrow pointing inward:

```
src/rag_ingestion/
  domain/          entities, value objects, events, ports — zero external imports
  application/     use cases — depends only on domain
  infrastructure/  adapters — PostgreSQL, outbox relay, Redis publisher
  api/             FastAPI routers and request/response models
```

The distribution is `devtools-rag-ingestion`; the import root is
`rag_ingestion`. See [ADR 0003](docs/adr/0003-src-layout-and-import-root.md).

Design decisions are recorded in [`docs/adr/`](docs/adr/). System-wide decisions
live in the [contracts repository](../../devtools-rag-contracts).

## Stack

Python 3.12 · FastAPI · Pydantic v2 · PostgreSQL · Redis Streams · Docker

## Running locally

<!-- TODO: fill in at Phase 5, when docker compose exists. -->

## Related repositories

- [`devtools-rag-contracts`](../../devtools-rag-contracts) — shared event schemas
- [`devtools-rag-retrieval`](../../devtools-rag-retrieval) — indexing and query answering

## License

MIT
