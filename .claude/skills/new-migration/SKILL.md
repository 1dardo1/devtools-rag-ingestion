---
name: new-migration
description: Write and prove a new Alembic migration for devtools-rag-ingestion. Use whenever the database schema has to change, once Carlos has approved the schema change. Migrations here are hand-written SQL with no declared models, so autogenerate cannot work, and every constraint is proved against a real PostgreSQL before the migration is proposed.
---

# Writing a migration

A schema change always needs Carlos's explicit approval first
(`docs/COLLABORATION.md` section 4), with a rejected alternative. If that
approval is not in the conversation, stop and propose instead.

## Why it is done this way

ADR 0010 chose psycopg 3 with hand-written SQL and Alembic running `op.execute`,
with **no declared models**. `alembic revision --autogenerate` diffs models
against the database, and there are no models, so it does not work here and
never will. ADR 0012 records what every constraint in the schema restates and
what the schema deliberately does not enforce. Read it before writing SQL.

## Steps

1. **Read** `docs/adr/0012-the-initial-database-schema.md` and the latest
   revision in `src/rag_ingestion/migrations/versions/`.
2. **Create the revision** with the next sequential id:
   `uv run alembic revision -m "<what it does>" --rev-id 000N`.
   Rename the file to the `v000N_<what_it_does>.py` pattern the existing
   revision uses.
3. **Write `upgrade()` and `downgrade()` by hand** as `op.execute("""...""")`.
   Name every constraint and index explicitly. A downgrade is required: it is
   how the migration is proved.
4. **Prove it with integration tests** in `tests/integration/`, following
   `tests/integration/test_initial_schema.py`. The test starts its own container
   through `testcontainers` and is marked `@pytest.mark.integration` (ADR 0011).
   Do not mock the driver. Cover:
   - upgrade creates what it should;
   - **for each new constraint, one row that violates it and is refused**, and
     one that is accepted;
   - downgrade removes it again, and upgrade after downgrade succeeds.
5. **Run** `uv run pytest -m integration tests/integration/<the new file>`. This
   needs a Docker daemon. If none is available, say so plainly. Do not report
   the migration as proved: CI is then the first place it runs.
6. **Hand the diff to the `transaction-reviewer` subagent** before proposing the
   pull request.
7. **Update ADR 0012 in place** (or delegate to `adr-writer`) if the schema
   record no longer matches. Records are corrected, not superseded.

## Never

- `--autogenerate`.
- A migration with no downgrade, or with a downgrade that has not been run.
- Running a migration at container start. ADR 0019 forbids it: replicas race,
  and a failed migration becomes a crashloop. Production migrations run through
  the `Migrate` workflow (`.github/workflows/migrate.yml`) and are started by
  hand.
