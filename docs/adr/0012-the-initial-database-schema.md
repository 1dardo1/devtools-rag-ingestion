# 12. The initial database schema

- **Status:** Accepted
- **Last revised:** 2026-09-09

## Context

ADR 0010 chose psycopg 3 with hand-written SQL and Alembic with no declared
models. That choice has a consequence which arrives immediately: there is no
metadata to generate a schema from, so **every column, constraint and index is
something a person decided on purpose**, and the reasons need to live
somewhere. This is that somewhere.

The domain is already built and validates on construction. Value objects parse
rather than validate, `Document` refuses a negative size and a naive timestamp,
`Metadata` refuses a blank required field, and `DocumentStatus` and `DocType`
are closed sets. The schema's job is therefore not to invent rules. It is to
**restate the rules the domain already has, in the one place the domain cannot
reach** — the moment two processes race, or a row is written by something that
is not this application.

Four questions were open before a line of SQL could be written, and each was
settled first: whether a failed document counts as a duplicate of itself, where
the raw bytes live, what an outbox row looks like before Phase 3 fixes the
payload, and where the database URL comes from.

## Options considered

### Whether a failed document blocks resubmitting its content

`Document.mark_failed` says in its own docstring that a failed document is
recovered by submitting it again.

- **A total unique index on `(collection_id, content_hash)`.** The obvious
  shape, and wrong. It makes that promise unkeepable: the resubmission is
  refused as a duplicate of the very attempt that failed, and the only way out
  is deleting a row by hand.
- **A partial unique index restricted to `status <> 'failed'`.** Chosen. Two
  failed attempts at the same content may coexist; one live copy — `pending`,
  `processing` or `indexed` — excludes any other.

This is the schema half of a rule whose other half is
`DocumentRepository.exists_with_content_hash`, which points here. Both halves
exist because the query is what produces a *domain error a caller can read*,
and the index is what makes the answer *true under concurrency*.

### Where the raw content lives

- **A separate `document_contents` table**, keyed by `document_id`, so that
  queries about a document never touch its bytes. Rejected on two counts. The
  cost it avoids is not real: PostgreSQL's TOAST already moves a large value
  out of line, so a `SELECT` that does not name `content` does not read it, and
  hand-written SQL always names its columns. And it would put a second insert
  inside the transaction that already carries the document and its outbox row,
  for no gain.
- **Object storage, with a key in the row.** Rejected for now: it introduces a
  second system that the transaction cannot span, which is the exact failure
  the outbox exists to prevent. Worth revisiting only if documents stop being
  documentation pages — at 5 MiB a page, they are not close.
- **A `bytea` column on `documents`.** Chosen.

### What an outbox row looks like

Phase 3 fixes the published payload in `devtools-rag-contracts`. This schema
therefore commits to the **envelope** and leaves the payload opaque.

- **Deleting the row once published.** Rejected: it destroys the audit trail,
  and makes "was this ever published?" a question with no answer. A
  `published_at` that is `NULL` until it is not says the same thing and keeps
  the record.
- **A UUID primary key.** Rejected: a v4 UUID carries no order, and the relay
  needs to publish oldest-first. An identity `bigint` gives that ordering for
  free.
- **`json` or `text` for the payload.** Rejected in favour of `jsonb`, which
  guarantees the stored value is valid JSON where `text` guarantees nothing.
  The cost is that `jsonb` normalises: key order and whitespace are not
  preserved, so the bytes published are not byte-for-byte the bytes stored.
  That is invisible to any JSON consumer, and would matter only if a payload
  were ever signed — at which point the signature belongs in a column of its
  own rather than in the shape of this one.
- **A foreign key from `outbox` to `documents`.** Rejected. The outbox is
  deliberately event-type-agnostic, its payload opaque to the table holding it;
  a foreign key would tie a log of things that happened to the lifetime of the
  rows they happened to.

### How the status vocabulary is constrained

- **A PostgreSQL `ENUM` type.** Rejected: adding a member becomes `ALTER TYPE`,
  which is awkward to reverse in a downgrade, and buys nothing a `CHECK` does
  not already give.
- **Unconstrained `text`.** Rejected, and this is the interesting half. The
  partial unique index above is written `WHERE status <> 'failed'`, so **the
  correctness of deduplication depends on that word being spelled the same
  everywhere**. A misspelled status would not raise anything; it would quietly
  make a document undedupable.
- **`text` with a `CHECK` naming the four members.** Chosen.

**`doc_type` is deliberately not constrained the same way**, and the asymmetry
is the point. It has twenty-six members, every addition would be a migration,
and *nothing in this schema branches on its value* — so a check would buy
tidiness at the price of coupling the schema to a list that is expected to
grow. An unrecognised `doc_type` is caught instead when the row is read back
through `DocType`, per ADR 0010's rule that rows become entities through their
own constructors.

### Whether `size_in_bytes` is stored at all

- **Drop it and compute `octet_length(content)`.** One source of truth, and
  tempting. Rejected because `octet_length` on a TOASTed value has to fetch the
  whole value: a status lookup that wants only the size would read the
  megabytes the column layout was chosen to avoid reading.
- **Store it, unrelated to the content.** Rejected: the two can then disagree
  silently, and a wrong size is not recoverable from anything.
- **Store it, with `CHECK (size_in_bytes = octet_length(content))`.** Chosen.

**This is the one constraint in the schema that goes beyond what the domain
states**, and the cost should be named plainly: `Document` only refuses a
negative size, so `Document(size_in_bytes=5)` carrying three bytes of content
is a legal object that the database will refuse. The asymmetry surfaces as an
integrity error rather than a domain error. It is accepted because
`IngestDocument` computes the size from the very bytes it stores, so the two
can only diverge through a bug, and a loud bug beats a silent one.

