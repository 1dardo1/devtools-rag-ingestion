# 30. The relay uses redis-py, the synchronous client, to talk to Redis

- **Status:** Accepted
- **Last revised:** 2026-11-26

## Context

ADR 0027 chose Upstash's free plan for Redis, with Redis Cloud's free plan as the
fallback. Upstash offers both the Redis protocol and a REST API. Which of the two
the relay speaks is the question this record answers.

**This record depends on the Upstash test in ADR 0027.** The test has not been run.
It checks whether the free plan persists data and serves `XADD`, `XGROUP CREATE`,
`XREADGROUP` and `XACK` over the Redis protocol. If Upstash cannot serve the Redis
protocol on the free plan, the REST path becomes the decision, and this record is
corrected in place. The chosen client is a dependency of the relay's adapter, not of
its logic, so that correction touches the adapter and not the relay.

Ports and adapters are synchronous (ADR 0007 and `CLAUDE.md`), so the relay's
client has to be synchronous too.

**Where the facts came from.** The approved proposal
`docs/proposals/relay-internals.md`, decision 7, approved by Carlos on 2026-11-26,
with the Upstash caveat stated in the proposal. Adding a dependency requires approval
under `docs/COLLABORATION.md`, section 4. The proposal records that approval. This
record does not restate the process.

## Options considered

- **redis-py, the synchronous client.** Chosen. It speaks the Redis protocol, it is
  synchronous, and the relay's adapter is the only code that imports it.
- **Writing the RESP protocol by hand.** Rejected. It is not thirty lines once TLS,
  authentication and reconnection are included. It would also be ours to maintain
  for as long as the relay exists.
- **Upstash's REST API through `httpx`.** Rejected, for two reasons. It needs a
  dependency too, so it saves nothing on the count of dependencies. And it ties the
  adapter to one vendor's API, where the Redis protocol is the standard. It is the
  natural alternative if the Upstash test fails, and this record says so.

## Decision

Add redis-py as a runtime dependency. It is imported only by the Redis adapter in
`infrastructure/`. The relay depends on the broker port named in the proposal, and
never on the client, so the domain and the relay's use case do not import it.

## Consequences

**Negative: a new permanent dependency.** The project now depends on a third-party
package to keep up to date, and on its maintainers for security fixes. The cost is
named here, and is accepted in exchange for not maintaining a protocol
implementation.

**Negative: the choice is conditional on an untested broker.** Until the Upstash
test passes, this record rests on an assumption. If the test fails, the record is
corrected in place to the REST path or to the fallback broker, and the adapter
changes with it. The port does not.

**Negative: the lockfile is a hazard for this change.** Adding the dependency
changes `uv.lock`. As `CLAUDE.md` records, a full relock with either `uv` version
used here drops `greenlet` wheels that SQLAlchemy never requests, on two
architectures. The pull request must add only the new package's lines and be checked
with `uv sync --locked`.

**Positive.** The client is synchronous, so it matches the ports and the rest of the
service. The Redis protocol is what the relay's tests and the integration tests
target, and a change of hosting that keeps the protocol changes nothing in the
relay.
