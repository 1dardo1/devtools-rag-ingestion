# 8. Run every local check again on a clean machine, on every proposed change

- **Status:** Accepted
- **Last revised:** 2026-09-05

## Context

Seventeen pull requests were merged into `main` before this record existed, and
not one of them was checked by anything but the author. The checklist in
`.github/pull_request_template.md` asks for four boxes — `ruff check` clean,
`mypy --strict` clean, tests green, no domain file importing infrastructure —
and every one of them was ticked by the same person who wrote the code, on the
machine that wrote it. A ticked box is a claim, not a check.

That is a gap between what this repository says about itself and what it
actually enforces. ADR 0005 and ADR 0006 both rest on the same argument: a rule
enabled today costs nothing, and the same rule enabled after Phase 4 costs a
migration. Both records make that argument about the *configuration* of the
tools. Neither of them makes anything *run* the tools. Enabling `mypy --strict`
and twenty-three `ruff` families, and then relying on the author to remember to
invoke them, is a policy without a mechanism.

The failure this closes is narrow and specific. The checks pass on the author's
machine by the time a pull request exists — that is why the pull request exists.
What has never been established is that they pass anywhere else: on a checkout
with no `.mypy_cache` holding results for a file that has since changed, with no
editable install left over from an experiment, with no tool that happens to be
on `PATH` for unrelated reasons, and with the dependency versions the lockfile
actually names rather than the ones that happen to be installed. This project
has already been bitten by two of those: a stale `.mypy_cache` reported errors
for a file that had been reverted, and a `hatchling` misconfiguration made the
package unbuildable while every local command kept working against an install
made before the breakage.

## Options considered

- **Keep the template checklist and no automation.** Zero configuration, zero
  minutes of compute. Rejected: it is the status quo, and the status quo is
  exactly what produced seventeen self-certified merges. It also cannot satisfy
  `ROADMAP.md` 7.1, whose completion criterion is a green badge — a badge is a
  statement by a third party, and there is no third party.

- **A pre-commit framework** (`pre-commit`, hooks installed locally). Catches
  problems earlier, before a commit exists rather than after a push. Rejected as
  the *primary* mechanism for one reason: hooks run on the developer's machine,
  which is the machine whose state is in question, and they can be skipped with
  `--no-verify`. It solves the convenience problem, not the trust problem. It is
  a reasonable addition later, on top of this, never instead of it.

- **Four parallel jobs, one per check.** Each check gets its own status line and
  they finish in the time of the slowest. Rejected: each job pays the checkout,
  the uv install and the dependency sync again, which for a suite that runs in
  0.16 seconds is several minutes of setup to parallelise a few seconds of work.
  The named-step approach below produces the same per-check granularity in the
  log at a quarter of the cost.

- **One job, one script** (`make ci` or a shell script running all four).
  Simplest to keep in step with what a contributor runs locally. Rejected
  because a single failing command reports only its own failure, and the run
  stops there: a lint error would hide whether the types and the tests were also
  broken, turning one round of feedback into three.

- **One job, four named steps, each running past the previous one's failure.**
  Chosen.

## Decision

`.github/workflows/ci.yml` runs on every pull request and on every push to
`main`: `uv sync --locked --all-groups`, then `ruff check`, `ruff format
--check`, `mypy` and `pytest` as four separately named steps.

**Every check after the first carries `if: ${{ !cancelled() }}`**, so one run
reports everything that is wrong rather than the first thing. Without it a
misplaced import would mask a type error and a broken test, and the author would
learn about them one push at a time.

**`uv sync --locked` is itself a check**, and the one a reviewer is least able
to perform by reading the diff. It fails rather than re-resolving when
`uv.lock` and `pyproject.toml` have drifted apart, which is the state in which
CI and the developer are silently running different dependency sets.

**Actions are pinned to a commit SHA, not a tag**, with the version in a
trailing comment:

```yaml
uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d  # v10.0.1
```

A tag is a movable pointer. `@v7` means "whatever the owner of that repository
last pointed it at", which is a third party with write access to a job holding
this repository's checkout. Phase 13 is security hardening, and ADR 0006 already
refused to defer the `S` family to it on the grounds that starting with the
protection off and retrofitting it is the pattern the roadmap argues against.
The same reasoning applies here.

The pin is not theoretical tidiness. `astral-sh/setup-uv` publishes floating
major tags only up to `v7` while its releases have reached `v10.0.1`, so
`@v10` — the tag a reader would reasonably expect to work — resolves to nothing.
This was found by listing the repository's refs rather than by a red pipeline.

**`uv` itself is pinned to `0.12.10`** for the same reason the dependencies are
locked: a release of the build tool should not be able to change what this
workflow does without a commit saying so.

**`permissions: contents: read`** at the workflow level. Nothing here needs to
write, and a job that cannot write cannot be persuaded to write.

**Concurrency cancels superseded pull-request runs only.** A second push makes
the first run's answer irrelevant. Runs on `main` are never cancelled: each one
is the record for a commit.

## Consequences

**Positive.** The four claims in the pull-request template become verifiable by
someone other than their author, which is the whole of the value. `uv sync
--locked` closes the class of bug where the lockfile and the manifest disagree —
invisible in a diff, and the source of the `hatchling` breakage this repository
already hit. Every check runs against a machine with no history, which is what
makes a stale-cache result impossible to mistake for a real one. `ROADMAP.md`
7.1's completion criterion becomes reachable, and the hard gate in `CLAUDE.md`
— a public URL and green CI — loses one of its two blockers.

**Negative.** Feedback is slower than running the checks locally, though by
much less than expected: the first run of this workflow took **16 seconds** end
to end, 12 of them inside the job. That is cheap enough that it is not a reason
to skip anything, and the estimate this record originally carried — minutes,
dominated by the checkout and the Python download — was simply wrong and has
been corrected against the measurement. It will grow when Phase 6 brings
integration tests that start real containers; the number above is a floor for a
pure-domain suite, not a promise.

Pinned SHAs do not update themselves, so the
actions will silently rot until someone bumps them deliberately — the honest
cost of refusing a movable pointer, and worth revisiting if it turns into
neglect rather than discipline. A single job means a failure in the sync step
stops everything after it, which is correct but does make the sync a single
point of failure for the whole signal.

The workflow's own correctness is not covered by anything. A typo in
`ci.yml` cannot fail `ci.yml`; it produces a run that does not exist, and an
absent check reads as an unblocked merge unless branch protection is configured
to require it. **Branch protection is not part of this record** and `main`
currently accepts a merge whose checks never ran. That is a repository setting
rather than a file, so it cannot be made here.

Coverage reporting (`ROADMAP.md` 6.2) is deliberately not in this workflow.
There is nothing yet whose coverage is interesting, and a threshold chosen
against fourteen pure domain modules would have to be renegotiated the moment
the first adapter arrives. It extends this pipeline later rather than shaping it
now.
