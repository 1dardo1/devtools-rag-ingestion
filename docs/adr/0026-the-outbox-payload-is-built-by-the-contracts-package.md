# 26. The outbox payload is built by the contracts package

- **Status:** Accepted
- **Last revised:** 2026-11-24

## Context

ADR 0014 wrote the outbox payload by hand, under the domain's own names, and said
that Phase 3 would own the contract and that `_as_payload` was the one function
it would change. Phase 3 has produced the contract: `rag_contracts.events.DocumentIngested`
in `devtools-rag-contracts`. The schema is the contracts repository's ADR 0007;
how it is versioned, rolled out and pinned is that repository's ADR 0008. This
record restates neither. It records only what the *producer* does about them.

The window ADR 0014 named is still open: the relay (4.3) has not shipped, so
nothing has read the outbox and changing the payload is still free. After 4.3
every change is a change to something already published. That is why this is
decided now rather than alongside the relay.

**Where the facts came from.** The decision and its alternatives were approved by
Carlos in conversation on 2026-11-24. The code facts (`_as_payload` in
`infrastructure/postgres/outbox_event_publisher.py`, the domain import guard) were
given to the writer of this record and not re-derived from a run. Statements about
what has and has not been executed are marked below.

## Options considered

### How the producer stays in agreement with the contract

- **Keep the hand-written dict and add a compatibility test.** Rejected. A test
  proves that today's payload is accepted; it does not stop the next change from
  writing one the contract refuses. The failure would then surface in the
  consumer, after the relay had published the event, far from the code that
  caused it.
- **Copy the schema into this repository.** Rejected. Principle 6 of
  `ARCHITECTURE.md`: event schemas live only in the contracts repository.
- **Install the contracts package and build the model in `_as_payload`.** Chosen.
  The contract model validates before the outbox `INSERT`, inside the document's
  transaction, so an event the contract would refuse rolls the document back with
  it. Producer and contract cannot disagree silently, and the invariant of
  CLAUDE.md (document and outbox row in one transaction) is what carries the
  refusal.

### Where the dependency may be imported

- **From `domain/`.** Rejected. The domain imports nothing external, and
  `tests/unit/domain/test_the_domain_imports_nothing_external.py` enforces it.
  `rag_contracts` is imported only in `infrastructure/`; the domain's
  `DocumentIngested` is untouched and `_as_payload` translates it.

### How the dependency is pinned

- **By commit hash.** Rejected as the end state. A reviewer cannot read from a
  hash whether an update is a patch or a major version. Contracts ADR 0008 says to
  pin by tag, so the pin is a tag. A commit `rev` is used only until the tag
  exists; the tag will be `v0.2.1`.
- **By tag.** Chosen. Contracts `0.2.0` shipped without `py.typed`, so under
  `mypy --strict` it cannot be used; `0.2.1` is the first release ingestion can
  consume.

### How the image gets a Git dependency

The `python:3.14-slim` base has no `git`, and `uv` needs it to fetch a Git
dependency.

- **Install `ca-certificates` and `git` in the build stage only.** Chosen. The
  runtime stage never has them, so they do not ship.
- **Point `uv` at a GitHub archive URL instead.** Rejected, but **not evaluated in
  depth**; the only reason on record is that the lockfile would then lose the
  git-source semantics (a tag and a resolved commit) that make the pin
  reviewable. It may deserve a proper look if the `git` step proves costly.

## Decision

`_as_payload` builds `rag_contracts.events.DocumentIngested` and the publisher
writes `model_dump(mode="json")` instead of a hand-written dict. Two things in the
payload change as a result: it now carries `schema_version: 1`, and `occurred_at`
is written in UTC with a `Z`. `rag_contracts` is a Git dependency pinned by tag
and imported only under `infrastructure/`. The `Dockerfile` installs
`ca-certificates` and `git` in its build stage.

ADR 0014's other choices stand: a literal `event_type`, `occurred_at` stored in
both the column and the payload from one value, and `publish` never contacting a
broker.

## Consequences

**Positive.** An invalid event cannot reach the outbox, and the refusal is
atomic with the document. A producer change that the contract rejects fails here,
in the transaction that caused it.

**Negative: the metadata rules now exist twice.** The domain has a closed
`DocType` enum; the contract constrains the same field with the pattern
`^[a-z_]+$`. Nothing in the type system ties them together. Only a test does:
`tests/unit/infrastructure/test_the_outbox_payload_is_the_contract.py`
parametrizes over every `DocType` value. A new member that violates the pattern
fails that test; a rule changed on one side only and not exercised by it would not.

**Negative: a release of another repository is now a dependency of a deploy.**
Builds of the image and CI need network access to `github.com`. The contracts
repository is public, so no credential is involved, but an outage or a deleted tag
breaks a build that nothing in this repository changed.

**Negative: the image build with `git` has not been run by the writer of this
change.** This environment has a Docker client and no daemon. The `image` job in
CI (ADR 0020) is the only proof that the build stage works and that the runtime
stage does not need `git`.

**Negative: the integration tests could not be run locally either.** They read the
row back from PostgreSQL and validate it against the contract, and are proved only
by CI.

**Negative: rows written before this change have no `schema_version`.** That
includes a test row in the public database (ADR 0025). The contract reads a
missing version as 1, so they remain valid, but it is a convention the contract
carries for this one history, not something ingestion enforces.

**Negative: `occurred_at` changed spelling.** `+00:00` became `Z`. Nothing has
read the outbox, so nothing broke, but it is exactly the kind of change that
becomes breaking once the relay ships.
