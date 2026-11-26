# Proposal: what happens to published outbox rows

- **Status:** Proposed. Nothing is decided and nothing is approved. This is not an
  ADR yet.
- **Scope:** the one problem ADR 0028 and ADR 0029 name as not covered: **nothing
  ever deletes a published outbox row**, so the `outbox` table grows with every
  event, on a database whose free plan holds 0.5 GB (ADR 0025). ADR 0029 bounds the
  Redis stream and says plainly that it does not bound the table.
- **Nothing here is code.** No migration, no command, no workflow. Each decision
  marked *needs approval* is one `docs/COLLABORATION.md` section 4 lists: a new
  command, a new port and, in two of the rejected options, a schema change.
- **Format:** follows `docs/proposals/relay-internals.md`.

## What is being decided

Whether published rows are kept, deleted, moved or partitioned, and if deleted,
after how long and by what. It does not decide anything about the relay, the stream
or the documents table.

## The tension this has to face first

ADR 0012 rejected "deleting the row once published": *it destroys the audit trail,
and makes "was this ever published?" a question with no answer.* That reason is
still true, and this proposal does not argue against it. It narrows it.

- **What ADR 0012 protects:** the ability to answer "was this ever published, and
  when?" from the table itself.
- **What deleting after N days gives up:** that answer, for events older than N days.
  Within the window nothing changes.
- **What survives anyway.** The invariant of ADR 0013 is that a document and its
  outbox row are written in one transaction, and the retention below never deletes an
  unpublished row. So a document older than N days that has no outbox row **must**
  have been published. The yes/no answer survives. The *when* does not.
  (This is an inference from two invariants, not a stored fact. It stops being true
  if either invariant is ever broken, for example by a manual delete.)
- **Whether the audit trail is worth its space** is Carlos's decision, and the
  reason option 1 below is a recommendation and not a conclusion.

If a retention option is approved, ADR 0012's rejected-alternative paragraph is
**corrected in place** (`COLLABORATION.md` section 8) to say what is deleted and when.
ADR 0028 and ADR 0029 each state, in their consequences, that the outbox is not
bounded, and are corrected in the same pull request.

## How big is the problem (estimates, not measurements of production)

**What a row weighs.** A real payload was built with the installed
`rag_contracts.events.DocumentIngested` (v0.3.0), using plausible values: a
`fastapi` tutorial page. It serialises to about **410 bytes** of JSON; PostgreSQL
`jsonb` stores it in about **456 bytes**. Nothing in it grows with the document:
the content is not carried (contracts CLAUDE.md), and the one free-text field is the
`source_url`.

**What a row costs on disk.** A throwaway PostgreSQL 16 was created in this
container, with the exact `outbox` table and partial index of migration `0001`, and
loaded with 100000 such rows. Measured with `pg_total_relation_size`:

| Situation | Bytes per row, table plus indexes |
|---|---|
| Inserted, not yet marked | about 590 |
| Inserted and already marked published, then `VACUUM` | about 570 |
| Inserted, then marked by a later `UPDATE`, then `VACUUM`, in bulk | about 1160 |
| The same, with a second 100000 rows reusing freed space | about 890 |
| Payload replaced by `'{}'`, then `VACUUM FULL` | about 100 |

Why the third row is double: `UPDATE` writes a new copy of the row, and the old copy
is dead space until `VACUUM` lets later inserts reuse it. The relay marks rows
minutes after they are inserted, so in steady state a table sits between the second
and the fourth row. **Use 1 KB per event as the working estimate.** It matches the
1 KB ADR 0029 already guessed for the stream, and now has a measurement behind it.
Measured locally only. Neon's own storage accounting (what it counts, whether it
includes write-ahead log or history) was not checked and may differ.

**What that means for 0.5 GB.** Steady state with retention is
`events per day x N days x 1 KB`. The event rate is unknown, so three guesses:

