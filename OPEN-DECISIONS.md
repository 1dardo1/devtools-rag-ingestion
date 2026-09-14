# Open decisions

**What this is.** A plain-language map of everything that is not finished in this
repository, written so it can be read cold and acted on later. Each item says what
the problem actually is, why it matters, what it costs to leave alone, and — the
part that matters most — **who can decide it**.

**Why it exists.** The ADRs in [`docs/adr/`](docs/adr/) record decisions that have
been *made*. `docs/ROADMAP.md` lists the work in order. Neither of them answers
"what is stopping me right now, and what do I have to choose?" That is this file's
only job.

**A word on honesty.** Several items below are uncomfortable — a component that
does not exist, a criterion not met, a guard with a known hole. They are listed
because a list of only the finished parts would be useless for deciding anything.

Last updated: 2026-09-14, at commit `eb0900c`.

---

## Quick orientation

If you read nothing else:

| | |
|---|---|
| **The one thing blocking the project** | There is no public URL. Until there is, the retrieval repository must not be started. |
| **Who can unblock it** | You. It needs an account somewhere, and I could not verify which free tiers are real from this machine. |
| **Blocked on somebody else** | The relay (4.3), which waits on the contracts repository. |
| **Safe to leave alone** | Everything in "Deferred on purpose" — each has a written trigger for when to revisit. |

---

## 1. The gate: there is no public deployment

**Status:** open. This is the single most important item.

### What it is

`CLAUDE.md` sets one rule above all the others: this service must be **deployed at
a public URL with green CI** before the retrieval repository is created. Green CI
has been true for a while. The public URL does not exist.

### Why it matters

The rule exists to stop a common failure: two half-finished services are worth less
than one finished one. A service that has never run anywhere but a laptop has not
been proved to run at all — everything about it is still a claim.

### What is actually ready

More than it might feel like. The hard parts are done and machine-verified:

- The container image **builds and starts**, checked by CI on every change.
- `docker compose up` brings the whole stack up on a clean machine, also checked by
  CI, which then posts a real document through it.
- Configuration comes entirely from the environment, and
  [`.env.example`](.env.example) lists every setting a deployment must supply.
- Migrations run as their own deliberate step, which is exactly what a platform
  needs.

So what is missing is not engineering. It is a place to put it.

### What has to be decided, and by you

**Where.** It needs an account, and possibly a card. I laid out Fly.io, Railway and
a small VPS earlier; you asked, reasonably, whether there are options with no
payment barrier at all.

**I could not answer that honestly.** The search results were low quality and
contradicted each other, and when I went to the providers' own pricing pages the
network policy of this machine blocked them. Reciting from memory which free tiers
exist today would be exactly the kind of unverified claim this project does not
accept — free tiers change every few months.

**What I can tell you is the shape of the problem, which is stable:**

- It splits in two — **compute** (run the image, get an HTTPS URL) and **a
  database**. Almost no provider is generous with both, so the realistic
  no-card answer is usually **two providers**, one for each half.
- Every free compute tier sleeps the service when idle. The cost is a slow first
  request for whoever opens your link — worth knowing for a portfolio.
- Historically card-free candidates worth checking *today*: Hugging Face Spaces
  (it can run a Dockerfile) or Koyeb for compute; Neon or Supabase for PostgreSQL.
  **Check them yourself — I am naming them as places to look, not as verified
  facts.**

### One thing I got wrong, corrected

When I first ranked the platforms I put Fly.io first because of its
`release_command`, which runs migrations once per deployment. **That criterion was
much weaker than I made it sound.** `alembic upgrade head` only needs to *reach the
database* — it can be run from your laptop, or from a CI job, pointed at the
deployed database. Migrations are rare. So no platform feature is required for it,
and the choice is really about cost, friction, and cold starts.

### What happens next

Name a platform and I write the configuration for that one, plus its ADR. Nothing
else about this is waiting on me.

---

## 2. The relay does not exist, so the outbox fills up and nothing empties it

**Status:** blocked, partly on another repository and partly on a decision you can
take today.

### What it is, in plain terms

