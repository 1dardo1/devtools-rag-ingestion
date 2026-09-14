# 23. The README shows the API, and a guard holds it

- **Status:** Accepted
- **Last revised:** 2026-09-14

## Context

`ROADMAP.md` 7.3: "Write the explanation someone reads cold, having never seen the
repository, and comes away understanding what it does and why it is built this
way."

A README already existed and was not bad. The problem was that **reading it cold
did not tell you what the service accepts.** There was no example request. For a
service whose entire job is to accept documents, that is the first question a
reader has, and the document did not answer it.

Reading it also turned up three claims that had stopped being true, which matters
more than any of them individually:

- `infrastructure/` was described as holding an "outbox relay" and a "Redis
  publisher". **Neither is written.** 4.3 is blocked, so the README described a
  more finished service than exists.
- "These five commands are exactly what CI runs" — CI has three jobs now, two of
  which run no commands from that list.
- A `<!-- TODO: extend at Phase 5 -->` left from before the container and the
  compose stack existed.
- The link to ADR 0005 used `../../devtools-rag-contracts/…`, which resolves only
  in a checkout with both repositories side by side. From GitHub it was broken.

Documentation drifts because nothing executes it. Adding a worked example makes
the document more useful *and* gives it more to get wrong.

## Options considered

### How much of the API the README shows

- **A worked example — three real requests with real JSON — plus a guard.**
  Chosen.
- **The worked example with no guard.** Self-sufficient and zero machinery.
  Rejected: the four stale claims above are what that costs, and they accumulated
  in a document nobody was lying in deliberately.
- **Prose and a pointer to `/docs`.** Cannot drift, because it says nothing
  specific. Rejected because it fails the unit's own criterion: a reader browsing
  GitHub cannot run the service, so "see `/docs`" tells them nothing about what it
  accepts.

### What the guard checks, and what it deliberately does not

It does **not** extract the shell from the markdown and run it. That needs a bash
grammar and a live server, and the compose CI job already posts a document through
the real stack — so the shape is exercised; what is unguarded is whether the
*document* still describes it.

So it checks the two things that actually drift, in both directions:

1. Every route, field name and refusal `code` the README shows still exists — the
   routes and fields against the generated OpenAPI document, and the codes against
   the `_REFUSALS` table itself rather than a second hand-written list.
2. The README still mentions each of them. Without this half, deleting the whole
   "What it accepts" section would leave the first half passing, since it would
   then be asserting that the API matches a list in a test file — which is not what
   the guard is for.

It also asserts that the README still explains **`202`, never `201`**. That is not
trivia: ADR 0015 made the status a statement about what the service promises, and
a README that quietly said `201` would undo the decision in prose while the code
kept it.

## Decision

`README.md` rewritten around what a reader needs in the order they need it: why
the service exists, **what it accepts** with three working `curl` commands and the
full refusal table, how to run the whole stack in one command, how to work on it,
how it is built, and what is not done.

`tests/unit/test_the_readme_describes_the_real_api.py` holds the API section
against the service, as above.

The three commands were **run against a real server**, not composed from memory:
PostgreSQL migrated with `alembic upgrade head`, the service started with
`uvicorn`, and each command executed verbatim. They answered `201`, `202` and
`200` with the shapes the README prints. Three refusals from the table were
checked the same way — `duplicate_collection_name` (409),
`collection_not_found` (404) and `request_too_large` (413, refusing an 8 MB body).

That found one error in the example: `ingested_at` was written as
`2026-09-13T08:04:52+00:00`, and the service returns
`2026-09-13T08:17:34.105557Z` — `Z` rather than `+00:00`, with microseconds.
Corrected to what it actually returns. A guard on field *names* would never have
caught that, which is worth knowing about the guard's reach.

**A "What is not done" section, stated as fact rather than as a plan.** The relay
does not exist, so nothing drains the outbox; there is no public deployment; there
is no health endpoint, so the compose health check probes `/openapi.json`. A README
that lists only what works is a sales document, and this repository's value to a
reader is the opposite of that.

## Consequences

**The README now answers the first question a reader has**, and the answer is
executable.

**Its most specific claims cannot rot silently.** A renamed field, a moved route, a
changed success status, a new or deleted refusal code, or a deleted section all
fail the suite with a message naming what disagrees.

**Negative: the guard checks names, not behaviour.** It would not have caught the
`ingested_at` format error — that took running the thing. Anything in the README
that is *prose about* behaviour, or a value's format, is still held by nothing but
care. The honest summary is that the guard makes the structure trustworthy and
leaves the semantics to review.

**Negative: the lists in the test are a third place the API is written down**,
after the code and the README. That is the cost of the two-way check; the
alternative, generating the README section from the OpenAPI document, would
produce reference material rather than an explanation, and the explanation is what
7.3 asked for.

**Negative: a count was removed rather than guarded.** The README said "the 238
tests"; it is 245 now. Rather than add a guard for a number nobody reads twice, the
sentence no longer states one. Not every fact is worth a test, and saying which is
which is part of the decision.

**And the rule was applied to one count and not the other, in this same commit.**
The rewrite removed the test count and then wrote "**Twenty-two decisions are
recorded in `docs/adr/`**" — while adding this ADR, the twenty-third. It was false
the moment it was written, by the commit that wrote it. The sentence now names no
number.

That is worth more than the one-word fix. The reasoning above ("a count in prose
is a count that rots") was correct and was recorded, and the *same document* then
broke it a hundred lines further down, because the second count was in a section
nobody was thinking about while editing the first. A rule that has to be
remembered at every site is not yet a rule — it is an intention. The guard in this
ADR checks names and not numbers on purpose, so nothing caught it; it was found by
reading the repository against itself. **What the guard's reach does not cover is
covered by nothing.**

**`docs/` keeps its job.** The README links to `ARCHITECTURE.md`, `ROADMAP.md`,
`BUILD-PLAN.md` and the ADRs rather than absorbing them. The line drawn is: the
README says what the service is, what it accepts and how to run it; everything
about *why* stays in the ADRs, with the README pointing at the two worth reading
first.
