# 27. The relay runs as a scheduled command, and its silence is measured by backlog age

- **Status:** Accepted
- **Last revised:** 2026-11-24

## Context

4.3, the relay, is the last unit of Phase 4. It was blocked on two questions, and
this record answers both because they are one problem seen from two sides.

**Where it runs.** ADR 0025 put the API on Render's free web service and the
database on Neon's free plan, under the developer's constraint of **no payment
barrier**. It recorded that "the relay will not fit": Render's free plan covers web
services only, and a free web service sleeps after 15 idle minutes. `CLAUDE.md`
also says the relay and the API do not share a lifecycle, so running the relay
inside the web service is not an option even if it stayed awake. The relay also
needs a broker to publish to, and ADR 0021 left Redis out of the compose stack
because nothing read from it.

**How its silence becomes legible.** ADR 0016 settled the logging mechanism and
split out the other half: a crashed relay and an idle relay both write nothing. It
proposed measuring the age of the oldest unpublished outbox row, through state the
API and the relay already share. That was "a proposal, not a decision"; this
record decides it. The principle that settles the design is that **what matters is
not whether the relay is alive but whether rows have been waiting too long.** A
dead relay with an empty outbox loses nothing.

**Where the facts came from.** Carlos approved both decisions in conversation on
2026-11-24, after a written proposal that named the alternatives. The provider
facts were gathered the same day by web search of vendor documentation and of
third-party comparisons, and some sources are vendor or competitor pages. They
were not exercised against an account, except where marked below. Free tiers
change every few months, so these are the reasons the choice was made, not a
guarantee. The sources:

- `https://render.com/docs/free`
- `https://upstash.com/pricing/redis`
- `https://upstash.com/docs/redis/commands/streams/overview.md`
- `https://redis.io/docs/latest/operate/rc/databases/create-database/create-free-database/`
- `https://docs.github.com/en/actions/reference/usage-limits-billing-and-administration`
- `https://flaviocopes.com/hosting-free-tiers/`
- `https://community.render.com/t/web-worker-not-part-of-the-free-plan/24555`

**Not verified, and this record's Redis choice depends on it.** Two things were
not confirmed: whether Upstash's free plan **persists** data (a competitor
comparison claims it does; Upstash's own page was not read for this), and whether
stream commands count against the 500K monthly commands the same as other
commands. Carlos is running a ten-minute test of `XADD`, `XGROUP CREATE`,
`XREADGROUP` and `XACK` on a free Upstash database **before the relay is
written**. If that test fails, the Redis choice below falls and the fallback
applies. Whether GitHub emails the owner when a workflow fails depends on Carlos's
notification settings, and that was not checked.

## Options considered

### Where the relay runs

- **A scheduled GitHub Actions workflow running the relay with `--once`, every 5
  minutes.** Chosen. In a public repository the minutes cost nothing, and it is
  still a separate process from the API, as `CLAUDE.md` requires.
- **A Render background worker.** Rejected, and only for one reason: it costs
  about 7 USD a month, and ADR 0025 records the no-payment constraint. It is the
  simplest and most reliable answer, and **if the constraint relaxes it is the
  clean way out.** Because the command has two modes (below), taking it is a
  change of host and not of code. The question will return anyway: the retrieval
  service will also need always-on processes.
- **Render's free Key Value as the broker.** Rejected. It is 25 MB, memory only,
  and may restart and lose data. Once the relay has marked an outbox row sent, a
  message lost from the broker is a lost event, so the broker has to be durable.
- **The relay inside the free web service.** Rejected. It sleeps after 15 idle
  minutes, so the relay would sleep with it, and it would share the API's
  lifecycle, which `CLAUDE.md` forbids.
- **An external cron that calls an API endpoint to trigger the relay.** Rejected.
  It would put the relay inside the API process, which is the same objection by a
  longer route.
- **Fly.io and Railway.** Not pursued. A 2026 comparison (`flaviocopes.com`, a
  third-party source) says neither has a permanent free always-on tier any more.
  ADR 0025 had already rejected Fly.io for new accounts.

### Where Redis lives

- **Upstash, free plan.** Chosen, **subject to the test above.** Its pricing page
  says 500K commands a month, 256 MB and one free database per account, and its
  command list includes `XADD`, `XREADGROUP`, `XACK` and `XGROUP`. A batch relay
  fits that budget. A relay polling every second would use about 2.6 million
  commands a month, five times the allowance, which is the reason the schedule is
  batch and not continuous.
- **Redis Cloud, free plan.** The fallback, not the choice. One 30 MB database,
  which Redis describes as for learning and prototypes.

### How the relay's silence is made legible

