# 1. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-08-22

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
- **Architecture Decision Records.** One immutable file per decision, numbered
  sequentially, never edited after acceptance — superseded instead.

## Decision

Use Architecture Decision Records, following Michael Nygard's format.

An ADR is written whenever a decision is expensive to reverse: choosing a
technology, drawing a boundary between services, defining a contract, or
selecting between two architectural approaches.

Every ADR must state at least one rejected alternative and at least one negative
consequence. A decision presented without a cost is not a decision — it is a
default that was never examined.

## Consequences

**Positive.** The reasoning survives the author's memory. Reviewers can evaluate
judgement, not just output. Revisiting a decision starts from the original
context rather than from scratch.

**Negative.** Writing an ADR costs time at the exact moment when momentum is
highest. There is a standing risk of writing them retroactively, which produces
justification rather than reasoning. ADRs also go stale silently: nothing in CI
fails when a record no longer reflects reality.
