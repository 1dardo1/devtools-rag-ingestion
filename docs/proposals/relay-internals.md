# Proposal: the relay's internals (ROADMAP 4.3)

- **Status:** Proposed, awaiting approval (`docs/COLLABORATION.md` §3 and §4)
- **Scope:** how the relay reads the outbox, publishes to Redis Streams, marks
  rows, retries and bounds the stream. It builds on ADR 0027, which decided where
  the relay runs and how its silence is measured, and does not revisit that.
- **Nothing here is code.** Once approved, the decisions marked *ADR* become
  records in `docs/adr/`, and the rest become the 4.3 pull requests.

## What is being built

A relay, `rag_ingestion.relay`, with two modes from ADR 0027: `--once` drains the
outbox and exits, `--loop` keeps running. Each run reads unpublished rows in
batches, writes each one to a Redis stream, and marks it published. The relay is a
separate process from the API and shares no lifecycle with it.

## Decisions

### 1. Publish, then mark, inside one database transaction (ADR)

Each batch runs in one transaction:

```sql
SELECT outbox_id, event_type, payload, occurred_at
FROM outbox
WHERE published_at IS NULL
ORDER BY outbox_id
LIMIT 100
FOR UPDATE SKIP LOCKED;
```

Each row is sent with `XADD`. Then one statement sets `published_at = now()` for
the batch, and the transaction commits.

**Consequence:** a crash between `XADD` and `COMMIT` publishes the batch again on
the next run. That is at-least-once delivery, which ADR 0003 already accepts, and
the consumer must be idempotent (principle 7).

**Rejected: mark, then publish.** A crash after marking and before publishing
loses the event silently. That is at-most-once, which the architecture forbids.

**Rejected: one transaction spanning the database and Redis.** Redis cannot join a
PostgreSQL transaction, so no such guarantee exists to be had.

### 2. `FOR UPDATE SKIP LOCKED`, so overlapping runs do not duplicate work (ADR)

A scheduled run can overlap with a slow one, or with a manual run. `SKIP LOCKED`
makes the second run skip rows the first has locked, rather than wait or publish
them twice.

**Rejected: a lock row or an advisory lock held for the whole run.** It works, but
it is a second locking mechanism when the table already provides row locks, and a
run that dies holds it until the session ends.

**Rejected: no locking.** Two overlapping runs would publish the same rows, and
the consumers would absorb the duplicates at a cost that grows with the schedule.

### 3. Batch size 100 (needs approval)

The batch bounds how long a transaction stays open while rows are locked. 100
keeps each transaction well under a second at the rates this service expects.

**Rejected: batch size 1.** It makes each run longer without reducing the number of
Redis commands. Each event is one `XADD` either way.

**Rejected: an unbounded batch.** A large backlog would hold locks for minutes and
could exceed the run's time budget on a free runner.

This is a guess about the rate, not a measurement. It is a configuration value,
so it can change without code.

### 4. Retries: a bounded number, then the run fails (needs approval)

A failed `XADD` is retried three times, after 1, 2 and 4 seconds. If it still
fails, the batch's transaction rolls back, the run logs the failure and exits
non-zero. The next scheduled run starts over from the oldest unpublished row.

Nothing is lost by this. Rows stay unpublished until marked, and the non-zero exit
is what the failed workflow run shows (ADR 0027, part 3).

**Rejected: retrying inside the process until success.** It holds a runner for as
long as Redis is down, and spends the free minutes on waiting.

**Rejected: a dead-letter table.** It needs a migration (ADR and approval under
`COLLABORATION.md` §4), and no failure mode yet needs one. Revisit when a row
fails repeatedly for a reason that is not transient.

**Decided (Carlos, 2026-11-26):** a row whose payload cannot be sent at all fails
the run and logs its `outbox_id`, so the backlog alarm fires. The batch stays
blocked until the row is fixed by hand. Skipping and marking it would lose it;
skipping without marking would keep the alarm on forever.

### 5. Stream trimming: `XADD ... MAXLEN ~ 100000` (needs approval)

A stream only grows. `XACK` does not delete a message, which was checked against
a local Redis on 2026-11-26. Upstash's free plan has 256 MB, so the stream needs a
bound.

The bound is a count, approximate for speed (`~`). At a guessed 1 KB per event,
100000 events is about 100 MB, which leaves room on the free plan. The 1 KB figure
is an estimate and must be measured with the real payload.

