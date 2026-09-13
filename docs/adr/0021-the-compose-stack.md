# 21. The compose stack

- **Status:** Accepted
- **Last revised:** 2026-09-13

## Context

`ROADMAP.md` 5.2 asks for "`docker compose`: app, relay, Postgres, Redis", done
when "`docker compose up` works from a clean machine".

Two things about that sentence had to be dealt with before a file could be
written.

**The relay does not exist.** 4.3 is blocked twice over — on Phase 3 in
`devtools-rag-contracts` and on the silence-legibility decision ADR 0016 split
out — so a quarter of the enumeration names a service nobody has written.

**And "works from a clean machine" requires a schema**, which ADR 0019
deliberately refused to create at container start. That ADR said the step would
find a home in 5.2 and 7.2; this is 5.2 paying that debt.

## Options considered

### Who applies the migrations

- **A one-shot `migrate` service** running `alembic upgrade head`, which `app`
  waits on with `condition: service_completed_successfully`. Chosen.

  **This does not contradict ADR 0019, and the distinction is the whole point.**
  That decision refused to migrate from the *image's* `CMD`, on two grounds: N
  replicas starting at once race to apply the same revision, and a migration that
  fails during startup becomes a crashloop instead of a visibly failed deployment.
  Neither reaches here. Compose starts **exactly one** migration container, waits
  for it to exit, and only then starts the app — one migrator cannot race itself,
  and if it fails the stack stops with that container's error rather than looping.
  The image's `CMD` is untouched.

- **The developer runs it by hand,** documented. Mirrors what production will do,
  and adds nothing to the file. Rejected because `docker compose up` alone then
  does *not* work from a clean machine, which is the criterion verbatim — and a
  three-command dance is the kind of thing that gets skipped, after which the
  first request fails for a reason that looks nothing like "you forgot a step".

- **PostgreSQL's init scripts** (`/docker-entrypoint-initdb.d`). No orchestration
  at all. Rejected decisively: it is a **second source of truth for the schema**
  beside Alembic, maintained by hand in parallel, which is precisely what ADR 0010
  and ADR 0012 exist to prevent.

### Which services

- **`app`, `postgres`, `migrate`.** Chosen. Everything in the file does something.
- **Those plus `redis`, with no relay.** It would leave the slot ready and give a
  developer a Redis to inspect. Rejected, and not on tidiness: **a Redis nothing
  reads from passes its health check while making the outbox look drained.** From
  outside, a stack with Postgres and Redis both up reads as a working pipeline;
  the rows would pile up in `outbox` with nothing consuming them, and the one
  piece of the system that would tell you so is the piece that is missing.
- **All four with the relay commented out.** Matches the roadmap's letter.
  Rejected: commented-out configuration is documentation pretending to be
  configuration, and it goes stale without anybody noticing, because nothing
  executes it.

**So 5.2 is split, the way the logging item was.** The Redis-and-relay half
travels with 4.3, in the change that can actually exercise it. `ROADMAP.md` and
`docs/BUILD-PLAN.md` say so rather than leaving the enumeration looking unmet.

### Database credentials

- **`POSTGRES_HOST_AUTH_METHOD=trust`, no password anywhere.** Chosen. There is no
  secret to leak because there is no secret, which is also what 6.3 will ask for:
  no credential in this repository. Local-only by construction — the published
  port is bound to `127.0.0.1`.
- **A development password written in the file.** Rejected: a secret-shaped string
  in version control is the thing 6.3 prohibits and `env.py` already warns about,
  and the next reader cannot tell a toy password from a real one without reading
  the comment beside it.
- **Requiring `POSTGRES_PASSWORD` from a `.env`, with a `.env.example`.** The
  safest pattern and what 6.3 will want for the *deployment*. Rejected here
  because `docker compose up` alone then fails until someone copies the example,
  which fails the criterion for the sake of protecting a secret that does not
  exist.

### Verifying the criterion

The same hole 5.1 had: this environment has a Docker client with no daemon, so
`docker compose up` cannot be run here. ADR 0020 already settled the shape of the
answer.

- **A third CI job, `compose`.** Chosen, on the rule ADR 0008 now carries: a job
  that would repeat the `uv` setup belongs in `checks`, and this repeats none of
  it.
- **Appending the steps to the `image` job.** Cheaper, since that job's layer
  cache is already warm. Rejected because that job's name is what appears as a
  status line and is what a required check is named after; "Image builds and
  starts" testing the compose stack as well makes the name lie.
- **Not verifying it.** Rejected: it would leave 5.2 in exactly the state 5.1 was
  just rescued from, and the genuinely new mechanism here — the wait on `migrate`
  — is the part nobody would have exercised.

## Decision

`compose.yaml` — the name the Compose specification prefers, rather than the v1
`docker-compose.yml` — with three services:

- `postgres: postgres:16`, pinned for ADR 0011's reason, with a `pg_isready`
  health check **naming the database** (`-d ingestion`, because the default
  database answers before `initdb` has created this one), a named volume, and the
  port bound to `127.0.0.1`.
- `migrate`, built from the same `Dockerfile` as the app so the migrations and the
  code that reads them are one commit, running `alembic upgrade head` once and
  exiting.
- `app`, waiting on `migrate` having completed *and* `postgres` being healthy.

`app` gets a health check too, and it is load-bearing rather than decorative:
**`docker compose up --wait` treats a service with no health check as ready the
moment its container is running**, which is before uvicorn has bound the port — so
a caller that waited would race the thing it waited for. It probes with `python3`
because the image is `python:3.14-slim` and has no `curl`.

The CI job runs `docker compose up --detach --wait`, then **creates a collection
and posts a document through the stack**, then prints the logs and tears the stack
down with `--volumes`. The post is deliberately more than a liveness probe: it is
the request that fails with a missing table if `migrate` did not actually run,
which is the one thing this file adds.

## Consequences

**`docker compose up` is now the whole of what a developer needs**, and CI asserts
it on a machine that has never seen this repository.

**The stack proves the migration ordering, not just that containers start.** A
`404` or `500` from the document post would mean the tables are missing — so the
`postgres healthy → migrate completed → app` chain is asserted by consequence
rather than by reading the file.

**Negative: `app` has no health endpoint, so the check probes `/openapi.json`.**
That is a gap rather than a preference: a liveness probe should not depend on the
documentation route, which could be disabled for unrelated reasons. Adding an
endpoint is a change to the API and therefore a decision of its own, not a detail
to slip into a compose file.

**Negative: the trust authentication is correct here and indefensible anywhere
else,** and a compose file is exactly the kind of thing that gets copied. The
mitigations are that it says so in the file, and that the port is bound to the
loopback address — which matters more than it sounds, because a bare `5432:5432`
binds every interface *and* does it by editing firewall rules directly, so a host
firewall would not save a laptop on a shared network.

**Negative: every `up` re-runs `alembic upgrade head`.** A no-op at `head`, but it
still starts a container and opens a connection. The alternative is remembering
when the schema changed, which is worse.

**Negative: this file is not the deployment, and nothing enforces that.** 7.2 puts
the service on the internet and will need its own answers for credentials,
migrations and TLS. The header says so; a reader in a hurry may not get that far.

**5.2 is half done by necessity, and the half that is missing is named.** Redis
and the relay arrive with 4.3. Recording that in `ROADMAP.md` rather than leaving
a four-service enumeration silently unmet is the same move ADR 0016 made when it
split the logging item.