The service stores a document and, **in the same database transaction**, writes a
row into a table called `outbox` saying "this document arrived". That pairing is
the most important property in the whole service: either both are saved or neither
is, so a document can never be stored without being announced.

The announcement is only written down, though. A separate process — the **relay** —
is supposed to read those rows and publish them to Redis so the retrieval service
can pick them up. **That process has not been written.**

### What that means in practice

If you deploy today, the service works: it accepts documents, stores them, and
records the announcements. But the `outbox` table grows and nothing ever drains it.
That is not a bug; it is a component that does not exist yet, and the README says
so out loud.

### Why it is blocked

Two separate reasons, and only one of them is about this repository:

1. **The event schemas live in `devtools-rag-contracts`, and its Phase 3 is not
   done.** The relay publishes events; the shape of those events is not this
   repository's to invent. This is genuinely external.
2. **A decision that was deliberately split out and is still open** — item 3 below.

### What you could do about it

Nothing here, until the contracts repository moves. That is not a failure of
sequencing; the build plan drew this dependency from the start.

---

## 3. A stopped relay and an idle relay look identical

**Status:** open, and **you can decide this today**. It is the only genuinely
technical decision left that nothing external blocks.

### The problem, plainly

The relay will run unattended. Suppose you check the logs and see nothing at all.
Two very different things produce that silence:

- the relay is running fine and there is simply nothing to publish, or
- the relay crashed an hour ago.

**Logging cannot tell these apart**, because in both cases nothing is written. ADR
0016 settled *how* the service logs (JSON, one object per line) and then noticed
that the mechanism does not solve the problem it was introduced for — so it split
the remaining half out as its own decision, due before the relay is built.

### The shape of an answer

Something has to speak when there is nothing to say. The proposal already recorded
in ADR 0016 is: **the API reports the age of the oldest unpublished row in the
outbox.** If that age keeps growing, the relay is not doing its job — and the
signal travels through the database both processes already share, rather than
needing a new channel between them.

That is a proposal, not a decision. When you want to take it, I will lay out the
alternatives properly, as with everything else.

### Why it matters now rather than later

Deciding it before the relay exists is much cheaper than retrofitting monitoring
onto a process already running in production. It also does not depend on the
contracts repository at all — so it can be done while that is blocked.

---

## 4. Decisions waiting on you, smallest first

These are all open questions from recent pull requests. **None of them blocks
anything**; each is a judgement call that is yours rather than mine.

### 4.1 A health endpoint

**The problem.** The compose stack checks whether the service is alive by asking
for `/openapi.json` — the route that serves the API documentation. It works, but it
is the wrong thing to depend on: documentation routes can be turned off for
unrelated reasons, and then the health check fails while the service is perfectly
fine.

**What it would take.** A few lines and a test. It is an addition to the public API,
which is why I have not done it without asking.

**My view.** Worth doing. It is the cheapest item here with a real effect, and a
deployment will want it anyway.

### 4.2 Should the two `413` refusals share a status code?

**The problem.** The service refuses over-sized input in two different places, for
two different reasons, and both answer HTTP `413`:

- `document_too_large` — the *document* breaks the domain's 5 MiB rule.
- `request_too_large` — the *request* was too big to even read, and was refused
  before being read at all.

They are told apart by a `code` field in the response body. My view is that this is
right, and it is exactly what that field was introduced for. But a client that
looks only at the status number cannot distinguish them, so it is worth your
confirmation rather than my assumption.

### 4.3 The strict reading of "no secrets in the repository"

**The problem.** [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md) asks that "no password,
key **or connection string**" be written down anywhere. A connection string *is* written down — in the compose
file and in the example environment file — naming a local database, with no
password in it.

I read the requirement as "no secret" and recorded that reading rather than
applying it quietly. **If you meant the stricter version**, the fix is to make the
value come from a file that is not committed — at the cost that
`docker compose up` stops working on a clean machine until someone creates that
file first.

**My view.** A connection string with no password is not a secret, and the one-step
start is worth more. But it is your requirement to interpret.

### 4.4 Make the two new CI jobs required

