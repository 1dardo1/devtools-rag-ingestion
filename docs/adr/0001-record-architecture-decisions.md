# 1. Record architecture decisions

- **Status:** Accepted
- **Last revised:** 2026-08-30

## Context

This system is built as a portfolio artifact. Its value depends less on the
features it ships than on whether the reasoning behind it can be reconstructed
and defended months later, by the author or by a reviewer reading the repository
for the first time.

Decisions made in code are invisible. A file shows what was chosen; it never
shows what was rejected, or why.

## Options considered

- **No formal record.** Rely on commit messages and memory. Cheap, and adequate
  for short-lived projects. Fails as soon as a decision needs to be revisited or
  explained to someone else.
- **A single design document.** One file describing the architecture. Easier to
  write, but it describes the current state rather than the history, and it
  silently loses the alternatives that were discarded.
- **Architecture Decision Records.** One file per decision, numbered
  sequentially, each stating what was chosen, what was rejected, and what the
  choice costs.

## Decision

Use Architecture Decision Records, following Michael Nygard's format.

An ADR is written whenever a decision is expensive to reverse: choosing a
technology, drawing a boundary between services, defining a contract, or
selecting between two architectural approaches.

Every ADR must state at least one rejected alternative and at least one negative
consequence. A decision presented without a cost is not a decision — it is a
default that was never examined.

### Records are edited in place, not superseded

When a decision changes, or when a record turns out to state something untrue,
the record itself is corrected. `docs/adr/` therefore shows only the decisions
currently in force, each described accurately.

The conventional practice is the opposite: records are immutable, and a change
is expressed by adding a new record that supersedes an old one, which stays in
the directory marked as superseded. That convention is rejected here. It grows
the directory faster than it grows the number of live decisions, and it means a
reader must reconstruct the current state by following a chain — the exact
failure the "single design document" option above was rejected for, arriving by
a different route. It also leaves incorrect statements sitting in the
repository, and a reader who lands on one has no way of knowing it was later
contradicted.

Correcting a record is an ordinary change: it goes through a branch and a pull
request, where the diff shows what moved and the description says why.

Each record therefore carries **`Last revised`**, not a creation date: the day
its contents were last known to be true. A record whose decision has never been
revisited still shows the day it was written, because nothing has changed since.
The alternative — keeping the original decision date — was rejected because a
reader checking whether a record is stale wants to know when it was last
confirmed, and `git log` answers the other question in a way a header field
cannot. Any claim inside a record that depends on a moment in time, such as a
version observed on PyPI, states that date explicitly rather than referring to
"this record".

## Consequences

**Positive.** The reasoning survives the author's memory. Reviewers can evaluate
judgement, not just output. Revisiting a decision starts from the original
context rather than from scratch.

Editing in place keeps the directory the size of the decision set rather than
the size of the project's history, and a reader can trust that every file
describes something currently true.

**Negative.** Writing an ADR costs time at the exact moment when momentum is
highest. There is a standing risk of writing them retroactively, which produces
justification rather than reasoning. ADRs also go stale silently: nothing in CI
fails when a record no longer reflects reality.

Editing in place means the file no longer carries its own history: what a
decision used to be, and when it changed, is visible only in `git log` and in
the pull request that changed it. That is a real loss — a reader skimming
`docs/adr/` sees the conclusion without the revision that produced it — and it
is accepted deliberately, on the grounds that a directory of accurate records is
worth more here than a directory that is also an archive. It puts weight on
commit messages and pull request descriptions that the records themselves used
to carry.
