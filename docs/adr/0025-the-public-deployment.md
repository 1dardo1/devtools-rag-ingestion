# 25. The public deployment: Render for compute, Neon for PostgreSQL

- **Status:** Accepted
- **Last revised:** 2026-10-28

## Context

`ROADMAP.md` 7.2: "Public deployment — done when: a public URL accepts documents."
It is the half of the gate still open, and `CLAUDE.md` ranks the gate above
everything else.

The engineering was ready before the platform was. The image builds and starts in
CI (ADR 0020), configuration comes entirely from the environment (ADR 0017, ADR
0022), and migrations are deliberately a step of their own (ADR 0019). What was
missing was a place to run it, and that needed an account — so it waited on the
developer, who set one constraint: **no payment barrier**.

That constraint shapes everything below. A deployment of this service has two
halves, compute and a PostgreSQL database, and almost no provider is generous with
both. The realistic answer was two providers.

**Where the facts came from.** The providers' own pricing pages are blocked by the
network policy of the machine this was written on. The free-tier terms below were
gathered on 2026-10-28 from search results: Render's free-tier documentation and
Neon's free-tier FAQ are official sources, and most of the rest are third-party.
Free tiers change every few months, so these are the reasons the choice was made,
not a guarantee that they still hold.

## Options considered

### Compute

- **Render, free web service.** Chosen. It builds the existing `Dockerfile` from
  the repository and gives an HTTPS URL. The cost is that a free web service
  sleeps after 15 minutes without traffic and takes up to about a minute to wake.
- **Fly.io.** Rejected. It no longer has a free allowance for new accounts, only a
  short trial, and its managed PostgreSQL starts around $38 a month. It fits this
  architecture better: one image can run several process groups, and
  `release_command` runs a migration before each release. That will matter at 4.3,
  when the relay needs a process that is always on. It is not why 7.2 exists.
- **Cloudflare.** Rejected. Workers cannot run this service as written: it is
  synchronous Python on psycopg with a native libpq. Containers are driven by
  requests and sleep between them, which is the opposite of what the relay will
  need. And it offers no PostgreSQL. It remains useful for DNS in front of
  whichever platform runs the service.

### PostgreSQL

- **Neon, free plan.** Chosen. It is permanent rather than a trial: 0.5 GB per
  project, and compute that suspends after five minutes idle. No code changes;
  it is a `DATABASE_URL`.
- **Render's free PostgreSQL.** Rejected. It expires 30 days after creation and is
  then deleted. A portfolio URL that dies after a month is worse than none.

### How the platform is configured

- **A Blueprint, `render.yaml`, in the repository.** Chosen. The deployment is
  reviewed in a pull request and can be recreated from the file.
- **Clicking it together in Render's dashboard.** Rejected. It works the same, but
  it lives where git cannot see it, so nobody reviews it and nobody can reproduce it.

### Region

**Frankfurt for both: Render's `frankfurt` and Neon's AWS `eu-central-1`.** The
developer is in Spain and asked for something nearer, such as Madrid or Paris.
Neither provider has a region there. Render's only European region is Frankfurt,
and Neon's European regions are Frankfurt and London.

The distance that matters most is not the user's. `transaction_per_request` opens a
new connection for every request (ADR 0017), so each request pays the TLS
handshake and several round trips **between the API and the database**, while the
user pays one round trip to the API. Putting the two halves together is what
counts. The rejected alternative was each provider's default region, which could
have split them across the Atlantic.

### Neon's direct URL, not its pooled one

Neon offers two URLs. The pooled one goes through PgBouncer, which shares a few
server connections among many clients. Rejected: it protects against connection
exhaustion this service will not approach, and transaction pooling can surprise a
migration tool. The direct URL also keeps **one variable in one shape for both
readers**, the app and Alembic, which is ADR 0017's rule.

### The port

The image's `CMD` listens on 8000. Render routes to `PORT`, whose default is 10000.
**Chosen: declare `PORT=8000` in the Blueprint,** which is the pattern Render's
own Docker reference shows. Rejected: changing `CMD` to read `$PORT`. That changes
the image, which the `image` and `compose` CI jobs exercise, for no gain. It was
verified that `Settings` ignores `PORT`. With `extra="forbid"` this was worth
checking, but pydantic-settings only reads the environment variables a model
declares.

### When a commit is deployed

**`autoDeployTrigger: checksPass`.** A commit on `main` deploys only after its
GitHub checks pass. Rejected: `commit`, which would deploy a red build as readily
as a green one.

