# 16. Structured logging on the standard library

- **Status:** Accepted
- **Last revised:** 2026-09-12

## Context

`docs/BUILD-PLAN.md` has carried this as a `[+]` item — work the roadmap did not
name — due before 4.5, on the grounds that "neither `ROADMAP.md` nor
`ARCHITECTURE.md` gives this service an observability story". Its statement of
the problem is specific:

> The relay runs unattended, where silence and success look identical. Without
> it, a relay that has quietly stopped announcing anything looks exactly like a
> relay with nothing to announce.

**That problem is not solved by logging errors, and noticing why reframes this
decision.** A relay that has crashed writes nothing. A relay with an empty
outbox also writes nothing. No amount of care about how failures are reported
distinguishes them, because neither case produces a failure to report. What
distinguishes them is something that speaks when there is *nothing* to say — a
heartbeat carrying the backlog depth, or a reading of that depth exposed
somewhere a person or a probe can ask.

So this ADR settles the **mechanism** only, which is what 4.5 needs in order to
configure anything. **The second half is named here as a decision still due,
before 4.3**, and one option is worth recording now because it falls out of the
architecture rather than being bolted on: `ARCHITECTURE.md` says the relay and
the API do not share a lifecycle, but they do share a database. The API can
report *the age of the oldest unpublished outbox row*, which is the relay's
liveness measured through state both processes already touch — no coupling, no
new channel. That is a proposal, not a decision.

## Options considered

### The mechanism

- **`structlog`.** Purpose-built for structured logging, widely used, and it
  supports 3.14. Rejected on a specific rather than a general objection: the way
  it is used in a real service is through `structlog.stdlib`, bridging to the
  standard library — so the standard library still has to be configured and
  understood, and the dependency buys ergonomics on top of work that still has
  to be done. For a service whose logging surface is a handful of call sites,
  that is a poor trade.

- **OpenTelemetry.** Traces, metrics and logs together, and the right answer for
  a distributed system with a collector to send to. Rejected as premature: there
  is no collector, Phase 5 is a single container, and adopting it now means
  configuring an exporter endpoint that does not exist. It is also the option
  most worth revisiting once there are two services talking to each other, which
  is a Phase 9 question, not this one.

- **`loguru`.** Pleasant to use and deliberately not standard-library-compatible,
  which disqualifies it here for the reason below.

- **The standard library's `logging`, with a JSON formatter.** Chosen, and the
  argument that settled it is specific to this repository rather than general:
  **ADR 0006 enabled `ruff`'s `G` (flake8-logging-format) and `LOG`
  (flake8-logging) families, and both lint `logging` and nothing else.** Two of
  the twenty-three rule families chosen for this project have been watching code
  that did not exist. Any library that is not the standard one leaves them
  watching nothing — which would mean either carrying two dead rule families or
  reopening ADR 0006. No new dependency either.

### JSON or human-readable text

JSON, one object per line, and the cost is real: a person tailing the log locally
reads worse output than a formatted line would give them. Rejected text anyway,
because Phase 5 runs this in a container where stdout *is* the log and the thing
reading it is a platform, not a person. A development-only pretty formatter can
be added when somebody is annoyed enough to want it; a log that cannot be queried
in production cannot be fixed after the incident.

### stdout or stderr

stdout. In a container both end up in the same place, and leaving stderr to the
runtime's own complaints keeps two kinds of output distinguishable.

### Where `extra` fields go

`ruff`'s G004 forbids f-strings in logging calls specifically to push callers
towards `extra`, so the formatter has to render it — a rule that directs people
to a mechanism producing nothing would be worse than no rule.

- **Merged into the top level.** More ergonomic to query: `document_id` rather
  than `context.document_id`. Rejected because a caller passing
  `extra={"level": ...}` then has to either overwrite the record's real level or
  be silently dropped, and both are bad. The choice would be between corrupting
  the envelope and losing the caller's field.

- **Nested under `context`.** Chosen. The collision becomes structurally
  impossible rather than documented, which is the same envelope-and-payload split
  the outbox uses and for the same reason.

## Decision

`rag_ingestion/observability.py` — a top-level module beside `config.py` in the
layout `ARCHITECTURE.md` sets out, because this is cross-cutting configuration
rather than an adapter for a port. It is named for the problem rather than the
mechanism, so the backlog-age reading belongs there too when 4.3 takes that
decision.

`configure(level, stream)` installs one `StreamHandler` on the root logger with a
`JsonFormatter`. Three details are load-bearing:

- **`force=True`.** Configuring twice must not log twice, and that is not
  hypothetical: Alembic's `env.py` configures logging too, whenever migrations
  are run in process.
- **`default=repr` on `json.dumps`.** An unserialisable value is rendered lossily
  rather than raising. A logging call that throws takes down the request it was
  describing, which is a worse outcome than an approximate field.
- **The reserved-attribute set is computed from a throwaway `LogRecord`**, not
  written out by hand, so a Python release that adds an attribute does not start
  leaking it as though a caller had passed it.

`configure` is **not** called on import, for the same reason `create_app` is a
factory: a module whose import reconfigures the root logger cannot be imported by
a test that wanted something else.

## Consequences

**Positive.** No new dependency, and `G` and `LOG` finally lint something.
Eleven tests cover the contract, and four mutations confirm they bite: merging
`extra` flat fails three of them, removing `force=True` fails ten, using
`record.msg` instead of `getMessage()` fails the `%`-formatting test, and dropping
`default=repr` fails the unserialisable-value test.

**Negative: the problem in the Context is still open.** This ADR settles how the
service speaks, not whether its silence is legible. Naming that explicitly is the
point; leaving this item marked "done" while the relay's silence remains
ambiguous would be the worse outcome. **Due before 4.3.**

**Negative: there is no request or correlation identifier.** Several log lines
from one request cannot be stitched together, which is exactly what makes an
incident hard to read. 4.5 is where that would be added — a middleware minting an
id and a `contextvars` default the formatter picks up — and it is deliberately
not done here, because a correlation id with one call site logging is
scaffolding.

**Negative: nothing redacts anything.** A caller who puts a secret in `extra`
logs the secret. The mitigation today is that nothing does; Phase 13 is where
that assumption should stop being trusted.

**Negative: `default=repr` is lossy**, and JSON read by a human is worse than a
formatted line. Both accepted above, both cheap to revisit.
