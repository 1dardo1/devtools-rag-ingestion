# 28. The relay publishes then marks each batch inside one locked transaction

- **Status:** Accepted
- **Last revised:** 2026-11-26

## Context

4.3, the relay, reads the outbox that ADR 0014 and ADR 0026 write and publishes
each row to a Redis stream. ADR 0003 accepts at-least-once delivery through a
transactional outbox. ADR 0012 says the outbox orders rows by assignment, not by
commit, so the relay cannot promise order across batches.

ADR 0027 decided where the relay runs and how its silence is read: a command,
`python -m rag_ingestion.relay`, with `--once` run from a scheduled workflow every
5 minutes, and a silence measured by the age of the oldest unpublished row. This
record decides something else, which is how one run moves rows across: what a
batch is, what is locked, in what order a row is sent and marked, and what happens
when a send fails.

**Where the facts came from.** The approved proposal
`docs/proposals/relay-internals.md`, merged to `main` as 99eeecd and approved by
Carlos on 2026-11-26, decisions 1 to 4. The unsendable-row policy was decided by
Carlos on the same day. The batch size of 100 is a guess about the rate of
ingestion. It is not measured anywhere, and the proposal's "well under a second"
is an estimate as well.

**Depends on the Upstash test in ADR 0027.** This record assumes the stream
accepts `XADD` on the broker it is written against. ADR 0027's ten-minute test of
`XADD`, `XGROUP CREATE`, `XREADGROUP` and `XACK` on a free Upstash database has not
been run. The locking and marking below do not depend on the broker. Only the
publish target does, so a failed test changes where the messages go and leaves the
shape of the transaction as it is.

## Options considered

### The order of publishing and marking

- **Publish, then mark, in one transaction.** Chosen. A row is marked only after
  it has been sent, and the mark is undone if the batch fails.
- **Mark, then publish.** Rejected. A crash after the mark and before the send
  loses the event silently. That is at-most-once delivery, which the architecture
  forbids.
- **One transaction spanning PostgreSQL and Redis.** Rejected. Redis cannot join a
  PostgreSQL transaction, so the guarantee does not exist to be had.

### How concurrent runs are kept apart

- **`FOR UPDATE SKIP LOCKED` on each batch.** Chosen. A run that overlaps another
  skips the rows the other holds, so neither waits nor publishes them twice.
- **An advisory lock, or a lock row, held for the whole run.** Rejected. It works,
  but it is a second locking mechanism when the table already provides row locks,
  and a run that dies holds it until its session ends.
- **No locking.** Rejected. Two overlapping runs publish the same rows, and the
  consumers absorb the duplicates at a cost that grows with the schedule.

### The batch size

- **100 rows per batch.** Chosen, as a guess about the rate. It is a configuration
  value (`RELAY_BATCH_SIZE`), so it can change without code.
- **1 row per batch.** Rejected. Each event is one `XADD` either way, so the
  smaller batch makes each run longer without reducing the number of Redis
  commands.
- **An unbounded batch.** Rejected. A large backlog would hold row locks for
  minutes, and could exceed the time budget of a free runner.

### What happens when a send fails

- **Retry a failed `XADD` three times, after 1, 2 and 4 seconds; if it still fails,
  roll the batch back, log the failure and exit non-zero.** Chosen. Nothing is lost,
  because rows stay unpublished until marked, and the failed workflow run is the
  alert that ADR 0027 relies on.
- **Retry inside the process until the send succeeds.** Rejected. It holds a runner
  for as long as Redis is down, and spends free minutes waiting.
- **A dead-letter table for rows that keep failing.** Rejected for now. It needs a
  migration, and no failure mode yet needs one. It is to be revisited when a row
  fails repeatedly for a reason that is not transient.

### A row whose payload cannot be sent at all

- **Fail the run, log its `outbox_id`, and leave the batch blocked until a person
  fixes the row.** Chosen, by Carlos on 2026-11-26. The backlog alarm fires, so the
  row cannot be forgotten.
- **Skip the row and mark it.** Rejected. The event is lost.
- **Skip the row without marking it.** Rejected. The row stays unpublished, so the
  backlog alarm would stay on forever, and it would be indistinguishable from a
  real outage.

## Decision

Each batch is one database transaction. The relay's use case owns the unit of
work, because it claims, sends and marks in one call. The caller owns the
transaction: it commits when the call returns and rolls back when it raises.
Neither the use case nor the adapters commit (ADR 0013).

1. Select up to `RELAY_BATCH_SIZE` unpublished rows, in `outbox_id` order, with
   `FOR UPDATE SKIP LOCKED`. Rows another run has locked are skipped.
2. Send each row to the stream with `XADD`.
3. If a send fails, retry it after 1, 2 and 4 seconds. If it still fails, the use
   case raises an error carrying the `outbox_id`, the caller rolls the
   transaction back, the run logs the failure, and the run exits non-zero.
4. Set `published_at` on the rows of the batch, with the instant read once from
   the `Clock` port after the last send, and return. The caller commits.

A row whose payload cannot be sent at all takes the same path as step 3, and the
batch stays blocked until the row is fixed by hand.

## Consequences

**Positive.** No row is marked unless it was sent. A batch is marked whole or not
at all, and overlapping runs publish each row once in the common case.

**Negative: a crash republishes. Delivery is at-least-once.** A crash between the
`XADD` calls and the `COMMIT` publishes those rows again on the next run. The same
happens after an ordinary failure, because the rollback also unmarks the rows that
were sent before the failing one. A batch that fails on its sixtieth row republishes
the first fifty-nine on the next run. The consumer must be idempotent (principle 7
of `docs/ARCHITECTURE.md`, and ADR 0003). The contracts repository's event inventory
keys the consumer's idempotency on `document_id`, and not on `content_hash`.

**Negative: one unsendable row blocks everything behind it.** Batches are taken in
`outbox_id` order, so a row that cannot be sent holds back every later row until a
person fixes it, and the rows already sent in that batch are republished on each
run until then. This was chosen over losing an event, and the backlog alarm of
ADR 0027 is what makes it visible. It does not make the wait any shorter.

**Negative: locks are held across Redis round trips and retry waits.** The retry
sleeps happen inside the transaction. A single send that fails every retry holds
its batch's locks for at least 7 seconds of waiting, plus the time of the sends. The
proposal's "well under a second" holds only when Redis answers at the first try.

**Negative: the batch size is unmeasured.** 100 is a guess about the rate, and so is
the duration it implies. The value is configurable, so being wrong costs run time
and not the shape of the design.

**Negative: no order across batches.** Two overlapping runs can publish a later row
before an earlier one. This is ADR 0012's ordering limit, and this record does not
change it.

**Decided: `published_at` comes from the `Clock` port, not from the database's
`now()`.** The proposal's statement used `now()`. ADR 0009 says that time enters
the service through the `Clock` port, and ADR 0012 rejected a `DEFAULT now()` for
the same reason, so the use case reads the instant once, after the last send, and
passes it to the adapter as a parameter. Every row of a batch therefore carries
one stamp, which is later than the moment each row was actually sent and never
earlier. That is harmless for ordering, and it means `published_at` is the end of
the run and not the instant of each send.

**Not covered here.** The stream's size is bounded in ADR 0029. The outbox table
in PostgreSQL is not trimmed by this record, so its rows, marked or not, accumulate.
