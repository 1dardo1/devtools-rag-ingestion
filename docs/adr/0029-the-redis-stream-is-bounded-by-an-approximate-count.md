# 29. The Redis stream is bounded by an approximate count of 100000 messages

- **Status:** Accepted
- **Last revised:** 2026-11-26

## Context

ADR 0028 has the relay send every event to a Redis stream before its row is
marked published. Nothing in the relay removes a message from the stream, and
nothing else in this repository does either. The consumer group's acknowledgement
does not help: `XACK` does not delete a message. That was checked against a local
Redis on 2026-11-26. A stream therefore only grows, and something has to bound it.

The bound is needed because of the broker's free plan. ADR 0027 records Upstash's
figures as 256 MB and 500K commands a month, from Upstash's pricing page. Those
figures were not verified by the Upstash test that ADR 0027 requires, so this
record **depends on that test**, as does the question of whether stream commands
count against the monthly allowance in the usual way.

The per-event size of 1 KB is an estimate, not a measurement. It is the basis of the
number 100000, which comes to about 100 MB at that estimate.

The fallback broker, Redis Cloud's free plan, has 30 MB, as ADR 0027 records. At the
same estimate, 100000 events do not fit in it. The bound below is therefore tied to
the Upstash choice, and would have to be recomputed before a switch.

The retention a consumer needs is not known. The retrieval repository exists but is
empty, and it has not stated how long it can be down.

**Where the facts came from.** The approved proposal
`docs/proposals/relay-internals.md`, decision 5, approved by Carlos on 2026-11-26,
which decided the bound. The `XACK` behaviour was checked against a local Redis on
2026-11-26. The plan limits are from ADR 0027.

## Options considered

- **An approximate count of 100000 messages.** Chosen. It bounds storage with one
  number, and it does not depend on any consumer's position.
- **Trimming by age, with `MINID`.** Rejected for now. It is the more honest bound
  for a consumer that may be down for a week, because it states how long a message
  is kept. It needs the retention window agreed with the retrieval service, and that
  service does not exist yet, so the window would be a guess dressed as an agreement.
- **No trimming.** Rejected. The stream reaches the plan's limit in time, and then
  every `XADD` fails. The relay can no longer publish, the backlog grows, and the
  failure arrives when the service is least able to absorb it.

## Decision

Every publish is an `XADD` with `MAXLEN ~ 100000` on the stream. The stream name is
`rag:events` by default and can be changed through `RELAY_STREAM_NAME`.

The count is approximate, because the `~` form is cheaper for Redis than an exact
bound. Redis's documentation describes the approximate form as allowed to keep
somewhat more than the count. That behaviour is taken from the documentation and was
not measured here.

## Consequences

**Negative: the bound discards events that nobody has read.** `MAXLEN` removes the
oldest messages whether or not a consumer has read them. If the retrieval service is
down for longer than the stream holds, the events it missed are gone, and nothing
reports the loss. The stream holds a number of events, not a span of time, so how
long a consumer may be down depends on the ingestion rate, which has not been
measured. Nothing in this record detects a trim that removed unread events.

**Negative: the number is decided before the figure it depends on.** Carlos decided
the bound on 2026-11-26, before the retrieval service has said how long it can be
down. This record is expected to be corrected in place when that happens, which is
the rule of ADR 0001. The likely correction is either to replace the count with a
bound by age, `MINID`, or to size the count from the outage the retrieval service
states. Either way, this record is a provisional decision, and it says so.

**Negative: the figure rests on two unverified numbers.** The 100000 comes from a
1 KB estimate, and the bound is safe only while the plan's 256 MB limit holds. If the
real payload is larger, the stream can reach the plan's limit before the count does,
and `XADD` fails. If the fallback broker is needed, 100000 events at the estimate do
not fit its 30 MB, so the count must be recomputed before the switch.

**Negative: this record bounds the stream and not the outbox.** The rows in the
PostgreSQL `outbox` table are not removed by this decision, so the table grows with
every event whether or not the stream is trimmed. The free database's limit is
recorded in ADR 0025.

**Positive.** The stream's storage is bounded by one number, and the plan's limit is
not reached by a stream that no one reads. Publishing keeps working for as long as
the stream's entries fit the bound and the size estimate holds.
