# 10. Reach PostgreSQL with psycopg 3 and hand-written SQL, migrate with Alembic

- **Status:** Accepted
- **Last revised:** 2026-09-08

## Context

Phase 4.1 builds a PostgreSQL adapter and nothing decides what it is built with.
`ARCHITECTURE.md` and `CLAUDE.md` forbid the **domain** from importing
SQLAlchemy, three times over, but that is a rule about a layer rather than a
technology choice for the adapters. The README's stack line names neither an ORM
nor a driver, and `pyproject.toml` still reads `dependencies = []`. The only
concrete mention anywhere is `psycopg-binary` in ADR 0002's compatibility table,
cited there as evidence that the ecosystem had Python 3.14 wheels — not as a
choice to use it.

Three things about this service narrow the field before any preference does.

**The domain is already built, and it validates on construction.** Value objects
parse rather than validate, entities refuse invalid states in `__post_init__`,
and `Document` carries no setters beyond three named transitions. There is
nothing an object-relational mapper would be saving us from writing.

**The outbox is the deliverable.** `ROADMAP.md` calls it "the single most
defensible piece of engineering in this service" and instructs that it be
treated as the deliverable rather than as plumbing. Whatever writes the document
row and the outbox row must make their shared transaction obvious to a reader,
because that is the thing the service exists to demonstrate.

**The query surface is tiny.** One ingestion is four statements — does this hash
exist in this collection, how many documents does it hold, insert the document,
insert the outbox row. The relay adds a select, an update, and a delete. There
is no reporting, no dynamic filtering, no joins across a wide schema.

## Options considered

- **SQLAlchemy ORM**, with the entities mapped imperatively. The most
  recognisable choice in the Python ecosystem, the least persistence boilerplate,
  and where Alembic's `autogenerate` is at its most useful. **Rejected on
  evidence rather than taste: it does not work with these entities as they
  stand.** `Document` is declared `@dataclass(eq=False, slots=True)`, and
  mapping it *declares* without complaint but fails on first use:

  ```
  TypeError: cannot create weak reference to 'Document' object
  ```

  The identity map holds weak references to mapped instances, and `slots=True`
  without `__weakref__` forbids one. Every way out — adding `__weakref__` to the
  slots, dropping slots, or duplicating the entities as persistence models —
  either changes the domain to suit the database or maintains two shapes of the
  same thing. Passing a static declaration and failing at runtime is the exact
  failure mode ADR 0006 refused once already, when it disqualified renaming a
  parameter to silence `ARG002`.

  Its unit of work is a second objection. A session that decides when writes
  happen is a transaction abstraction competing with the one invariant this
  service is built to make obvious.

- **SQLAlchemy Core, without the ORM.** `Table` metadata and explicit
  `insert()`/`select()` statements over psycopg 3. No session, no identity map,
  so the weak-reference problem never arises. It buys a typed query builder,
  parameterisation by construction, and `alembic autogenerate` — which writes
  migrations from a diff instead of by hand. **This was the close call.**
  Rejected because a large dependency and a table-definition layer earn their
  keep on a wide schema with dynamic queries, and this service has four
  statements per ingestion against three tables; and because the outbox reads
  less directly through a builder than as two `INSERT`s in one transaction
  block.

- **psycopg 3 with hand-written SQL.** Chosen.

Then, for applying schema changes:

- **`dbmate` and `sqitch`.** Both do exactly this job well. Rejected on
  operations rather than merit: they are a Go binary and a Perl program, so
  adopting either puts a foreign executable in the Phase 5 `Dockerfile` and in
  CI, where today `uv sync` resolves the entire toolchain.

- **`yoyo-migrations`.** The cleanest conceptual fit — plain `.sql` files, no
  SQLAlchemy, up and down and a version table already solved. Rejected on
  maintenance: 9.0.0 was published in August 2024, and it declares no supported
  Python versions in its metadata, so 3.14 would have to be established by hand.
  A tool that touches the production schema going unmaintained mid-Phase-4 would
  mean migrating the migration tool with a live schema.

- **A hand-rolled runner**, forty lines over numbered `.sql` files. Zero
  dependencies and auditable at a glance. Rejected: it is infrastructure code to
  own and test, with no downgrade, no branching and no checksum verification
  unless written, and this repository has consistently declined to rebuild what
  a maintained tool already does.

- **Alembic running hand-written SQL.** Chosen.

## Decision

The Phase 4 adapter uses **psycopg 3** and SQL written by hand. Rows are turned
back into entities through their own constructors, so the invariants the domain
enforces are enforced again on the way out of the database.

Schema changes are applied by **Alembic**, with migrations containing
`op.execute("CREATE TABLE …")` and no declared models.

**That combination was run before it was recorded**, because the received wisdom
is that Alembic implies SQLAlchemy models. It does not: `alembic init`, a
revision whose `upgrade` is a single `op.execute`, then `alembic upgrade head`,
with no `MetaData` or `Table` anywhere, created the version table and applied
the change. An earlier draft of `BUILD-PLAN.md` claimed Alembic was "the wrong
answer without SQLAlchemy". That claim was written from memory, is false, and
has been corrected.

Versions were checked rather than assumed: `psycopg-binary` 3.3.5 ships cp314
wheels, and Alembic 1.19.2 declares support for 3.14 and 3.15.

## Consequences

**Positive.** The transaction that carries the document and its outbox row is
two `INSERT`s inside one block, which is as legible as that invariant can be
made. The domain needs no change and gains no mapping layer. The adapter's only
runtime dependency is a driver. Alembic supplies versioning, ordering and a
record of what has been applied without a line of it being written here.

**Negative, and the first one is an oddity worth stating plainly.** Alembic
depends on SQLAlchemy, so a project that deliberately declined to use SQLAlchemy
will nevertheless install it. It is a transitive dependency used only as
Alembic's engine layer, never imported by this codebase — but anyone reading
`uv.lock` will find it there and deserves this paragraph as the answer.

**`autogenerate` is unavailable.** It is the feature that makes Alembic feel
effortless, and it needs declared metadata to diff. Every migration is therefore
written by hand, which means the schema and the code that queries it can drift
apart with nothing to notice. Only the Phase 6.1 integration tests, against a
real container, will catch a column the SQL expects and the schema lacks.

**Nothing checks the SQL until it runs.** A misspelled column is a runtime error,
not a type error; `mypy --strict` has no opinion about the inside of a string.
This is the cost that SQLAlchemy Core would have removed, and it is the reason
that option was a close call rather than an easy rejection.

**Parameterisation is a discipline rather than a guarantee.** psycopg binds
parameters safely when values are passed as parameters; it cannot stop a
developer formatting a string. ADR 0006 enabled `ruff`'s `S` family, whose
`S608` flags likely SQL injection, so the linter carries part of this — but only
part, and Phase 13 should verify the rest rather than assume it.