- **A heartbeat table the relay updates.** Rejected. It needs a migration, and it
  measures liveness, which is not the harm. A live relay that fails every publish
  would keep it fresh while the backlog grew.
- **Logs only.** Rejected as the whole answer. Nobody reads logs until something
  has already failed. Logs stay, as the second of the three parts below.
- **An external monitoring service such as Sentry or Datadog.** Rejected. It is an
  account and a dependency for something the shared state already provides.
- **The age of the oldest unpublished outbox row, reported three ways.** Chosen.

## Decision

### The relay is a command with two modes

`python -m rag_ingestion.relay`, with `--once` (drain the outbox, then exit) and
`--loop` (keep running). The same code serves both, so changing host rewrites
nothing.

- `--once` runs from a scheduled workflow every 5 minutes.
- `--loop` is for the local compose stack and for a future always-on host.
- Secrets for Neon and Upstash live in a GitHub Environment, as the `Migrate`
  workflow's do (ADR 0025).

### Redis is Upstash's free plan

Redis Cloud's free plan is the fallback if the test fails. Neither goes into
`render.yaml`, because the relay is not a Render service.

### The silence is measured in three parts

1. **A read-only endpoint, `GET /outbox/backlog`**, returning
   `{"unpublished": n, "oldest_unpublished_age_seconds": s}`, with a null age when
   nothing is waiting. It is the measure ADR 0016 proposed. It is an API change, so
   it gets its own pull request, and ADR 0015 and the README guard
   (`tests/unit/test_the_readme_describes_the_real_api.py`, ADR 0023) apply.
   **The endpoint's internal design, a port and a use case, is not decided here**
   and needs Carlos's separate approval.
2. **The relay writes one JSON log line per run** with the same two numbers (ADR
   0016's mechanism), so "nothing pending" is distinguishable from "did not run".
3. **`--once` exits non-zero if, after its run, the oldest unpublished row is older
   than a threshold**, so the failed workflow run is the alert. 30 minutes is
   suggested; the exact value is left to the relay's own proposal.

The health check Render uses stays `/openapi.json` and must not touch the
database, or it would keep Neon awake (ADR 0025). The new endpoint is separate
from it.

### What this does not decide

The relay's internals (`FOR UPDATE SKIP LOCKED`, publish-then-mark, batch size,
retries) get their own proposal as 4.3. The retrieval service's hosting is not
decided either.

## Consequences

**Positive.** The relay costs nothing and the API process is untouched by it. A
move to an always-on host is a change of where `--loop` runs. The measure is the
harm itself, an event waiting too long, and needs no new channel or table.

**Negative: latency is at least 5 minutes, and the schedule is not a promise.**
GitHub does not guarantee that a scheduled run starts when scheduled. Community
reports describe delays of hours and skipped runs. Retrieval will see a document
minutes to hours after it was accepted.

**Negative: GitHub disables scheduled workflows in a public repository after 60
days without repository activity** (GitHub's documentation). A finished project
would stop relaying without any change on our side.

**Negative, the residual hole: if GitHub stops running the workflow, nothing
fails, and the silence returns.** Whether disabled or skipped, no run fails and so
no alert fires. Only `GET /outbox/backlog` shows it, and someone has to look. A
free external monitor polling the endpoint would close the hole. **It was not
evaluated and is not part of this decision.**

**Negative: the alert is slow by design.** The 30-minute threshold has to sit well
above the 5-minute cadence plus GitHub's delays, or ordinary lateness would fail
runs. A real outage is therefore noticed at least half an hour late, and a delay
longer than the threshold is a false alarm.

**Negative: the broker rests on an unverified claim.** Persistence and the stream
command accounting on Upstash's free plan were not confirmed from Upstash's own
pages. The ten-minute test decides it, and a failed test reopens the choice and
sends it to the fallback, whose 30 MB is much smaller.

**Negative: a second place for secrets.** Neon and Upstash credentials now sit in
a GitHub Environment as well as in their providers' consoles and the developer's
gitignored `.env`. The guard `tests/unit/test_no_secret_is_committed.py` covers
the repository, and nothing covers the Environment.

**Negative: the paid answer was rejected, and it is the better one.** A background
worker is simpler and more reliable than a schedule. This record chooses against
it because of a constraint, and will be corrected in place if the constraint goes.

**Negative: whether a failed run reaches the owner is not known.** If GitHub's
notification settings do not email failed runs, the failed run is an alert nobody
receives.

**Other files.** This record corrects ADR 0016 and ADR 0025 in place. It changes
no code. The unit's outcome is for `docs/BUILD-PLAN.md` and `CLAUDE.md` to carry
once the pull request merges.