**Rejected: trimming by age (`MINID`).** It is the more honest bound for a
consumer that may be down for a week, but it needs the retention window agreed
with the retrieval service, which does not exist yet.

**Rejected: no trimming.** The stream reaches the plan's limit in time, and then
every `XADD` fails.

**Open question, and the main risk of this choice:** `MAXLEN` removes the oldest
messages whether or not a consumer has read them. A retrieval service that is down
for longer than the stream holds loses events silently. The mitigation is to size
the bound above the longest outage we expect, and to revisit once retrieval's
needs are known. Say if you prefer to block the proposal until then.

### 6. The broker is a port, and Redis is an adapter (needs approval)

The relay depends on a `Protocol`, `EventBroker`, with one method that publishes
one envelope. The Redis client is an adapter in `infrastructure/`. The domain is
untouched.

**Rejected: calling Redis directly from the relay.** It works, but the relay then
cannot be tested without a Redis server, and the unit suite would need one.

**Rejected: an abstract base class.** `CLAUDE.md` requires `Protocol`.

### 7. A synchronous Redis client, `redis-py` (needs approval, a new dependency)

Ports and adapters are synchronous (ADR 0007 and `CLAUDE.md`), so the relay uses
the synchronous client.

**Rejected: writing the RESP protocol by hand.** It is not thirty lines once TLS,
authentication and reconnection are included, and it would be ours to maintain.

**Rejected: Upstash's REST API through `httpx`.** It needs a dependency too, and
it would make the adapter depend on a vendor-specific API when the Redis protocol
is the standard. Recorded here because it is the natural alternative if the
Upstash test in ADR 0027 shows the free plan cannot use the Redis protocol.

### 8. Configuration: three values, read from the environment (needs approval)

`REDIS_URL`, `RELAY_BATCH_SIZE` (default 100) and `RELAY_STREAM_NAME` (default
`rag:events`). `REDIS_URL` is a secret, so it lives in the GitHub Environment and
the developer's `.env`, and never in the repository. The guard
`tests/unit/test_no_secret_is_committed.py` must still pass.

## What this does NOT include

- The GitHub Actions workflow that runs `--once` every 5 minutes. It touches CI
  and deployment, so it is a separate pull request under `COLLABORATION.md` §4.
- The compose service for the relay and for Redis (ADR 0021 left both out).
- The alarm threshold of 30 minutes (ADR 0027, part 3), which belongs to the
  workflow pull request.
- Retrieval's consumption, consumer groups, and the content-fetch and
  indexing-report gaps named in `devtools-rag-contracts`. None of them belong to
  the relay.
- Global ordering. `outbox_id` orders assignment, not commit (ADR 0012), so the
  relay does not promise order across batches.

## Test plan

- **Unit tests** against a fake `EventBroker`, covering: publish-then-mark order,
  rollback when a publish fails, retry counts and backoff, and the non-zero exit.
- **Integration tests** with real containers (ADR 0011): PostgreSQL 16, and Redis
  through `testcontainers`, marked `@pytest.mark.integration`. They prove that a
  crash between publish and commit republishes, that two overlapping runs publish
  each row once in the common case, and that a stream never exceeds the bound.
- **Not tested here:** Upstash itself. That is the ten-minute test in ADR 0027,
  and no unit or container test can replace it.

## Why this way (teaching notes)

- **The pattern is a transactional outbox with a polling publisher.** Look up
  "transactional outbox" (Chris Richardson's microservices.io). The relay is the
  polling publisher.
- **`FOR UPDATE SKIP LOCKED` is the database's work queue.** The C# or Java
  analogue is a job table that several workers drain. Each worker takes a batch
  and skips what others hold. It is why a queue can live in PostgreSQL.
- **At-least-once is a choice, not a defect.** It moves the duplicate problem to
  the consumer, which is cheap to solve with an idempotency key and expensive to
  solve in the broker. ADR 0003 already made this trade.
- **The trade-off in §5 is the one to understand before approving.** `MAXLEN`
  bounds storage by discarding history, so the bound is a claim about how long
  consumers can be down.

## Questions for the reviewer

1. Approve §4's open question (fail the run on an unsendable row), or prefer a
   different choice?
2. Approve §5's bound of 100000 now, or block until retrieval states its outage
   tolerance?
3. Approve `redis-py` as a dependency (§7)?

Question 1 is decided (see §4).