**The problem.** CI now has three jobs: the checks, the image build, and the compose
stack. Only the first can block a merge. The other two report their result and
nothing enforces it — so a broken image could, in principle, be merged.

**Only you can fix this**, because it is configured in GitHub's branch-protection
settings, not in any file in this repository. I would let them run green for a few
more changes first.

### 4.5 A duplicated fixture in two test files

**The problem.** A small piece of test setup — restoring the logging configuration
after a test changes it — now exists in two files, because anything that starts the
application touches it. The tidy fix is to move it to a shared file.

That means editing an existing test file, which the working agreement says I do not
do without asking. Genuinely minor.

---

## 5. Deferred on purpose, with the trigger written down

These are not oversights. Each was decided against *for now*, with a recorded
condition for revisiting.

### 5.1 A secret scanner

The repository has a guard that searches every file for credential-shaped text. It
is honest about its limit: **it only finds shapes it knows**. A high-entropy string
with no recognisable form would get through, and it does not read git history.

A proper scanner (gitleaks and similar) would do both. It was declined because it
means another third-party tool to pin and audit, for a repository that contains no
secrets at all. **The trigger to revisit is the deployment** — the moment there is a
real credential worth protecting.

### 5.2 Coverage measurement (roadmap 6.2)

Not done. Nothing measures how much of the code the tests actually exercise.

With 296 tests and mutation-testing done by hand on every guard, the marginal value
is lower here than in most projects — but it is genuinely missing, it touches CI,
and it is the last unfinished item in Phase 6.

### 5.3 A database connection pool

Every request opens a new database connection. That is slower than reusing them,
and it was deferred on the architecture's own principle: **no optimisation before
measurement**. There is still nothing to measure. The tool for it (`psycopg-pool`)
is well known and the change would be small.

### 5.4 A one-off CI failure that was analysed but not fixed

CI failed once because Docker Hub did not answer when the test suite tried to
download PostgreSQL. It has not happened since.

It was *not* written off as a fluke: there is a plausible cause in a change of mine
(a third CI job that also downloads from Docker Hub, so three now run at once), the
analysis is written in the comments of pull request #38, and the fix is known —
make the jobs run one after another instead of together, at the cost of slower CI
for every change. **The trigger is a second occurrence.** Paying that cost
permanently for a single ambiguous event would be the wrong trade.

---

## 6. Two things that belong to other repositories

Recorded here only so they are not lost:

- **The contracts repository needs its own toolchain scaffold** before its Phase 3
  can start — and its Phase 3 is what unblocks the relay here.
- **Somebody has to actually collect the corpus.** The roadmap decided *what* the
  documents are (documentation for FastAPI, Pydantic, Qdrant, `uv`, Redis Streams
  and pytest) but never scheduled *gathering* them. The retrieval repository's
  evaluation phase cannot happen without it.

---

## 7. A suggested order

Not a plan you have to follow — a reading of which moves buy the most.

1. **Decide where to deploy** (item 1). Everything else is polish beside it, and
   the project's own rule says so.
2. **Add a health endpoint** (4.1) — cheap, and a deployment wants it anyway.
3. **Decide the relay's silence** (item 3) while the contracts repository is
   blocked, so that work is ready when it unblocks.
4. Then the small confirmations: 4.2, 4.3, 4.4, 4.5, in any order.
5. **Coverage** (5.2) last, or never, depending on what you want the repository to
   demonstrate.

---

## A short glossary

Terms used above that are worth having straight:

- **The gate** — the project's own rule that this service must be publicly deployed
  with green CI before the next repository is started.
- **Outbox** — a table where an outgoing announcement is stored *in the same
  transaction* as the thing it announces, so the two can never disagree. The
  announcement is sent later by a separate process.
- **The relay** — that separate process. Not written yet.
- **Required check** — a CI job that GitHub will refuse to merge without. Configured
  in GitHub's settings, not in this repository.
- **Guard** — a test whose job is to hold a rule that would otherwise rely on
  somebody remembering it. This repository has six.
- **ADR** — Architecture Decision Record: one document per non-obvious decision,
  naming the alternatives that were rejected and what the choice costs. There are
  twenty-three in [`docs/adr/`](docs/adr/).
