---
name: redis-streams-client
description: Use in devtools-rag-ingestion when writing, reviewing or testing the Redis adapter behind the EventBroker port, or anything else that talks to Redis. Covers the synchronous redis-py client, one client per relay run, explicit timeouts with no client-side retries, TLS through the URL, XADD with the approximate MAXLEN bound, translating client errors to EventBrokerError, and testing against a real Redis.
---

# Talking to Redis from the relay

The relay publishes outbox rows to a Redis stream (ADR 0027 to 0030). The Redis
client lives in **one adapter in `infrastructure/`**, behind the `EventBroker`
port. Nothing in `domain/` or `application/` imports `redis`.

## Before writing the adapter

- **`redis-py` is approved (ADR 0030) but not yet a dependency.** Add it in the
  adapter's own pull request, adding only its lines to `uv.lock` and checking
  with `uv sync --locked` (the relock trap in `CLAUDE.md`).
- **Integration tests need a Redis container.** `pyproject.toml` installs only
  `testcontainers[postgres]` and says the `redis` extra arrives with 4.3. Adding
  that extra is a dependency change: name it in the proposal.
- **The Upstash test in ADR 0027 is still the condition** for using Upstash at
  all. Until it has passed, the adapter is proved against a local Redis only.

## The client

- **Synchronous only.** `redis.Redis`, never `redis.asyncio`. Ports, use cases and
  adapters are synchronous (ADR 0007).
- **One client per relay run**, built once from the configured URL with
  `redis.Redis.from_url(...)` and reused for every row of every batch in that run.
  Never one connection per `XADD`. The relay runs one batch at a time, so the
  client's own connection pool needs no tuning.
- **Explicit timeouts.** Set `socket_connect_timeout` and `socket_timeout`. The
  upstream guidance suggests a connect timeout shorter than the read timeout
  (2 s and 5 s, for example). The values are the adapter's decision, and its
  pull request records them.
- **No client-side retries.** Do not set `retry_on_timeout` or a `Retry` policy.
  ADR 0028 owns retries (1, 2 and 4 seconds, then the run fails). A second retry
  layer multiplies the time the batch's row locks are held, and hides the
  failure ADR 0027's alarm relies on.

## The URL, which carries a credential

- **TLS for any hosted Redis:** the URL scheme is `rediss://`. Plain `redis://`
  is for a local or compose Redis only.
- **The URL comes from the environment**, like `DATABASE_URL`. Adding the
  setting is a configuration change and needs approval (`COLLABORATION.md`
  section 4; the relay proposal, section 8, names it).
- **Never log it, never print it, never put it in an error message, a test or a
  document.** `tests/unit/test_no_secret_is_committed.py` refuses any connection
  URL carrying a user and a password, with no placeholder allowance. Examples in
  this repository use a host-only URL such as `redis://localhost:6379/0`.

## Publishing

- **One `XADD` per row**, with the bound from ADR 0029:
  `client.xadd(stream_name, fields, maxlen=100_000, approximate=True)`.
- **The bound is approximate, so trimming is by whole internal blocks.** A small
  stream is not trimmed at all, and a large one can briefly exceed the bound.
  This was observed against a local Redis on 2026-11-26; see
  `docs/runbooks/upstash-stream-test.md`. Size estimates must allow for it.
- **No pipelining in the first version.** One command per row keeps each failure
  attributable to its `outbox_id` (`RelayFailedError`) and each retry to one row.
  Pipelining does not reduce the number of commands a hosted plan counts.
- **The payload is the contracts package's JSON, unchanged.** The field names on
  the stream entry are the adapter's decision, made in its pull request. They are
  what retrieval will read, so they belong in `devtools-rag-contracts` once
  agreed.
- **Never `KEYS`, `FLUSHALL` or `FLUSHDB`.** To inspect a stream use `XLEN`,
  `XINFO STREAM` and `XRANGE` with a `COUNT`.

## Errors

Catch `redis.exceptions.RedisError` (it covers connection and timeout errors) in
the adapter and raise `EventBrokerError` from it: it is the only error
`RelayOutbox` retries. Anything else propagates and fails the run, which the
caller rolls back.

## Tests

- **Unit tests** use the in-memory fake broker. Nothing mocks the Redis client
  (`docs/COLLABORATION.md` section 7).
- **Integration tests** start a real Redis through `testcontainers`, marked
  `@pytest.mark.integration`, and cover: an entry appears with the payload
  unchanged, the bound is passed, and a dead server raises `EventBrokerError`.
- **Without Docker**, the container has a `redis-server`. Run it on a spare port
  with a data directory in the scratchpad (`--save "" --appendonly no`), and stop
  it with `SHUTDOWN NOSAVE`. Say in the pull request that the tests ran this way
  and not through `testcontainers`.

## Source

Written for this repository from `redis-connections` and `redis-security` in
[redis/agent-skills](https://github.com/redis/agent-skills) at commit `74708da`,
under the MIT licence in `LICENSE` beside this file
(Copyright (c) 2026 Redis, Inc.). Kept from the original: reuse the client, set
explicit timeouts, use TLS, avoid whole-keyspace commands. Changed: no
`retry_on_timeout` (ADR 0028 owns retries), and no credentials in examples
(this repository's secret guard). Not carried over: client-side caching, ACL and
`redis.conf` hardening, and Java and Lettuce material. Whether the hosted plan
supports ACL users is unverified.
