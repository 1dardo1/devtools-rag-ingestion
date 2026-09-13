# 20. The image is built and started in CI

- **Status:** Accepted
- **Last revised:** 2026-09-13

## Context

ADR 0019 ended on an admission: the `Dockerfile` it describes had never been
built. This repository's environment has a Docker client with no daemon — the
same absence ADR 0011 works around for the integration tests — so the layer
ordering, the `COPY --from` of the `uv` binary, and whether `uv sync --locked`
succeeds inside the image were reasoned rather than demonstrated.

`ROADMAP.md` 5.1 is **"done when: image builds"**, so the unit was not closed. It
could not be closed from here at all; something with a Docker daemon had to do
it.

And the gate makes this urgent rather than tidy: a public URL with green CI, and
the URL comes from an image. An image nobody has built is not a deployment plan.

## Options considered

### Where the build happens

- **A second job in the existing CI workflow, on every pull request and every
  push to `main`.** Chosen.
- **A separate workflow filtered with `paths`,** running only when the
  `Dockerfile`, `pyproject.toml` or `uv.lock` change. Cheaper, and rejected on two
  counts. A required check that is *skipped* blocks merges in GitHub — the
  classic trap — and handling that needs a dummy job that reports success, which
  is machinery in place of a decision. More importantly the build would then be
  absent from most runs, which is exactly when a transitive change breaks it
  without anybody noticing: the failure mode a `paths` filter is most likely to
  hide is the one it is least able to predict.
- **Build it by hand, once, before the deployment in 7.2.** No change to CI at
  all. Rejected because the criterion stays unmet until then, and a broken
  `Dockerfile` is then discovered while deploying, which is the worst moment to
  learn it.

### A second job, when ADR 0008 chose one

ADR 0008 made the checks a single job rather than four, and this adds a second,
so the earlier decision deserves an answer rather than a quiet exception.

**ADR 0008's objection was to four jobs each paying the same setup cost to run one
fast command** — checkout, install `uv`, fetch Python, install the dependency set,
then run `ruff` for two seconds. That argument does not reach this job, because it
**shares none of that setup**: no `uv`, no Python, no dependency install. Put in
the same job it would only make the fast feedback wait for the slow thing, which
is the cost ADR 0008 was trying to avoid, arrived at from the other direction.

### How much the job proves

- **Build *and* start the container.** Chosen, and the reason is that building is
  the weaker half. An image can build perfectly and die on the first `docker run`
  because of the `PATH`, the `CMD`, or the non-root user being unable to read the
  virtual environment — and those are precisely the three things ADR 0019 could
  only reason about. A check that stops at `docker build` would leave the most
  likely defects undetected while reporting success.
- **`docker build` alone,** the literal wording of `ROADMAP.md` 5.1. Rejected on
  the above: it satisfies the sentence without testing the thing the sentence is
  about.
- **Build, start, and assert that every line of the container's stdout is valid
  JSON.** This would also close ADR 0019's logging claim in a real container
  rather than on a developer's machine. Rejected for now as more shell in the
  workflow than the gap justifies: the logging claim already has unit tests and a
  verified local run, and the step prints the container's logs unconditionally, so
  a human sees the format on every run. Worth revisiting if it ever regresses.

### What the job does not do

- **No registry, no push.** Nothing needs the image to exist anywhere yet;
  publishing is 7.2's problem, and it is the step that would need a token that can
  write. The workflow's `permissions: contents: read` stays as it is.
- **No `docker/build-push-action`, no buildx cache.** The runner already has
  Docker, so the build needs no action at all — one less third-party dependency to
  pin and audit. Layer caching is an optimization, and `ARCHITECTURE.md` principle
  10 says not before measurement; there was nothing to measure until this had run
  once.

## Decision

A second job, `image`, named "Image builds and starts": check out, `docker build`,
`docker run --detach` with `DATABASE_URL` pointing at nothing, poll
`/openapi.json` until it answers, print the container's logs, remove the
container.

`DATABASE_URL` points at nothing deliberately. ADR 0017 gives one connection per
request and opens none before a request arrives, so the server must come up and
serve its own OpenAPI document with no database anywhere. That is what makes this
a test of the *image* rather than of PostgreSQL, and it keeps the job free of a
service container it does not need.

The wait polls rather than sleeping a fixed time. A fixed wait is either flaky or
slower than necessary, and usually both.

The build, start and wait steps carry **no** `if:` condition, so each runs only if
the previous one succeeded. That is a departure from the `checks` job, where
`!cancelled()` makes every check report even after an earlier one failed, and the
difference is the point: those are independent checks, these are a sequence. The
two terminal steps do run under `always()` and tolerate there being no container,
so a failed build still shows whatever the container said and the cleanup is never
what turns the job red.

## Consequences

**5.1's criterion is now met by a machine, and exceeded.** "Image builds" is
checked, and so is "image starts and serves", which is the part that would
actually have been broken.

**A broken `Dockerfile` can no longer merge.** It could before: ADR 0019 went in
with the file unverified, which was the honest thing to do at the time and is not
a state to stay in.

**The new job is not a required check, and making it one is not something this
decision can do.** `main` is protected by a ruleset that names its required
checks, and that is configuration in the GitHub interface rather than in this
repository. Until somebody adds it, the job reports but does not block.

**Negative: every pull request now pays for a Docker build, including ones that
only touch documentation.** That is the cost of the `paths` filter being rejected
above. It is ~1–2 minutes in parallel with the checks, so it does not extend the
critical path unless the build is slower than the test suite.

**It earned its place on the first run, which was red.** The build failed with
`OSError: License file does not exist: LICENSE`: `pyproject.toml` has
`license = { file = "LICENSE" }` and hatchling validates that the file exists, and
the `Dockerfile` copied `README.md` but not `LICENSE`. ADR 0019 had reasoned its
way to the readme and missed the licence, which is the same reason stated twice in
one manifest. **That is an absence, and reading does not find absences — building
does.** ADR 0019 is corrected in place, with the rule rather than the filename:
every path `pyproject.toml` points at has to be in the image.

**And it found a defect in itself on the same run.** `Start the container` and
`Wait for it to answer` carried `if: ${{ !cancelled() }}`, copied from the `checks`
job without re-deriving why it is there. In `checks` it is right: those steps are
independent checks and one run should report every failure. In `image` they are a
*sequence*, so after the failed build the job ran `docker run` against an image
that did not exist ("Unable to find image"), then polled an address nothing was
listening on for thirty seconds, and buried the real error under two misleading
ones. The condition is gone from both steps; the terminal two keep `always()`,
which is correct, because showing the logs and removing the container should happen
however the job ended.

**Negative: nothing verifies the workflow before it runs.** Both defects above
were found by running it, because a workflow cannot be executed locally here. The
YAML parsing and `bash -n` over every `run` block are the most this environment
can check, and neither could have caught either of them: one was a missing file in
another file, the other was a semantically wrong but syntactically perfect
condition.

**Negative: ADR 0008's "one job" is now "one job and one more".** The distinction
drawn above — shared setup or not — is the rule that keeps it from becoming four
jobs by drift. A future job that *would* share the `uv` setup belongs in `checks`.
