# 19. The container image

- **Status:** Accepted
- **Last revised:** 2026-09-13 (corrected: see the LICENSE note below)

## Context

`ROADMAP.md` 5.1 asks for a multi-stage `Dockerfile`, "done when: image builds".
Phase 5 is the nearer half of the gate — a public URL with green CI — and it is
not blocked on anything, unlike 4.3.

Three things had to be decided and none of them follows from the others, so each
is recorded with what it rejected.

## Options considered

### The base image and the build strategy

- **`python:3.14-slim`, two stages, `uv` copied from its own image.** Chosen. The
  build stage installs into `/app/.venv`; the runtime stage copies that and the
  source. `uv` is a build tool and never reaches the runtime layer.
- **`ghcr.io/astral-sh/uv:python3.14-bookworm-slim`, a single stage.** The
  shortest Dockerfile, with `uv` already present. Rejected on two counts: it
  leaves a build tool in the production image, and it ties the base to Astral's
  tagging cadence rather than to the official Python image.
- **Alpine. Rejected on evidence, not on taste.** `psycopg[binary]` is a
  **manylinux** wheel with libpq bundled inside. Alpine is musl, where that wheel
  does not exist, so `uv` would fall back to building psycopg from source —
  needing a compiler and `libpq-dev`, producing a *larger* image more slowly, and
  discarding the binary wheel ADR 0010 chose deliberately.
- **Distroless in the final stage.** Smaller, with less attack surface. Rejected
  because it is the chosen two-stage build *plus* constraints: no shell, so
  diagnosing a misbehaving deployment gets materially harder, which is a poor
  trade for a service that has never yet run in production.

`uv` is pinned to **the version `.github/workflows/ci.yml` pins**, not `latest`.
A different resolver in the image than in CI is two answers to the question "what
does `uv.lock` mean".

### When migrations run

- **Never at container start.** Chosen. `CMD` starts the server and nothing else.
  `alembic upgrade head` is available in the image — ADR 0010 made `alembic` a
  runtime dependency for exactly this — and is run as its own deliberate step.
- **In an entrypoint, before the server.** One command deploys, and the database
  is never behind the image. Rejected: every replica starting at once races to
  apply the same revision, and a migration that fails during startup becomes a
  crashloop rather than a deployment that visibly failed. It also couples the
  service's startup to the schema, which is the coupling ADR 0017 avoided by
  keeping the API and relay lifecycles separate — and the relay, when 4.3 lands,
  has no business migrating anything.
- **At start, under a PostgreSQL advisory lock.** This genuinely solves the race.
  Rejected because it puts code we wrote in the startup path that cannot be
  tested without several real replicas, and it still couples startup to the
  schema. It is choosing the hard problem in order to keep the convenience.

### What to do about the server's own logs

ADR 0016 promised "one JSON object per line on stdout". Introducing `uvicorn`
broke that promise before a line of the Dockerfile existed, and it was found by
reading the server's output rather than by assuming it was fine:

```
"uvicorn":        {"handlers": ["default"], "level": "INFO", "propagate": False}
"uvicorn.error":  {"level": "INFO"}
"uvicorn.access": {"handlers": ["access"],  "level": "INFO", "propagate": False}
```

With `propagate: False` those records never reach the root handler, and uvicorn's
handler writes **plain text to stderr**. So a container's output would be two
formats on two streams. Worse: **nothing in this service logs anything yet**, so
in practice the only lines a deployment emitted would be the ones in the wrong
format.

- **`observability.configure` reclaims those loggers** — clears their handlers and
  restores propagation. Chosen. One mechanism, in the module ADR 0016 made
  responsible for the question.
- **A `--log-config` file in the image.** uvicorn's documented knob. Rejected
  because it is a second place configuring logging: a `dictConfig` file
  duplicating `observability.py`. Duplicated mechanisms for one concern is the
  failure mode ADR 0017 spent a decision avoiding with `DATABASE_URL` and ADR
  0018 avoided again with the body cap.
- **Leave it, with `--no-access-log` to cut the noisiest part.** Free. Rejected:
  the output still mixes formats and streams, which is what ADR 0016 chose one of
  each to prevent.

## Decision

A two-stage `Dockerfile` on `python:3.14-slim`. Dependencies install in their own
layer before the source is copied, so editing a docstring does not re-resolve the
dependency set. `uv sync --locked --no-dev`: `--locked` so an image can never be
built from a dependency set the lockfile does not describe, `--no-dev` so the
test toolchain stays out. A non-root `ingestion` user. `PYTHONUNBUFFERED=1`,
because buffered stdout in a container means logs that arrive late or not at all,
and ADR 0016 made stdout the log.