### Whether `collections` records when it was created

- **A `created_at` column.** Rejected, twice over. `Collection` has no such
  field, so the column would either be one nothing ever reads, or a change to
  the domain made for the database's convenience. And filling it with `DEFAULT
  now()` is the database reading a clock behind the domain's back — the exact
  thing ADR 0009 put the `Clock` port there to prevent.

If an operator later needs to know when a collection was made, that is a
domain change first and a migration second, in that order.

### Where the migrations live

- **A top-level `migrations/` directory.** The conventional layout, and what
  `alembic init` produces. Rejected: `pyproject.toml` packages `src/rag_ingestion`
  and nothing else, so those files would not be in the wheel. The Phase 5 image
  would have to copy them in separately, and `script_location` would differ
  between a checkout and the image.
- **`src/rag_ingestion/migrations/`, with `script_location =
  rag_ingestion:migrations`.** Chosen. Alembic resolves a `package:path`
  location through the import system, so the same `alembic.ini` works from a
  checkout and from site-packages.

### Where the database URL comes from

- **`sqlalchemy.url` written into `alembic.ini`.** Rejected: it is a
  credential in version control the first time somebody adds a password.
- **Environment only.** Nearly right, but a test that has just started a
  database already knows its URL, and putting it in `os.environ` leaks it into
  every test that follows.
- **A configured URL if there is one, then `DATABASE_URL`, then a readable
  error.** Chosen, in `env.py`.

**This settles the migration runner's own need and nothing wider.** The
service's configuration story belongs to the 4.5 composition root; if that
names its variables differently, this is one line.

## Decision

Three tables, created by revision `0001`.

**`collections`** — `collection_id uuid` primary key, `name text` not null,
unique and non-blank. The unique constraint is **case-sensitive**, because
`Collection` is: it strips surrounding whitespace and does not fold case, and
an index that treated `Docs` and `docs` as one name would enforce a rule the
domain does not have.

**`documents`** — identity, a foreign key to `collections`, the content hash,
the content as `bytea`, the size, the status, `Metadata`'s four fields as four
columns, and `ingested_at` as `timestamptz`. Constraints restate the domain:
a 64-digit lowercase hex digest, a non-negative size that matches the content,
a status drawn from `DocumentStatus`, and non-blank text where `Metadata`
demands it — expressed so that `NULL` still means absent, since a `CHECK` does
not apply to one. Two indexes: the partial unique index above, and a plain
index on `collection_id`, which the partial one cannot serve because
`count_in_collection` counts failed documents too, and which PostgreSQL does
not create for a foreign key by itself.

The foreign key takes no `ON DELETE` clause, so a collection holding documents
cannot be deleted. Nothing in this service deletes collections; when something
does, that is a decision to take then rather than a default to inherit now.

**`outbox`** — `outbox_id bigint generated always as identity` primary key,
`event_type text`, `payload jsonb`, `occurred_at timestamptz`, and
`published_at timestamptz` left `NULL` until the relay has sent it. One partial
index on the unpublished rows, so the index holds the backlog rather than every
event ever published.

`timestamptz` throughout, never `timestamp`. The domain refuses a naive
datetime; a column that discards the zone would reintroduce exactly what it
refuses.

Migrations live in `src/rag_ingestion/migrations`, and integration tests pin
`postgres:16` rather than `postgres:latest` — a suite whose result depends on
when it was run is not a suite.

## Consequences

**Positive.** A row the domain would refuse to build cannot be stored, and that
is not a claim: `tests/integration/test_initial_schema.py` inserts each
violation and asserts the refusal. The deduplication rule now has both halves,
so it survives two requests arriving at once rather than only reading well.

**This schema was run before it was recorded.** Against PostgreSQL 16.13:
`upgrade head`, then every constraint probed with a violating insert, then
`downgrade base` leaving only `alembic_version`, then `upgrade head` again.
`alembic upgrade head --sql` generates the offline script. The wheel was built
and installed into a separate environment containing no `src/`, and migrated a
database from there, which is the claim `script_location = rag_ingestion:migrations`
makes and the one the Phase 5 image depends on.

**Negative: every constraint is a second statement of a rule that lives in
Python, and the two can drift.** ADR 0010 already named this as the price of
hand-written SQL. The mitigation is the integration suite and nothing else — if
a domain rule changes and the migration does not, only those tests will say so.

**Negative: the size check is stricter than the entity.** Named above, and
worth repeating here because it is the one place where a legal `Document` is
not a storable one.

**Negative: a typo'd `doc_type` is storable.** It fails later, when the row is
read back through `DocType`, which is a worse place to find out than the write.
Accepted deliberately, so that adding a documentation kind stays a domain change
rather than a domain change plus a migration.

**Negative: the outbox orders by assignment, not by commit.** Identity values
are handed out when a row is inserted, so under concurrency a row with a lower
`outbox_id` can commit after a higher one, and the relay can publish two events
slightly out of order. Nothing is lost — an unpublished row stays unpublished
until it is marked — but **strict global ordering is not a guarantee this schema
makes**, and 4.3 should not assume one.

**Negative: the payload column exists before its contents are agreed.** Phase 3
fixes the `DocumentIngested` schema in the contracts repository, and until it
does, `jsonb` is a shape with nothing to say about what goes in it. That is the
deliberate split — the envelope is this service's, the payload is the contract's
— but it does mean 4.2 writes a column whose validity nothing here can check.
