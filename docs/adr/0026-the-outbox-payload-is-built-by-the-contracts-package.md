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
Carlos in conversation on 2026-11-24, and the choice to loosen the contract's
`source_url` the same day. The code was run: the unit and integration suites, and
the check of which URLs the domain and the contract accept. Statements about what
has not been executed are marked below.

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
  exists; the tag will be `v0.3.0`.
- **By tag.** Chosen. Contracts `0.2.0` shipped without `py.typed`, so under
  `mypy --strict` it cannot be used, and its `source_url` pattern was stricter
  than this service's own rule (below). `0.3.0` is the first release ingestion can
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

ADR 0014's other choices stand: `event_type` is a constant and never derived from
a class name (it is now the contract's `EVENT_TYPE`, not a literal of this
repository's), `occurred_at` is stored in both the column and the payload from one
value, and `publish` never contacts a broker.

**The contract is never stricter than the domain.** Reviewing this change showed
the contract refusing three `source_url` values the domain accepts: an upper-case
scheme, whitespace inside the URL, and a tab. Each would have been a document
stored and then refused at the outbox on every attempt, a permanent 500 for
something that used to return 202. The contract was loosened (its ADR 0007), and
two tests hold the rule from this side. One passes such URLs through
`_as_payload`. The other makes the contract refuse an event after the document row
is written and checks that neither the document nor an outbox row survives.

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

**The integration tests were run, but not in a container.** There is no Docker
daemon here, so the publisher's tests were run against a locally started
PostgreSQL 16, through a test-only plugin that stood in for `testcontainers`: 356
tests passed and coverage was 99%. CI, which does use the container, is still the
binding result.

**Negative: rows written before this change have no `schema_version`.** That
includes a test row in the public database (ADR 0025). The contract reads a
missing version as 1, so they remain valid, but it is a convention the contract
carries for this one history, not something ingestion enforces.

**Negative: the contract is now deliberately loose, and so is what a consumer can
assume.** Because it must accept everything the domain does, `source_url` reaches
a consumer as text that may not be a URL a browser would open. That cost is
recorded in the contracts repository's ADR 0007.

**Negative: `occurred_at` changed spelling.** `+00:00` became `Z`. Nothing has
read the outbox, so nothing broke, but it is exactly the kind of change that
becomes breaking once the relay ships.