`CMD` runs `uvicorn rag_ingestion.main:build --factory --host 0.0.0.0`, with
**one worker**. More than one is an optimization and `ARCHITECTURE.md` principle
10 says not before measurement; the orchestrator scales replicas, which is the
same lever one level up without also putting a process manager in the image.

`uvicorn` is added as a dependency, and **not `uvicorn[standard]`**. Those extras
are `uvloop` (which barely touches a service whose endpoints run in a threadpool
by ADR 0007), `httptools`, `watchfiles` (development reload), `websockets`
(unused), and `python-dotenv` — a second configuration mechanism beside
`pydantic-settings`. Six packages for an optimization nobody has measured.

`configure` also reclaims `uvicorn`, `uvicorn.error` and `uvicorn.access`, and
the formatter drops `color_message`: uvicorn passes it in `extra`, holding the
same message again with ANSI escape sequences inside, and nested under `context`
it is neither context nor readable. It is the one library-specific exclusion in
that module.

## Consequences

**Verified by running the server, not by reading the code.** Every line uvicorn
emits — startup, access, shutdown — now arrives on stdout as JSON through
`JsonFormatter`, stderr is empty, and no `color_message` survives. That is the
whole point of the logging decision and it is the kind of claim that is worthless
unasserted.

**Negative, and it is the important one: the image has not been built.**
`ROADMAP.md` 5.1 says "done when: image builds", and this repository's
environment has a Docker client with no daemon — the same absence ADR 0011 works
around for the integration tests. So the `Dockerfile` here is **unbuilt and
therefore unverified**: the layer ordering, the `COPY --from` of the `uv` binary,
and whether `uv sync --locked` succeeds inside the image are all reasoned rather
than demonstrated. **5.1 is not done until something builds it.** Building it in
CI is the obvious answer and is a change to CI, which is a decision of its own.

> **Built, and this reasoning was wrong in one place.** ADR 0020 put the build in
> CI, and its first run failed:
>
> ```
> OSError: License file does not exist: LICENSE
>     at RUN uv sync --locked --no-dev
> ```
>
> `pyproject.toml` has `license = { file = "LICENSE" }`, and **hatchling validates
> that the file exists** when it builds the project. The reasoning above worked
> out that the build backend reads `README.md`, because `readme` names it — and
> then missed that `license` names a file for exactly the same reason. One
> `COPY` line short.
>
> The correction is a rule rather than one more filename: **every path
> `pyproject.toml` points at has to be in the image**, because the build backend
> reads the manifest, not the `Dockerfile`. Today that is `README.md` and
> `LICENSE`; a `license-files` glob or a dynamic version read from a file would
> add more.
>
> It is worth being exact about what this says of the reasoning. Everything else
> it predicted held: the layer ordering, the `COPY --from` of the `uv` binary, the
> manylinux wheel installing on glibc, `--locked` succeeding. What it could not do
> was notice an *absence*, which is the class of error reading cannot catch and
> building does. That is the argument for ADR 0020 stated better than ADR 0020
> managed to state it in advance.

**Negative: reclaiming another library's loggers reaches into its configuration.**
It works because uvicorn configures logging *before* it calls the application
factory, which is its behaviour today and not a promise it makes.
`test_the_assumption_this_rests_on_still_holds` asserts the shape that depends
on, so a release that renames a logger or stops silencing it fails the suite
instead of quietly making `_SERVER_LOGGERS` a list of names that do nothing.

**Negative: `_NOISE` is a library-specific exclusion in a module that had none.**
One entry today. If it grows, the formatter is accumulating knowledge of its
callers and the design should be revisited rather than the set extended.

**Negative: migrations are now a step a human has to remember.** A deploy can
start a new image against a database that has not been migrated, and the failure
shows up on the first request rather than at deploy time. That is the accepted
cost of not racing replicas; 5.2 and the deployment in 7.2 are where the step
gets a home.

**The image's Python and the locked one are the same interpreter.**
`UV_PYTHON_DOWNLOADS=never` is what enforces it; without it `uv` would fetch its
own and the image would contain two.

**`.dockerignore` is a correctness concern before a speed one.** A local `.venv`
copied into the context would be an environment built against a different
machine's interpreter, silently shadowing the one the build stage produced, and a
`.env` would bake a developer's database password into a layer. A deny list
rather than `*` with exceptions: the Dockerfile already copies only the four
paths it needs, so the list's job is to say what is *dangerous*, which is the
part a reader needs.
