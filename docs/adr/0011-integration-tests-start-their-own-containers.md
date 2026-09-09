# 11. Let integration tests start their own containers

- **Status:** Accepted
- **Last revised:** 2026-09-09

## Context

`ROADMAP.md` 4.1 is done when the PostgreSQL adapter has an "integration test
against a real container", and `CLAUDE.md` states the rule directly:
"Integration tests use real containers. Do not mock the PostgreSQL driver." What
neither says is **how** the container gets there, and the answer shapes every
integration test in Phases 4 and 6.

One property is at stake that this repository has held since Phase 0. The README
says of its five commands: *"These five commands are exactly what CI runs."*
Today `uv run pytest` is the whole story — clone the repository and it works. If
the test database is started by something outside the test, that sentence stops
being true, and the suite stops being self-contained.

The decision covers more than PostgreSQL. Unit 4.3 needs Redis for the relay, so
whatever is chosen here is paid twice.

## Options considered

- **A service container in the CI workflow, plus a compose file for local
  work.** GitHub starts the database before the job begins, which is the fastest
  option inside CI, and nothing has to start anything from a test. Rejected
  because the database ends up defined in two places — the workflow and the
  compose file — that must agree and that nothing keeps in step; because
  `uv run pytest` alone would no longer work locally; and because the workflow,
  which today declares no infrastructure at all, would start declaring it.

- **One `compose.test.yaml` used by both**, with CI running `docker compose up
  -d` before pytest. Better than the previous option on the duplication count:
  one definition, two consumers. Rejected because the suite is still not
  self-contained, the workflow gains shell steps, and a throwaway test compose
  invites confusion with the production-shaped one that 5.2 will add — app,
  relay, Postgres and Redis together, serving an entirely different purpose.

- **`pytest-postgresql`.** Maintained and current (9.1.0, published five days
  before this record, declaring Python 3.14). Rejected on what it actually
  does: its dependencies are `mirakuru` and `port-for`, and it starts a **local
  PostgreSQL process**, not a container. That would require PostgreSQL installed
  on every machine that runs the suite and in CI, which is a heavier operational
  burden than Docker and does not match the rule `CLAUDE.md` already states. Its
  `noproc` fixture can attach to an existing server, but then its whole
  contribution — process management — goes unused.

- **`pytest-docker`.** Rejected on support: 3.2.5, published November 2025,
  declares Python 3.10 through 3.13 and not 3.14.

- **`testcontainers`.** Chosen.

## Decision

Integration tests start their own containers, through
`testcontainers[postgres]` in the `dev` dependency group. Each test receives a
container on a random port and tears it down afterwards.

Only the `postgres` extra is installed. The `redis` one belongs with 4.3, which
is blocked on Phase 3 in any case, and installing it now would be a dependency
nothing uses.

**Tests that start a container are marked `@pytest.mark.integration`**, so the
unit suite stays runnable where there is no Docker:

```toml
addopts = "--strict-markers"
markers = ["integration: starts a real container; needs a Docker daemon"]
```

`--strict-markers` is part of the decision rather than decoration. Without it a
mistyped `@pytest.mark.integrationn` is silently accepted and the test escapes
every filter; with it, collection fails. This was verified rather than assumed —
the typo aborts collection, and the correct marker deselects in both directions.

**The CI workflow needs no change.** GitHub's `ubuntu-latest` runners already
provide a Docker daemon, so the same `uv run pytest` continues to be the whole
of the test step.

## Consequences

**Positive.** `uv run pytest` remains the complete story, and the README's claim
that its commands are exactly what CI runs stays true. One mechanism covers
PostgreSQL now and Redis at 4.3. Random ports mean two suites can run at once
without colliding. The database a test uses is described in the test that uses
it, rather than in a file somewhere else that has to be kept in step.

**Negative.** Integration tests will not run on a machine without Docker; they
are marked so the other 179 still do, but the person who wants a full run needs
a daemon. Container startup is paid at test time rather than before the job, so
the integration suite will be slower in CI than a service container would have
been — a cost that grows with the number of containers, not with the number of
tests, provided fixtures are scoped to the session rather than to each test.

The dependency is not small: `testcontainers` pulls `docker`, `requests`,
`urllib3` and their transitive set into the dev group. That is contained — none
of it reaches the runtime dependencies, and nothing in `src/` imports any of it.

**The rule is now enforceable but not yet enforced.** Nothing stops an
integration test being written without the marker, in which case it fails
confusingly on a machine with no Docker instead of being skipped. The natural
place to close that is a fixture in 4.1 that both provides the container and
carries the marker, so forgetting it is not possible.
