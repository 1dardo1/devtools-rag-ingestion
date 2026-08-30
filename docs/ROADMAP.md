# Roadmap — devtools-rag-ingestion

Phases run in order. Each leaves the repository in a working, committable state.

## Phase 0 — Environment

| # | Unit | Done when |
|---|------|-----------|
| 0.1 | Scaffold: `src/` layout, `uv`, `ruff`, strict `mypy`, `pytest` | Lint, type check and one trivial test pass |

**Why first:** strict typing enforced from commit one. Adding it later means
fixing hundreds of errors at once.

## Phase 1 — Domain

| # | Unit | Done when |
|---|------|-----------|
| 1.1 | Value objects `DocumentId`, `ContentHash`, `Metadata` | Invalid values cannot be constructed |
| 1.1b | `Metadata` fields: `source_library`, `library_version`, `doc_type`, `source_url` | Required fields enforced at construction |
| 1.2 | Entities `Document`, `Collection` | Tests pass |
| 1.3 | Rules: content-hash deduplication, state machine, size and count limits | Each rule has a test |
| 1.4 | Domain event `DocumentIngested` | Shape agreed before Phase 3 |
| 1.5 | Ports `DocumentRepository`, `EventPublisher` | Defined as `Protocol` |

**Phase complete when:** the `domain/` package has zero external imports.

**Why this order:** a `Document` holds a `DocumentId` and a `ContentHash`, so the
value objects come before the entities that contain them.

**Why here:** cheapest layer to change and the one every other layer depends on.

## Phase 2 — Use cases

| # | Unit | Done when |
|---|------|-----------|
| 2.1 | `IngestDocument` | Runs against in-memory fakes |
| 2.2 | `CreateCollection` | Runs against in-memory fakes |
| 2.3 | `GetIngestionStatus` | Runs against in-memory fakes |

**Phase complete when:** all three run end to end with no infrastructure present.

**Why before infrastructure:** proves the ports are the right shape before
committing to any specific technology.

> **Phase 3 happens in `devtools-rag-contracts`.** Return here afterwards.

## Phase 4 — Infrastructure

| # | Unit | Done when |
|---|------|-----------|
| 4.1 | PostgreSQL adapter | Integration test against a real container |
| 4.2 | **Outbox table with transactional write** | Document and event committed atomically |
| 4.3 | **Relay process: outbox to Redis Streams** | Unpublished rows are published and marked sent |
| 4.4 | FastAPI HTTP layer, OpenAPI generated | Endpoints documented automatically |
| 4.5 | Composition root | Dependencies wired in one place |

**Phase complete when:** posting a document over HTTP produces a row in Postgres
and a message in Redis, verifiable by hand.

**The outbox is the deliverable, not the plumbing.** It is the most defensible
piece of engineering in this service.

## Phase 5 — Containerization

| # | Unit | Done when |
|---|------|-----------|
| 5.1 | Multi-stage `Dockerfile` | Image builds |
| 5.2 | `docker compose`: app, relay, Postgres, Redis | `docker compose up` works from a clean machine |

## Phase 6 — Quality

| # | Unit | Done when |
|---|------|-----------|
| 6.1 | Integration tests with real containers | Suite green |
| 6.2 | Coverage measurement | Reported in CI |
| 6.3 | Secret management via environment | No secret in the repository, `.env.example` present |

## Phase 7 — Deployment 🚩

| # | Unit | Done when |
|---|------|-----------|
| 7.1 | GitHub Actions: lint, types, tests | Badge green on `main` |
| 7.2 | Public deployment | A public URL accepts documents |
| 7.3 | English README with architecture rationale | Readable by someone who has never seen the repo |
| 7.4 | ADRs committed | Every non-obvious decision recorded |

> **HARD GATE.** The retrieval repository is not created until this phase is
> complete.

## Later

Phase 13 — security hardening: rate limiting, input validation, secret audit.
