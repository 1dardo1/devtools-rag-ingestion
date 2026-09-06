# 9. Read the clock once, through a port, and let the instant travel

- **Status:** Accepted
- **Last revised:** 2026-09-06

## Context

Three decisions about time were taken at three different moments — the `Clock`
port in Phase 1, `Document.ingested_at` and the event's derived `occurred_at` in
Phase 2 — and none of them was recorded. The `Clock` in particular has shaped
the signature of every use case since it was introduced, and its only
justification lived in a docstring. `docs/COLLABORATION.md` asks for a record
when a decision is expensive to reverse, and reversing this one now would mean
touching every use case, every fake and every composition site at once.

They are one decision in three parts, which is why they get one record.

**Reading a clock is I/O wearing a disguise.** `datetime.now()` looks like a
pure function and behaves like a network call: the answer comes from outside the
process and differs every time. Left unguarded it becomes a hidden dependency on
real time, and any test that asserts on a timestamp either turns
non-deterministic or resorts to patching `datetime` — which couples the test to
the implementation it is supposed to be independent of.

The service has two timestamps, and they describe the same event. `Document`
records when this service took responsibility for a document.
`DocumentIngested` announces it. If those two values are produced separately
they can disagree, and a consumer reconciling the event against the record would
have no way to tell which is right.

**The outbox makes the difference load-bearing rather than cosmetic.** The relay
in `ROADMAP.md` 4.3 is a separate process that reads unpublished rows and
publishes them afterwards — a second later, or twenty minutes later if the
broker was down. A timestamp stamped at publication would make the event say the
document arrived when the queue drained.

## Options considered

- **An ambient clock: `datetime.now(UTC)` called where it is needed,** including
  as a dataclass `default_factory`. Zero ceremony, and it is what most Python
  code does. Rejected: it is precisely the hidden dependency above. It also
  contradicts the rule that `domain/` imports nothing external and depends on
  nothing it cannot be handed — a module that reads the system clock has an
  unwritten dependency on the machine it runs on.

- **A test-time freezing library** (`freezegun`, or `monkeypatch` on
  `datetime`). It permits the ambient clock and still gives deterministic tests,
  which is a genuine answer to the objection above. Rejected on three counts: it
  adds a dependency to do what an argument already does; it patches a module the
  code under test did not declare it uses, so the test knows more about the
  implementation than the interface does; and it leaves production code with a
  dependency that is invisible at the call site, where the port makes it a
  parameter a reader cannot miss.

- **The HTTP layer supplies the instant,** passing it into the use case. No port
  needed. Rejected: it moves a domain concern outside the application boundary
  and makes every caller — including a future CLI, a batch importer, a test —
  responsible for remembering that the instant must carry a timezone.

- **Two reads: one for the entity, one for the event.** The obvious shape if
  each object is considered on its own. Rejected because the two values can then
  differ, and nothing in the type system objects. That is a bug that appears
  only under load, when the two reads straddle a scheduler switch.

- **The event stamps itself, or the publisher stamps it.** Rejected in the same
  breath as the previous one: the adapter would need its own clock, which
  reintroduces the second read, and it would move the decision of *what is
  announced* into infrastructure when Phase 3 puts the schema in the contracts
  repository.

- **One read, through a port, stored on the entity, derived by the event.**
  Chosen.

## Decision

**`Clock` is a port**, in `rag_ingestion.domain.ports`, with a single `now()`
returning a timezone-aware `datetime`. Production supplies a clock that reads
the system time; a test supplies one that returns a fixed instant, and the
assertion becomes an equality rather than a tolerance.

**The use case reads it exactly once per ingestion.** There is one
`clock.now()` call in the whole of `src/`, in `IngestDocument.execute`. A test
asserts the count, so a second read is a failing test rather than a review
question.

**The instant becomes `Document.ingested_at`,** a required field. It is named
for what happened in this domain — the service took responsibility — rather than
`created_at`, which is persistence vocabulary in a layer that does not know a
database exists and which names the wrong event.

**`DocumentIngested.about(document)` derives `occurred_at` from it** and takes
no instant of its own. One value, one source: the record and the announcement
cannot disagree, and `mypy` rejects any attempt to supply a different one.
`occurred_at` therefore answers *when the ingestion happened*, never when it was
managed to be told, which is what makes the outbox delay harmless.

**Naive timestamps are refused** by both `Document` and `DocumentIngested`,
raising `NaiveTimestampError`. ADR 0006 selected `ruff`'s `DTZ` family for the
same class of bug; this is the runtime half of that guard, for instants that
arrive from outside the process.

## Consequences

**Positive.** Every test that touches time names the instant it expects, with no
plugin, no patching and no tolerance windows. The record and the announcement
agree structurally rather than by convention. The outbox can publish an hour
late without the event lying. And the dependency is visible: a use case that
needs the time says so in its constructor, where a reader cannot miss it.

**Negative.** Every use case that creates or transitions an entity now needs a
clock injected, and the composition root in 4.5 grows a little for each one.
That cost is paid by units that have nothing to do with time except that they
happen to record when they ran.

The validation is duplicated: `Document` checks the timezone, and
`DocumentIngested` checks it again on a value that has already been checked. It
is cheap and it guards direct construction of the event, which `about` no longer
covers — but it is two places that must agree about what a valid instant is.

`Document` carries a field no domain rule reads. That is the same criticism that
would exclude it, answered by the fact that `metadata` is in the same position:
the entity already carries what a caller must be told as well as what a rule
must decide. It is a precedent worth noticing rather than one worth extending
without argument.

**The sharpest gap: status transitions carry no time at all.** `start_processing`,
`mark_indexed` and `mark_failed` record that a document moved, not when. Nothing
can therefore answer "which documents have been stuck in `PROCESSING` for an
hour", and the relay in 4.3 runs unattended, where silence and success look
identical. Adding it means giving all three methods an instant parameter and
coupling the entity to time on every move, which was judged premature while the
retry and give-up rule is still undecided. This is the first thing to revisit
when 4.3 exists.