| Events per day | Kept 30 days | Kept for ever, one year |
|---|---|---|
| 100 | about 3 MB | about 36 MB |
| 1000 | about 30 MB | about 360 MB |
| 10000 | about 300 MB | about 3.6 GB |

The honest reading: the outbox is not what fills the database first. ADR 0025
works from the domain's 5 MiB limit per document, which gives about a hundred
documents in 0.5 GB. At an assumed 50 KB per page (a guess), the same space holds
about ten thousand, and each costs its content (50 KB) plus 1 KB of outbox, **an
outbox share of about 2 percent**. The outbox only becomes the problem if documents
are small, or are deleted while their rows stay. The pressure is real but slow, and
the rate is the number nobody has.

## Decisions

### 1. Delete published rows older than N days (needs approval; a recommendation)

A command removes rows where `published_at IS NOT NULL AND published_at < cutoff`.
Unpublished rows are never selected, whatever their age. The cutoff is `now - N days`
from the `Clock` port (ADR 0009), passed in, not read from the database's clock.

**Consequence:** the table's size settles at rate times N times about 1 KB, and stops
growing. The audit answer is kept for N days and reduced to a yes/no inference after.
No migration. A new command, a new port and a new use case.

**Rejected: keep everything for ever, with a size alarm (option 0 below).** It keeps the
audit trail and costs no code in the data path. It is rejected as the recommendation
because the alarm only says the problem has arrived: a database at its limit refuses
`INSERT`, which refuses documents, which is a production outage on the write path. The
alarm itself also needs code: a size endpoint or a workflow, both needing approval. It
remains the right answer if the audit trail matters more than the space, and it is
cheap to start with and move from. See the questions.

**Rejected: move old rows to an archive table.** It needs a migration. Worse, a table
in the same database frees **nothing** against a 0.5 GB limit: the bytes move from one
table to another. It only helps if the archive leaves the database, to a file or to
object storage, and that is a second system the transaction cannot span, the argument
ADR 0012 used against object storage for content. It would be the right answer with a
paid database or a free bucket and a reason to read old events.

**Rejected: partition the table by time.** Dropping a partition is instant and
reclaims space without `VACUUM`, which is its real advantage, and it is the right tool
at a volume this service does not have. It needs a migration that recreates the table
(PostgreSQL requires a unique constraint to contain the partition key, so the primary
key `outbox_id` has to change shape), something to create partitions ahead of time, and
a rewrite of the partial index per partition. Whether Neon's free plan offers the
extension that automates this was not checked. It costs more machinery than the problem
at 1000 events a day.

**Rejected: keep the row and empty its payload.** Measured: 570 bytes becomes about 100.
It needs no migration, because `payload` is `NOT NULL` and `'{}'` is a valid value, and
it keeps `outbox_id`, `event_type`, `occurred_at` and `published_at`. But it does not
fully answer the audit objection, since the `document_id` lived in the payload, so
afterwards the row says *an event was published at this time* and not *for which
document*. It also leaves 10 MB per 100000 events for ever. Reasonable as a second stage
after deletion, if Carlos wants a thinner trail than none.

### 2. N is 30 days (needs approval)

A guess. Reasons for the number: it is well beyond the 30-minute alarm of ADR 0027 and
the GitHub schedule's worst delays, so no row is deleted before anyone could still
act on it; it is long enough to investigate a report made a few weeks later; at the
rates above it costs at most about 30 MB at 1000 events a day.

**Rejected: 7 days.** It saves little (about 7 MB at 1000 a day) and shortens the
window an operator has to notice a problem found over a long weekend plus a holiday.

**Rejected: 90 days or more.** At 1000 events a day that is 90 MB, and the benefit is
the audit trail option 0 already provides at full length. If the window is going to be
this long, it should be for ever.

N is a command-line argument, not an environment variable, so it adds no
configuration to the service (section 4 lists configuration separately).

### 3. A separate command, not a step of the relay (needs approval)

`python -m rag_ingestion.outbox_retention --older-than-days 30`, with `--dry-run`
printing what would be removed. It is its own process, like the relay and the API.

