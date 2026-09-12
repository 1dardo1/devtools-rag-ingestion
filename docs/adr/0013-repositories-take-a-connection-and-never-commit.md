# 13. The PostgreSQL repositories take a connection and never commit

- **Status:** Accepted
- **Last revised:** 2026-09-12

## Context

ADR 0010 settled what the Phase 4 adapter is built *with* — psycopg 3 and SQL
written by hand. It did not settle two questions that only appear once the
adapter is actually written:

1. **Where does the connection come from?**
2. **Who decides when the work becomes durable?**

Both are ordinarily answered by reflex, and the reflex is wrong here. The reason
is 4.2, which is one unit away: the document and its outbox row must be written
**in the same transaction**, and `CLAUDE.md` calls that the single most
important invariant in the service. The `EventPublisher` port says the same and
adds that how the transaction is scoped "is not decided here, and cannot be".

That makes 4.1 load-bearing for a unit it does not contain. Whatever the adapter
does with connections either leaves room for one transaction spanning two
collaborators, or quietly makes it unreachable — and if it makes it unreachable,
4.2 is not a new unit but a rewrite of this one.

## Options considered

### Where the connection comes from

- **Each repository owns a connection pool** and borrows a connection per call.
  The conventional answer, the one most production adapters reach for, and the
  one with the best story about connection limits. **Rejected, and not on
  taste.** Each call would borrow its own connection, so each call would be its
  own transaction; `documents.add(...)` followed by `events.publish(...)` could
  not be atomic however the composition root arranged them. It forecloses the
  invariant the service exists to demonstrate.

- **Each repository takes a URL** and connects per call. The same defect, plus a
  TCP connection and authentication handshake per query.

- **A unit-of-work object** that owns the connection and hands out repositories.
  This may well be where 4.2 or 4.5 ends up, and the `EventPublisher` docstring
  already anticipates it. **Rejected for now**, because the abstraction would be
  invented before the thing it abstracts exists: there is no outbox publisher
  yet, no second implementation, and no caller. Guessing its shape a unit early
  is how an abstraction acquires the wrong seams.

- **The constructor takes a `psycopg.Connection`.** Chosen. The repository
  becomes a frozen dataclass around a connection with no lifecycle of its own,
  and two repositories handed the same connection are already one transaction —
  which is exactly the room 4.2 needs, available without a new abstraction.

### Who commits

- **The repository commits after each write.** The most forgiving option for a
  caller, and it destroys the invariant in one line: a committed `add` cannot be
  rolled back alongside an outbox row that failed to write.

- **The repository exposes its own `commit()`.** Rejected as redundant and
  misleading — the connection belongs to the caller, who already has `commit()`
  on it. A second route to the same operation only invites disagreement about
  which one is in charge.

- **The caller commits.** Chosen. `add` leaves the work pending.

## Decision

`PostgresDocumentRepository` and `PostgresCollectionRepository` each take a
`psycopg.Connection` in their constructor. **Neither commits, and neither rolls
back.** The transaction boundary belongs to whoever owns the connection: the
composition root in 4.5, or the unit of work 4.2 may turn out to need.

Rows become entities through the domain's own constructors, per ADR 0010. `get`
does not select the `content` column, which is what makes ADR 0012's reasoning
about TOAST true rather than merely plausible.

The ports are `Protocol`s, so nothing at runtime forces these classes to match
them. `tests/integration/test_postgres_repositories.py` declares the conformance
inside a `TYPE_CHECKING` block, which makes `mypy --strict` the assertion.

## Consequences

**Positive.** 4.2 requires no change to anything here: it writes an outbox row
on the connection it is given, and the atomicity follows. That is not a
prediction —
`TestTheTransactionBelongsToTheCaller` creates a collection and a document
through two repositories on one connection, rolls back, and asserts from a
second connection that neither survived. **Adding a single `commit()` to either
adapter fails that test**, which was confirmed by making the change and watching
it fail.

**Negative, and this is the sharp one: nothing prevents a caller passing a
connection in autocommit mode**, and if one does, every write is its own
transaction and the invariant is lost *silently*. psycopg has one `Connection`
type for both modes, so no signature can rule it out. The honest measure of how
easy that mistake is: **this repository's own test fixture uses
`autocommit=True`**, because most tests are not about transactions and an open
one would block the teardown. A runtime guard rejecting autocommit was
considered and not added — it would have broken those fixtures, which are
legitimate. 4.5 must get this right in one place, and 4.2 should consider
checking it where the outbox write happens.

**Negative: connection pooling is now nobody's job.** Pushing the connection
outward means the question of how many there are moved outward too, and no unit
currently owns it. It belongs with 4.5.

**Negative: `mypy` cannot see the mapping.** A row element is typed `Any`, so the
row-to-entity function is unchecked. Swapping `library_version` and `source_url`
in it — two adjacent nullable text columns — **typechecks cleanly**; that was
tried. Three tests caught it, and one of them caught it because `Metadata`
refuses a version string as a URL, which is ADR 0010's "rows become entities
through their own constructors" earning its place. The protection is the
integration suite and the domain's constructors, never the type checker.

**A driver error, not a domain error, on a lost race.** Two concurrent requests
submitting identical content can both pass `exists_with_content_hash`; the
partial unique index then refuses the second as `UniqueViolation`. Translating
that into a domain error is error-handling strategy, which `docs/BUILD-PLAN.md`
still carries as a decision due before 4.5. This adapter deliberately does not
pre-empt it.
