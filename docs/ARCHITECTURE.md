# Project Context — Devtools RAG System

> **Purpose of this file:** load it as context when starting or resuming work on this system. It describes the full architecture, the build order, and the reasoning behind each decision. Follow the build order strictly — the gates exist to prevent half-finished repositories.

---

## 1. What is being built

A retrieval-augmented generation system over developer documentation, split into two independently deployable services plus one shared contracts package.

The system ingests technical documents, indexes them as vector embeddings, and answers natural-language questions grounded in that corpus.

**This is a portfolio system.** Architectural clarity and operational maturity matter more than feature count. A small system that is deployed, tested, observable and documented beats a large one that is none of those things.

---

## 1.1 Corpus

The system indexes **developer documentation for its own stack**: FastAPI,
Pydantic v2, Qdrant, `uv`, Redis Streams and pytest.

### Why this corpus

- **Evaluation requires familiarity.** Phase 11 depends on writing
  question–answer pairs with known-correct answers and judging whether the
  system is wrong. A corpus the author cannot verify makes evaluation
  impossible, and evaluation is the most valuable part of the system.
- **It provides a measurable baseline.** Base language models reliably confuse
  Pydantic v1 and v2 APIs, and `uv` post-dates most training cutoffs.
  Version-sensitive questions therefore produce a comparison the ungrounded
  model measurably fails — which turns "grounding works" from an assertion into
  a number.
- **It is useful during development.** The corpus gets used while building the
  thing that indexes it.

### What the corpus does and does not affect

The corpus does **not** change the domain model. Documents and collections are
the domain regardless of subject matter. Entities, deduplication rules, the
state machine, the outbox and every port are identical for any corpus. That
independence is precisely what the architecture demonstrates.

It affects exactly three things, all of them in adapters or configuration:

| Affected | How |
|---|---|
| **Metadata fields** | `source_library`, `library_version`, `doc_type`, `source_url` |
| **Chunking strategy** | Fenced code blocks must never be split. A truncated example is worse than no example. |
| **Evaluation dataset** | Question–answer pairs about these libraries, including version-sensitive cases |

If a proposal claims the corpus requires a change to `domain/` beyond the
metadata fields listed above, that proposal is wrong.

---

## 2. Topology

```
┌──────────────────────────────┐
│  ingestion-service           │  Accepts documents, enforces domain
│  FastAPI + PostgreSQL        │  rules, persists raw content, writes
│                              │  the event to an outbox table in the
│                              │  same transaction.
└──────────────┬───────────────┘
               │
        ┌──────▼──────┐
        │ outbox relay │  Separate process. Reads unpublished rows,
        └──────┬──────┘  publishes to the broker, marks as sent.
               │
      ┌────────▼─────────┐
      │  Redis Streams   │  Event schemas defined in rag-contracts.
      └────────┬─────────┘
               │
┌──────────────▼───────────────┐
│  retrieval-service           │  Consumes events, chunks, embeds,
│  FastAPI + Qdrant + LLM      │  indexes into Qdrant, serves queries.
└──────────────────────────────┘

rag-contracts — Pydantic event schemas. Installed into both services
as a pinned Git dependency. Single source of truth.
```

### Why two services and not one

They have opposing load profiles. Ingestion arrives in bursts, tolerates latency, and is write-heavy against a relational store. Retrieval must respond in low single-digit seconds, is read-heavy, and scales with query volume rather than corpus size. Independent deployment and scaling is the justification — not repository count.

### Why events and not a direct HTTP call

A synchronous call would couple availability: if the indexer is down, ingestion fails. With the outbox pattern, the document and its event are written in one database transaction, so no event is ever lost even if the broker or the consumer is unavailable. Delivery is **at-least-once**, which makes consumer idempotency mandatory.

### Why Redis Streams

Sufficient throughput for this workload, minimal local footprint, consumer groups built in. RabbitMQ would be the choice if complex routing or dead-letter topologies were required. This decision belongs in an ADR.

---

## 3. Stack

- **Language:** Python 3.14+, fully type-annotated (see ADR 0002)
- **Package manager:** `uv`
- **Web framework:** FastAPI (OpenAPI generated automatically)
- **Validation:** Pydantic v2
- **Lint / format:** `ruff`
- **Type checking:** `mypy` in strict mode
- **Testing:** `pytest`, `testcontainers` for integration
- **Relational store:** PostgreSQL (ingestion only)
- **Vector store:** Qdrant (retrieval only)
- **Broker:** Redis Streams
- **Containers:** Docker, multi-stage builds, `docker compose` for local
- **CI:** GitHub Actions
- **Hosting:** Render or Fly.io

---

## 4. Non-negotiable principles

1. **Hexagonal architecture in both services.** Domain → ports → use cases → adapters. The dependency arrow always points inward.
2. **The domain layer imports nothing external.** No FastAPI, no SQLAlchemy, no Qdrant client, no HTTP library. If an external type is needed, a port is missing.
3. **Ports are `typing.Protocol`.** Structural typing, no inheritance from abstract base classes.
4. **Use cases are testable with in-memory doubles.** If a use case cannot be exercised without a database, the design is wrong.
5. **Tests are written alongside the code, not retrofitted.** Domain and use-case tests are part of the definition of done for every unit.
6. **Event schemas live only in `rag-contracts`.** Copying a schema between services defeats the separation.
7. **The retrieval consumer is idempotent.** Reprocessing the same event must not duplicate chunks or corrupt the index.
8. **All commits, READMEs, ADRs, docstrings and identifiers in English.**
9. **Every non-obvious decision gets an ADR.** Service split, broker choice, outbox over direct call, vector store, chunking strategy, embedding model.
10. **No optimization before measurement.** Performance work only begins once evaluation metrics exist.

