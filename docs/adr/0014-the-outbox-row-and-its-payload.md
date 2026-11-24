# 14. The outbox row, its payload, and who owns the contract

- **Status:** Accepted
- **Last revised:** 2026-11-24

## Context

Unit 4.2 is the one `ROADMAP.md` singles out: "the outbox is the deliverable,
not the plumbing", and "the most defensible piece of engineering in this
service". ADR 0013 did the structural work a unit early — the repositories take
a connection and never commit — so the transaction this unit needs already
exists. What 4.2 has to decide is narrower and mostly about the *message*.

One question looked like a blocker and is not. ADR 0012 left the outbox payload
deliberately opaque because "Phase 3 fixes the published payload in
`devtools-rag-contracts`", and when this was written Phase 3 had not happened.
**It has now, and the hand-written payload described below is gone (ADR 0026):**
the payload is built by `rag_contracts.events.DocumentIngested`. The reasoning
that follows is how 4.2 got there; the sections that changed say so. The dependency
graph in `docs/BUILD-PLAN.md` is explicit: `U41 --> U42 --> U43` and
`EXT3 --> U43`. **Only the relay is blocked on Phase 3**, because the relay is
what puts a message on the wire. The outbox row is internal, and writing one
needs a shape, not a ratified contract.

## Options considered

### What goes in the payload

- **Invent a wire format now** — envelope version, `type`/`data` split, renamed
  keys in whatever convention seems likely. Rejected: it creates a *second*
  shape for Phase 3 to reconcile with the one `ROADMAP.md` 1.4 already agreed,
  and guessing at a convention in the repository that does not own it is how two
  repositories end up disagreeing politely forever.

- **Wait for Phase 3.** The cautious reading, and it contradicts the build plan:
  4.2 is not blocked, and stalling the centrepiece behind another repository to
  avoid writing down a shape that is already agreed trades real progress for
  imagined safety.

- **Serialise the event's own fields under the domain's own names.** Chosen at
  the time, as a stopgap. `DocumentIngested` carries exactly five things and
  `ROADMAP.md` 1.4 required that shape be agreed *before* Phase 3 turns it into a
  published schema. This wrote that agreement down and nothing more. **The
  contracts repository owns the contract** — versioning, the formal schema, any
  renaming — and `_as_payload` was the single function it would change. It has:
  `_as_payload` now builds the contract's model (ADR 0026).

### Where `event_type` comes from

- **`type(event).__name__`.** One line, no constant, automatically correct.
  Rejected: the class name is Python's and a rename is a refactor, while this
  string is on the wire and a rename is a breaking change for every consumer.
  Deriving one from the other means a refactor silently publishes a different
  event type, and nothing fails until a consumer stops recognising messages.

- **A literal constant.** Chosen. `_EVENT_TYPE = "DocumentIngested"`.

### Whether `occurred_at` is stored twice

It is both a column on `outbox` and a field in the payload.

- **Column only**, with the relay merging it into the message it publishes.
  Rejected, and this is the interesting one: it would make the **relay** decide
  the message's shape. The relay should be a dumb pipe — read a row, send its
  payload, mark it sent — because a pipe that assembles messages is a second
  place the contract lives.

- **Payload only.** Rejected: the envelope loses a typed `timestamptz`, and the
  relay's ordering and any future retention reasoning would have to reach into
  JSON.

- **Both, written from one value in one statement.** Chosen. They are not
  independent copies that could drift; there is one `event.occurred_at` and it
  is passed twice in the same `INSERT`.

### Whether a unit of work is needed

The `EventPublisher` port says the transaction scoping "may well need a unit-of-
work abstraction that does not exist yet". **It turned out not to.** Connection
injection from ADR 0013 already makes the document write and the outbox write
one transaction; a unit of work would add an object whose only job is to hold
the connection that is already being held. Rejected on the same grounds as in
ADR 0013, now with evidence rather than anticipation.

## Decision

`PostgresOutboxEventPublisher` takes a `psycopg.Connection`, never commits, and
writes one row per event with `event_type`, a `jsonb` payload and `occurred_at`.
`published_at` is omitted from the `INSERT` rather than set to `NULL`: absence is
how a row says "not yet sent", and it is what the partial index uses to find the
backlog.

**`publish` must never contact a broker.** Not as a matter of layering, but
because a socket cannot be rolled back: a network call here would reintroduce
exactly the inconsistency the outbox exists to remove.

The payload is the output of `rag_contracts.events.DocumentIngested`'s
`model_dump(mode="json")` (ADR 0026): the event's five fields plus
`schema_version: 1`, with `UUID`s as strings and `occurred_at` in UTC with a `Z`.
The conversion is the contract model's, not hand-written; psycopg's `Jsonb` still
refuses a raw `UUID` and a raw `datetime`, which is why the dump is in JSON mode.

## Consequences

**Positive, and this is the claim the unit exists to make: the invariant is
proved through the real use case, not through the adapters in isolation.**
`TestTheDocumentAndItsOutboxRowAreAtomic` builds `IngestDocument` from the three
real adapters on one connection and shows that one commit makes both durable,
a rollback loses both, and a genuine `UniqueViolation` mid-transaction takes both
down together. Three mutations were applied and reverted to confirm the tests
bite: adding `commit()` to the publisher fails two of them; **wiring the
publisher to a different connection fails the same two**; dropping `occurred_at`
from the payload fails the payload test.

**Negative: the invariant is only as strong as 4.5's wiring, and no type
protects it.** A publisher and a repository on two different connections
typecheck perfectly and are not atomic. The mutation above is precisely that
mistake, which means the test that catches it is an integration test of the
*composition*, not of any one class. 4.5 must build all three adapters from one
connection and commit once, and that file deserves more care than its size
suggests.

**Negative: the payload changed when Phase 3 landed**, and rows written before
then carry the old shape: no `schema_version`, and `occurred_at` ending in
`+00:00`. That is harmless because nothing reads them — there is no relay and no
retrieval service; the contract reads a missing version as 1 (ADR 0026). **The
window closes when 4.3 ships**, because from then on a shape change is a change
to something that has been published.

**Negative: "was this document announced?" is not a cheap question.** ADR 0012
kept the outbox envelope event-type-agnostic and gave it no `document_id`
column, so the answer requires `payload->>'document_id'` with no index behind it.
That cost was abstract when the schema was written and is concrete now. It is
paid once per investigation rather than once per ingestion, which is why the
generic envelope still looks right — but a `document_id` column remains the
obvious thing to add if operational reality disagrees.

**`jsonb` normalises key order**, so the bytes read back are not the bytes
written. ADR 0012 accepted that; it matters here only if a payload is ever
signed.
