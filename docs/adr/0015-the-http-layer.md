# 15. The HTTP layer: FastAPI, base64 content, and per-request use cases

- **Status:** Accepted
- **Last revised:** 2026-09-12

## Context

`ROADMAP.md` 4.4 asks for a "FastAPI HTTP layer, OpenAPI generated", accepted
when "endpoints documented automatically". The framework was therefore chosen
before this ADR; what was not chosen is everything about how the layer is
shaped.

`docs/BUILD-PLAN.md` constrains it from the other side: "the web layer talks
only to the use cases; the storage chain only to the database. They meet for the
first time at 4.5." So 4.4 has to produce endpoints that work, are documented,
and are wired to nothing.

## Options considered

### The dependencies

FastAPI is mandated. Two things around it were not, and one of them produced a
surprise.

- **Pydantic: declared explicitly, or left transitive?** `fastapi` pulls it in
  either way. Declared explicitly, because `api/schemas.py` imports it directly —
  and that is the exact distinction ADR 0010 drew when it left SQLAlchemy
  transitive: SQLAlchemy is transitive *because nothing here imports it*. Declare
  what you import.

- **`httpx` or `httpx2` for the test client?** `httpx` is what every FastAPI
  tutorial installs. **Installing it and importing `TestClient` on Python 3.14
  emits:**

  ```
  StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is
  deprecated; install `httpx2` instead.
  ```

  Starlette 1.6 has moved on. `httpx`'s own PyPI classifiers also stop at 3.12,
  which is what prompted the check. Swapping to `httpx2` 2.12.0 — which declares
  3.14 and 3.15 — removes the warning. **Chosen on that evidence rather than on
  convention**; the rejected alternative is the popular one, and it would have
  adopted a deprecated path on day one and scheduled a migration for later.

- **`uvicorn` is deliberately not added.** 4.4 is routers and a test client;
  serving is 5.1's problem, and a dependency nothing uses is a dependency to
  explain.

### How the document's content arrives

The domain takes `bytes`, and `size_in_bytes` is computed from them.

- **A plain UTF-8 string in JSON.** The most readable option, `curl`-able by
  hand, and the corpus is text. Rejected because it narrows what the service
  accepts: the domain deliberately stores bytes, and a service that cannot take
  a document it has no opinion about has acquired an opinion. `CLAUDE.md` is
  emphatic that nothing outside the metadata fields should become
  corpus-specific.

- **`multipart/form-data`.** The textbook answer for uploading a file, and it
  carries arbitrary bytes. Rejected on the metadata rather than the content:
  form fields are flat, so the nested `metadata` object would have to be
  flattened or smuggled through as a JSON string inside a field, and the
  generated OpenAPI is markedly worse to read.

- **Base64 inside the JSON body.** Chosen. Arbitrary bytes, one content type,
  nested metadata intact, and `content: string (format: base64)` in the schema
  is self-explanatory. Pydantic's `Base64Bytes` decodes and rejects malformed
  input; it is lenient about over-padding (`"YWJj===="` decodes to `b"abc"`),
  which was checked and is tolerance rather than corruption.

### How an endpoint gets its use case

- **A router factory: `create_router(ingest: IngestDocument)`.** More explicit,
  no framework dependency-injection, and the pattern the rest of this codebase
  uses — the use cases and adapters are all plain dataclasses taking
  collaborators. **Rejected on one decisive point: it holds one use case for the
  lifetime of the process**, and therefore one connection and one transaction for
  the lifetime of the process. ADR 0013 put the transaction boundary in the
  caller's hands precisely so that it could be per request; a router built once
  at startup throws that away.

- **A module-level global that the composition root assigns.** Rejected without
  much thought: import-order-dependent, untestable in parallel, and invisible.

- **FastAPI's `Depends`, on provider functions that raise.** Chosen. The provider
  is called per request, which is where a per-request connection has to come
  from, and `app.dependency_overrides` is how both the composition root and a
  test supply the real thing.

### How a domain refusal becomes a status code

- **`try`/`except` in each endpoint.** Rejected: the same refusal reaches more
  than one route, and a mapping repeated per route is a mapping that drifts.

- **One table, registered as an exception handler on `DomainError`.** Chosen.
  A domain error this table has never heard of becomes a `500`, which is the
  honest answer — an unmapped error is a gap here, not a request the caller got
  wrong, and defaulting to `400` would blame the caller for our omission.