**Rejected: run it at the end of every relay `--once`.** It would couple two jobs
with different failure meanings. The relay's non-zero exit is the alarm of ADR 0027,
and a retention failure would raise it for a reason that has nothing to do with a
waiting event, teaching everyone to ignore it.

**Rejected: an API endpoint that triggers it.** The API is public and unauthenticated
until Phase 13. A delete endpoint there is the wrong place to begin.

**Rejected: a SQL statement in a runbook, run by hand.** Zero code, and it works for
the first months. It is rejected as the destination because a step done by hand is a
step forgotten, and the first time it is forgotten is the day the database is full.
It is a reasonable first stage while the rate is learned, which is a way to phase the
work, not a different design.

How it is run (a manual workflow dispatch like `Migrate`, or on the relay's schedule)
touches CI and deployment, and is a separate pull request.

### 4. Delete in small batches, only published rows (needs approval)

```sql
DELETE FROM outbox
WHERE outbox_id IN (
    SELECT outbox_id FROM outbox
    WHERE published_at IS NOT NULL AND published_at < %s
    ORDER BY outbox_id
    LIMIT 1000
);
```

Repeated until a batch removes nothing. The predicate `published_at IS NOT NULL` is
the safety property of the whole proposal, so a test must hold it: with unpublished
rows older than the cutoff, none is deleted.

The cutoff uses `published_at`, not `occurred_at`. A row that waited three weeks and was
published yesterday is yesterday's event for retention, and keeps its window.

**Rejected: one `DELETE` of everything older than the cutoff.** The first run on a
large table holds one long transaction, and lock waits against the relay's
`FOR UPDATE SKIP LOCKED` batches become possible if a row is still being finished.
1000 matches the shape of the relay's batch (100) at ten times the size, since a delete
is cheaper than a publish. The number is a guess.

**Rejected: `TRUNCATE`.** It removes the unpublished rows too.

### 5. A port and a use case (needs approval)

A `Protocol`, `OutboxRetention`, with one method that deletes published rows before a
cutoff, up to a limit, and returns how many. A use case, `PruneOutbox`, takes the
cutoff from the `Clock` and loops. A Postgres adapter takes a connection and never
commits (ADR 0013); the command commits after each batch, as the relay does.

**Rejected: SQL straight in the command.** It works, but then the rule that
protects unpublished rows has no test that does not need a container. A port with an
in-memory fake lets the unit suite hold it.

### 6. One log line per run

One JSON line with `deleted`, `batches` and the cutoff, through ADR 0016's mechanism.
No new endpoint. `GET /outbox/backlog` stays exactly as it is.

## Effects on what already exists

**The partial index `outbox_unpublished`.** It holds only rows where `published_at IS
NULL` (ADR 0012), so it never contained the rows being deleted and deleting them does not
touch it. What it does show is what the relay's `UPDATE` already does: after 100000 rows
were marked published and vacuumed, the index kept about 2.2 MB of empty pages. Small, and
a plain `VACUUM` reuses them. The primary-key index is the one that grows with every row
(about 23 bytes per row) and is what a delete shrinks, after a vacuum.

**Space and `VACUUM`.** `DELETE` and a plain `VACUUM` make space *reusable*, not smaller:
a measured table at 169 MB stayed 169 MB after half its rows were deleted and vacuumed,
and fell to 54 MB only after `VACUUM FULL`. So retention **stops the table growing**; it
does not give megabytes back. That is the right property for a steady state, and the wrong
one for a table already past its limit. `VACUUM FULL` takes an exclusive lock and needs
room for a second copy, so it is not part of this proposal. Whether Neon vacuums on its own
schedule was not checked.

**`GET /outbox/backlog` (ADR 0027).** Unaffected, provided decision 4's predicate holds.
It counts and ages only `published_at IS NULL` rows. The danger is the one the predicate
removes: deleting unpublished rows would lose events and make the endpoint report zero.

**Idempotent consumers and replays.** The relay never rereads a published row, so
deleting one cannot cause a duplicate or a gap. Consumers deduplicate on `document_id`
(contracts `CLAUDE.md`), so a republished event is harmless. What retention removes is
a recovery tool, not a mechanism: setting `published_at` back to `NULL` makes the relay
send a row again, and that works only for rows still present. After N days, re-sending an
old event would need the event rebuilt from the `documents` row, which holds the same
fields, but no code does that. The stream, trimmed at about 100000 messages (ADR 0029),
is the replay source in practice, and it forgets sooner than N days at any rate above
about 3300 events a day. `outbox_id` is an identity, so a deleted id is never reused.

**The Neon limit.** See the tables above: with retention at N = 30 the outbox is a
constant of tens of megabytes at plausible rates and the limit is reached by documents
first. Without it, it is a ratchet.

## What this does NOT include

- A migration. Decision 1 needs none. The rejected options 2 and 3 each need one.
- Any code, command or workflow, and **where or when the command runs**. That is CI and
  deployment (section 4) and its own pull request.
- Any change to the relay, the stream, `GET /outbox/backlog`, the `documents` table or
  the contracts package.
- Deleting or compacting the `documents` table. Its content dominates the 0.5 GB and
  would be a decision of its own.
- A size alarm. It is option 0 and is not recommended as the only measure.
- Measuring the real ingestion rate, which every figure here depends on.

## Test plan, once approved

- **Unit tests** against an in-memory fake `OutboxRetention`: unpublished rows are never
  deleted, the cutoff is taken from the `Clock`, the loop stops when a batch is empty.
- **Integration tests** with real PostgreSQL (ADR 0011): the same three properties
  against the real table, and that a row locked by the relay's `FOR UPDATE SKIP LOCKED`
  does not block or lose to the delete.
- **Not tested here:** Neon's storage accounting and autovacuum, which only the deployed
  database can show.

## Why this way (teaching notes)

- **The trade-off.** Space against history. The outbox is a work queue that also happens
  to remember, and a queue that remembers for ever turns into a log nobody asked for.
  Retention says how long the memory is worth its price. The pattern is a **TTL, or
  retention policy**, applied to an **outbox table**. Look up "outbox cleanup" and
  "retention window".
- **C# and Java.** It is the scheduled cleanup job that every Hangfire, Quartz.NET or
  Spring `@Scheduled` application grows for its job tables. NServiceBus's outbox has a
  setting for how long it keeps its deduplication data, which is the same dial (name
  from memory, check before quoting it). The command being separate from the relay is
  the separation you would give a `BackgroundService` for cleanup versus one for
  dispatch.
- **Soft versus hard delete.** `published_at` is already a soft marker. Retention is the
  hard delete that eventually follows, and ADR 0012's objection was to doing the second
  without keeping the first for a while.
- **Archive and partitioning** are the two answers a larger system gives. An archive table
  is a temporal or history table in SQL Server terms. A partitioned table is how you make
  "delete a month" a metadata operation. Both are reasoned away here only by scale and by
  a 0.5 GB limit that an archive in the same database does not move.
- **What it makes easy, what it makes hard.** Easy: a size you can reason about. Hard:
  answering "when was this published" for an old document, and replaying from the table.

## Questions for the reviewer

1. **Is the audit trail worth its space?** If yes, the recommendation is option 0, keep
   everything and alarm on size, and decision 1 falls. If no, or only for a while, decision
   1 stands. This is the question ADR 0012 asked, and only Carlos can answer it.
2. Is 30 days the right N, or should it wait until the real event rate is known? Without a
   rate every figure here is a guess.
3. Is the "document with no outbox row was published" inference an acceptable replacement
   for the stored answer, given it rests on two invariants holding?
4. Should the first stage be a hand-run SQL statement in a runbook, with the command built
   later, or the command straight away?
5. Should the empty-payload variant (the fourth rejected option) be a second stage, or is
   deleting outright simpler to explain?