### Health check

**`/openapi.json`**, as in `compose.yaml` (ADR 0021). It needs no database, so a
Neon compute that is still waking cannot fail a deploy. Rejected for now: adding a
`/health` endpoint. That is an API change and gets its own pull request
(`OPEN-DECISIONS.md` 4.1).

### Migrations

ADR 0019 already ruled out migrating when the container starts. That left three
ways to run `alembic upgrade head` against Neon:

- **A GitHub Actions workflow started by hand (`workflow_dispatch`).** Chosen. It
  is proposed in **its own pull request**, the next one, because it touches CI. A
  human chooses the moment, so it cannot race Render's deploy. It always runs
  in the same environment, and it leaves a record of who ran it and when. The URL
  lives in a GitHub **Environment** secret, so only that workflow can read it.
- **From the developer's machine.** Rejected. It would work, but it depends on one
  laptop and leaves no record.
- **Automatically on merge, or through Render's `preDeployCommand`.** Rejected. A
  merge-triggered job and Render's deploy would start at the same time, with
  nothing to order them. `preDeployCommand` would order them, but it appears to be
  limited to paid instance types (not verified).

### The secret scanner, revisited as ADR 0022 required

ADR 0022 declined gitleaks with a trigger: "worth revisiting when there is a real
credential to protect, which is to say after 7.2". The trigger has now fired, and
**the decision is to defer again, for a reason that is new.** The one credential
this deployment creates is a PostgreSQL URL carrying a password. That is exactly
the first shape `test_no_secret_is_committed` searches for, and a Neon-shaped URL
was checked against that pattern and matched. The value itself lives in three
places outside the repository: Render's dashboard, a GitHub Environment secret, and
the developer's gitignored `.env`. The scanner's extra reach, high-entropy strings
and git history, protects shapes this repository still does not have. **The new
trigger is the first credential of a shape the guard does not know**, an LLM API
key in the retrieval service being the likeliest.

## Decision

- Render runs the existing image on its free plan, from `render.yaml`.
- Neon provides PostgreSQL on its free plan.
- Both are in Frankfurt, and the service uses Neon's direct URL.
- `DATABASE_URL` is entered once in Render's dashboard (`sync: false`) and never
  committed.
- Migrations run from a manually started workflow, added in the next pull request.

**This ADR does not make 7.2 done.** Done is "a public URL accepts documents", and
that is claimed only after the README's three requests have been run against the
deployed service. That is a later pull request, as the README's examples were
(ADR 0023).

## Consequences

**The gate depends on accounts, not code.** Once this and the migration workflow
merge, the remaining steps are the developer's: create the Neon project, create the
Blueprint, enter the URL, run the migration, and send the three requests.

**Negative: two cold starts in a row.** After 15 idle minutes Render sleeps the API,
and after 5 Neon suspends the database. The first request after a quiet spell can
take close to a minute. A keep-alive pinger was rejected: it would hide the
trade-off instead of stating it, and the README will state it.

**Negative: an unauthenticated public write endpoint until Phase 13.** Anyone can
post documents. The damage is bounded. 0.5 GB holds roughly a hundred documents
at the domain's 5 MiB limit, after which Neon refuses writes. Neither account is
meant to carry a card, so the worst case costs nothing. Phase 13 is rate limiting,
and it comes after the retrieval service, so this window is long. That is an
accepted risk, chosen over delaying the gate.

**Negative: the relay will not fit.** Render's free plan covers web services only;
background workers start on a paid instance. So 4.3 reopens the platform question,
and Fly.io may win it then.

**Negative: the health check proves the process, not the database.** A wrong
`DATABASE_URL` deploys green and fails on the first real request. That is the gap
a `/health` endpoint that touches the database would close.

**Negative: the Blueprint was not validated against Render's schema before
merging.** The network policy blocks `render.com`. Its field names were checked
against Render's published Blueprint reference, but the `free` plan slug and the
`frankfurt` region slug were taken from Render's documented usage rather than from
the schema. Render validates the file when the Blueprint is created, before
creating anything. If that fails, this ADR and the file are corrected in place.

**Every request opens a TLS connection to Neon.** That was always true of
`transaction_per_request`, but it is now a real network hop rather than localhost.
A connection pool remains deferred until there is a measurement
(`OPEN-DECISIONS.md` 5.3). This deployment is the first place such a measurement
can be taken.