- **RFC 9457 `application/problem+json`** for the body. The correct answer in the
  abstract, and rejected for a concrete reason: FastAPI's own validation failures
  return `{"detail": ...}`, and adopting problem+json for our refusals would give
  the API **two** error shapes. One slightly non-standard shape beats two
  standards-compliant ones. The chosen body is `{"code", "detail"}` — `detail`
  matching FastAPI's key, plus a stable `code`, because three distinct refusals
  share `409` and a client should not have to parse English to tell a duplicate
  name from a duplicate document from a full collection.

### Two smaller ones

**`202`, not `201`, for an accepted document.** The document is recorded and its
status is `pending`; whether it is ever indexed is the retrieval service's
business. `201 Created` would claim a finished resource and a client would be
right to read it as "ready". The outbox exists precisely because this service
promises only to have written the document down and told somebody.

**`create_app()`, not a module-level `app`.** A module-level instance is built on
import, so importing the module becomes a side effect and two tests wanting
differently wired applications fight over one object. `uvicorn` accepts a
factory.

## Decision

`api/` holds five modules: `schemas.py` (Pydantic request and response models),
`dependencies.py` (providers that raise), `error_handling.py` (the refusal
table), `routes.py` (three endpoints) and `app.py` (`create_app`).

Three endpoints: `POST /collections` → `201`, `POST
/collections/{collection_id}/documents` → `202`, `GET /documents/{document_id}`
→ `200` or `404`.

Path identifiers are typed `UUID`, so FastAPI refuses a malformed one with `422`
before any domain code runs. `doc_type` is typed as the domain's `DocType`, so
Pydantic rejects an unknown kind with a `422` listing the allowed values —
accepting a plain string and calling `DocType(...)` would raise `ValueError`,
which is not a `DomainError` and would surface as a `500`.

**Every handler is `def`.** ADR 0007 decided it; this is where the temptation
lives, because FastAPI is async-native. FastAPI runs a `def` endpoint in a
threadpool, which is the correct way to call blocking code from an async server.

## Consequences

**Positive.** The whole layer is tested without a container — 20 unit tests,
because the web layer talks only to use cases, and if it had needed a container
the layering would already have been wrong. Four mutations confirm the tests
bite: declaring one endpoint `async def` fails the synchronicity test; removing
`DocumentTooLargeError` from the refusal table fails the size test; changing
`202` to `201` fails the acceptance test; and replacing `Base64Bytes` with
`bytes` fails two tests, because the content then silently arrives as the bytes
of the base64 *string*.

**Two rules now have guards rather than only reviewers.**
`test_every_endpoint_is_synchronous` holds ADR 0007 against a future `async def`,
and `test_the_application_ships_unwired` holds the 4.4/4.5 split by asserting
that an un-overridden provider refuses.

**Negative: a forgotten override in 4.5 is a runtime `500`, not a type error.**
That is the price of `Depends`. The providers raise `NotImplementedError` with a
message naming the composition root, which makes the failure legible but does not
make it early. Nothing in the type system can tell that an override is missing.

**Negative: base64 costs a third of the payload.** A document at the 5 MiB limit
is about 6.7 MiB of JSON on the wire. Acceptable for documentation pages
submitted by a pipeline; it would not be for a service taking large binaries.

**Negative, and this one is a real gap rather than a trade-off: the size limit is
enforced after the body has been read.** `DocumentTooLargeError` is raised by the
domain, which means the bytes are already in memory; a caller sending 500 MB gets
a `413` *after* the service has read 500 MB. A status code is not a defence. A
body-size cap belongs at the server or proxy, and Phase 13 is where security
hardening lives — but it is worth saying plainly that nothing here protects
against that today, and that 5.1 deploying this behind something is not optional.

**Negative: three refusals share `409`.** Deliberate, and the `code` field is the
mitigation, but a client that ignores the body cannot distinguish them.

**A third-party deprecation warning remains.** `starlette/testclient.py` triggers
`anyio.abc.BlockingPortal is deprecated` on import. It is inside Starlette, not
this codebase, and there is nothing here to change; it will go when Starlette
updates. Noted so the next person does not go looking for it in our code.
