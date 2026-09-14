# devtools-rag-ingestion

[![CI](https://github.com/1dardo1/devtools-rag-ingestion/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/1dardo1/devtools-rag-ingestion/actions/workflows/ci.yml)

The write path of the Devtools RAG system: accepts technical documents, enforces
domain rules, stores them, and publishes an event when a document is ready to be
indexed.

## Why this exists

This service deliberately knows nothing about retrieval, embeddings or language
models. Its only job is to accept documents safely and tell the rest of the
system that they arrived.

Documents and their outgoing events are written in **a single database
transaction**, using the transactional outbox pattern, so no document is ever
stored without eventually being announced — even if the broker or the consumer is
unavailable at the time. That invariant is the reason this service exists as its
own process, and the test that holds it is
`TestTheDocumentAndItsOutboxRowAreAtomic`.

The corpus is developer documentation for the stack this system is built on —
FastAPI, Pydantic v2, Qdrant, `uv`, Redis Streams and pytest. That choice is
recorded as ADR 0005 in the [contracts
repository](https://github.com/1dardo1/devtools-rag-contracts); it constrains the
metadata carried with each document and nothing else here.

## What it accepts

Three endpoints. Content arrives **base64-encoded inside JSON**, because the
domain stores arbitrary bytes and a service that cannot take a file with a `\0` in
it is not storing bytes — [ADR
0015](docs/adr/0015-the-http-layer.md) records the alternatives that were
rejected.

Create a collection:

```bash
curl -X POST http://localhost:8000/collections \
  -H 'Content-Type: application/json' \
  -d '{"name": "fastapi-docs"}'
# 201 {"collection_id": "0b5f…"}
```

Submit a document into it:

```bash
curl -X POST http://localhost:8000/collections/$COLLECTION_ID/documents \
  -H 'Content-Type: application/json' \
  -d '{
        "content": "'"$(printf 'FastAPI runs a def endpoint in a threadpool.' | base64 -w0)"'",
        "metadata": {
          "source_library": "fastapi",
          "doc_type": "tutorial",
          "library_version": "0.141.1",
          "source_url": "https://fastapi.tiangolo.com/async/"
        }
      }'
# 202 {"document_id": "7c1a…"}
```

**`202`, never `201`.** The service has accepted responsibility for the document
and written down that it arrived; it has not finished with it. Indexing happens
elsewhere, later, and `201 Created` would claim otherwise.

Ask what happened to it:

```bash
curl http://localhost:8000/documents/$DOCUMENT_ID
# 200 {"document_id": "7c1a…", "collection_id": "0b5f…",
#      "status": "pending", "ingested_at": "2026-09-13T08:17:34.105557Z"}
```

`library_version` and `source_url` are optional; `source_library` and `doc_type`
are not. Every refusal answers with the same shape, `{"code", "detail"}`, because
several distinct refusals share a status — a duplicate name, a duplicate document
and a full collection are all `409`, and a client should not have to parse English
to tell them apart:

| status | `code` | meaning |
|---|---|---|
| `404` | `collection_not_found` | no collection with that id |
| `409` | `duplicate_collection_name` | that name is taken |
| `409` | `duplicate_document` | this exact content is already live in this collection |
| `409` | `collection_full` | the collection is at its document ceiling |
| `413` | `document_too_large` | the decoded content exceeds the domain's limit |
| `413` | `request_too_large` | the *request body* exceeded the transport cap, and was refused before being read |
| `422` | `missing_metadata_field`, `invalid_source_url`, `missing_collection_name` | malformed input |

The two `413`s are different rules measuring different things, which is exactly
what the `code` field is for: one is a document the domain refuses, the other is a
request too big to read. [ADR 0018](docs/adr/0018-the-body-size-cap.md).

The generated OpenAPI document is served at `/openapi.json`, and the interactive
version at `/docs`. The example above is held against it by
`tests/unit/test_the_readme_describes_the_real_api.py`, so a renamed field or a
moved route fails the suite rather than quietly making this section a lie.

## Running the whole thing

One command, on a machine with Docker and nothing else:

```bash
docker compose up --wait
```

That starts PostgreSQL, runs `alembic upgrade head` **once** in its own
throwaway container, and only then starts the service — so a clean machine really
does work in one step. Then:

```bash
curl -X POST http://localhost:8000/collections \
  -H 'Content-Type: application/json' -d '{"name": "fastapi-docs"}'
docker compose down --volumes
```

**Two things are deliberately absent.** There is no Redis and no relay, because
the relay is not written yet — and a Redis nothing reads from would pass its
health check while making the outbox look drained, which is worse than its
absence. **So a document posted to this stack lands in `documents` and in
`outbox`, and nothing takes it out of `outbox`.** That is the true state of the
system, not a bug in the compose file.
[ADR 0021](docs/adr/0021-the-compose-stack.md).

PostgreSQL runs with trust authentication and both ports are bound to
`127.0.0.1`. That is correct for a laptop and indefensible anywhere else; it
exists so that no password has to live in this repository. See
[`.env.example`](.env.example) for every setting a real deployment supplies, and
[ADR 0022](docs/adr/0022-secrets-live-in-the-environment.md) for the guard that
keeps credentials out of the history.

## Working on it

Requires [`uv`](https://docs.astral.sh/uv/), which installs Python 3.14 itself if
the machine does not have it.

```bash
uv sync --locked --all-groups  # install exactly what uv.lock names, dev tools too
uv run ruff check              # lint
uv run ruff format --check .   # formatting
uv run mypy                    # strict types, over src and tests
uv run pytest                  # tests
```

Those four checks are the `Lint, types, tests` job in CI, in that order. Two more
jobs run beside it: one builds the image and starts the container, and one brings
the compose stack up and posts a document through it. See
[`.github/workflows/ci.yml`](.github/workflows/ci.yml),
[ADR 0008](docs/adr/0008-continuous-integration.md) for why the checks are one job
and [ADR 0020](docs/adr/0020-the-image-is-built-and-started-in-ci.md) for why the
other two are not.

`uv run pytest` runs the integration tests too, and those start real PostgreSQL
containers through `testcontainers` — so they need a Docker daemon. Without one,
`uv run pytest -m "not integration"` runs every test that needs nothing — a
number deliberately not written here, because a count in prose is a count that
rots.
[ADR 0011](docs/adr/0011-integration-tests-start-their-own-containers.md).

`uv sync` is not optional before `uv run pytest`. Under the src layout the suite
imports the *installed* package rather than the source tree, so a bare checkout
fails with an import error instead of a test result. That is deliberate — it is
what makes a green suite evidence that the packaged artifact works.
[ADR 0003](docs/adr/0003-src-layout-and-import-root.md).

## How it is built

Hexagonal, with the dependency arrow pointing inward:

```
src/rag_ingestion/
  domain/          entities, value objects, events, ports — zero external imports
  application/     the three use cases — depends only on domain
  infrastructure/  adapters — PostgreSQL repositories, the outbox publisher, a clock
  api/             FastAPI routes, schemas, the refusal table, the body-size cap
  migrations/      Alembic revisions, hand-written SQL
  main.py          the composition root: the one place the real pieces are wired
  config.py        settings, read from the environment
  observability.py JSON logging, one object per line on stdout
```

`domain/` imports nothing external, and that is checked rather than trusted. Ports
are `typing.Protocol`; the adapters never commit, because the transaction belongs
to the caller ([ADR 0013](docs/adr/0013-repositories-take-a-connection-and-never-commit.md));
and ports, use cases and adapters are **synchronous** on purpose, which
[ADR 0007](docs/adr/0007-synchronous-ports.md) argues at length because FastAPI
makes `async def` the reflex.

The distribution is `devtools-rag-ingestion`; the import root is `rag_ingestion`.
[ADR 0003](docs/adr/0003-src-layout-and-import-root.md).

**Every non-obvious decision is recorded in [`docs/adr/`](docs/adr/)**, each with
the alternatives it rejected and what it costs. They are the most useful thing in this
repository. If you only read two, read
[ADR 0012](docs/adr/0012-the-initial-database-schema.md) — what the schema
deliberately does not enforce — and
[ADR 0010](docs/adr/0010-persistence-with-psycopg-and-alembic.md), which rejects
the SQLAlchemy ORM on evidence rather than taste.

[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) describes the three-repository
system and why it is split. [`docs/ROADMAP.md`](docs/ROADMAP.md) lists the phases;
[`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md) maps what blocks what, including the
work the roadmap did not name.

## What is not done

Honest about the shape of the thing rather than the plan for it:

- **The relay does not exist.** Nothing drains the outbox, so documents are
  recorded and announced-to-nobody. It is blocked on the event schemas in the
  contracts repository, and on one local decision: a relay that has stopped and a
  relay with nothing to do both write nothing, so its silence is not yet legible.
  [ADR 0016](docs/adr/0016-structured-logging-on-the-standard-library.md).
- **There is no public deployment yet**, which is the one thing this repository
  owes before the retrieval service is started.
- **There is no health endpoint.** The compose health check probes
  `/openapi.json`, which is the documentation route and the wrong thing to depend
  on.

## Related repositories

- [`devtools-rag-contracts`](https://github.com/1dardo1/devtools-rag-contracts) — shared event schemas
- [`devtools-rag-retrieval`](https://github.com/1dardo1/devtools-rag-retrieval) — indexing and query answering

## License

MIT