---

## 5. Build order

The order is not negotiable. Each phase leaves the repository in a working, committable state.

### Phase 0 — Environment (`ingestion-service`)
Project scaffold with `src/` layout, `uv`, `ruff`, strict `mypy`, `pytest`.
**Done when:** lint, type check and one trivial test all pass.
**Why first:** every later phase depends on this toolchain being enforced from commit one. Adding strict typing later means fixing hundreds of errors at once.

### Phase 1 — Ingestion domain
Entities `Document` and `Collection`. Value objects `DocumentId`, `ContentHash`, `Metadata`. Business rules: content-hash deduplication within a collection, document state machine (`pending → processing → indexed | failed`), size and count limits. Domain event `DocumentIngested`. Ports `DocumentRepository` and `EventPublisher`. Unit tests.
**Done when:** the domain package has zero external imports and its tests pass.
**Why here:** this is the cheapest, highest-leverage layer. Getting the invariants right now prevents rework in every layer above.

### Phase 2 — Ingestion use cases
`IngestDocument`, `CreateCollection`, `GetIngestionStatus`. Tested against in-memory fakes.
**Done when:** all three run end to end with no infrastructure present.
**Why before infrastructure:** proves the ports are the right shape before committing to any specific technology.

### Phase 3 — Contracts package (`rag-contracts`)
Pydantic schemas for the published events, semantic versioning, installable as a pinned Git dependency, documented backward-compatibility policy.
**Done when:** `ingestion-service` consumes it as an external dependency.
**Why here and not earlier:** the event shape is derived from the domain built in Phase 1. Designing it first would be guessing.

### Phase 4 — Ingestion infrastructure
PostgreSQL adapter, **outbox table with transactional write**, **relay process publishing to Redis Streams**, FastAPI HTTP layer, composition root wiring dependencies.
**Done when:** posting a document over HTTP produces a row in Postgres and a message in Redis, verifiable by hand.
**Why the outbox is the centerpiece:** it is the single most defensible piece of engineering in this service. Treat it as the deliverable, not as plumbing.

### Phase 5 — Ingestion containerization
Multi-stage `Dockerfile`, `docker compose` with app, Postgres and Redis.
**Done when:** `docker compose up` brings the service up from a clean machine.

### Phase 6 — Ingestion quality
Integration tests with real containers, coverage measurement, secret management via environment variables.
**Done when:** integration suite is green and coverage is reported in CI.

### Phase 7 — Ingestion deployment 🚩 **GATE**
GitHub Actions running lint, types and tests. Public deployment. English README explaining the architecture. ADRs committed.
**Done when:** a public URL accepts documents and the CI badge is green.

> **HARD GATE.** Do not create the `retrieval-service` repository until this phase is complete. Two half-finished repositories are worth less than one finished one. If progress stalls here, the correct response is to finish this service, not to start the next.

### Phase 8 — Retrieval domain and use cases
Entities `Chunk`, `IndexedDocument`, `Query`. Ports `Chunker`, `EmbeddingProvider`, `VectorStore`, `LLMClient`. Use cases `IndexDocument` and `AnswerQuery`. Tested with doubles.
**Done when:** `AnswerQuery` runs end to end against fakes with no real model or vector store.

### Phase 9 — Retrieval infrastructure
Redis Streams consumer with **idempotency guarantees**, chunking adapter, embedding adapter (hosted and local implementations behind one port), **Qdrant adapter** with index configuration, payload filtering and hybrid dense + sparse search, LLM client adapter, FastAPI query endpoint.
**Done when:** the deployed ingestion service emits an event that this service consumes and indexes, then answers a query about that document.
**Why Qdrant is the heavy piece:** index type selection, quantization and hybrid search are the substantive infrastructure work in this system. Budget accordingly.

### Phase 10 — Retrieval containerization and quality
`docker compose` with app and Qdrant. Integration tests. Sentry error tracking.

### Phase 11 — Evaluation
Fixed evaluation dataset of question–answer pairs. Ragas for retrieval and generation metrics. Tracing via LangSmith or Phoenix. Latency and cost-per-query instrumentation.
**Done when:** a reproducible evaluation report can be regenerated with one command.
**Why this phase matters most:** an unevaluated RAG is indistinguishable from a weekend tutorial. Quantitative retrieval metrics are the strongest single differentiator in the entire system.

### Phase 12 — Retrieval deployment 🚩 **GATE**
CI, public deployment, English README, ADRs.
**Done when:** both services run in production and the full path from upload to answer works against public URLs.

### Phase 13 — Security hardening
Rate limiting and input validation on both services. Prompt injection mitigation and context sanitization in retrieval. Secret management audit. Hardening decisions recorded as ADRs.

---

## 6. Repository layout (both services)

Each service is a single importable package under `src/` — `rag_ingestion` here,
`rag_retrieval` in the retrieval service. See ADR 0003 in this repository.

```
src/<package>/
  domain/          # entities, value objects, events, ports. Zero external imports.
  application/     # use cases. Depends only on domain.
  infrastructure/  # adapters. Depends on domain ports.
  api/             # FastAPI routers, request/response models.
  config.py        # settings via Pydantic Settings
  main.py          # composition root
tests/
  unit/            # domain + use cases, no I/O
  integration/     # real containers
docs/
  adr/             # numbered architecture decision records
```

---

## 7. Definition of done for any unit of work

- Code is fully type-annotated and `mypy --strict` passes
- `ruff` reports no violations
- New behaviour is covered by tests and the suite is green
- No domain file imports infrastructure
- Commit message is in English and describes the change, not the file
- If a non-obvious decision was made, an ADR exists
