# 24. Coverage is measured in CI, and it has a floor

- **Status:** Accepted
- **Last revised:** 2026-09-27

## Context

`ROADMAP.md` 6.2: "Coverage measurement — done when: reported in CI."
`docs/BUILD-PLAN.md` states the purpose more sharply: report it automatically
"so the number cannot quietly drift". A number that is printed and never checked
satisfies the first sentence and not the second.

Before anything was configured, the unit suite was measured as it stands: 245
tests, **93.31%** of statements and branches in `rag_ingestion`. What it misses is
almost entirely the PostgreSQL adapters and parts of `main.py` — the code the 51
integration tests exist to exercise, and which they cannot exercise without a
Docker daemon.

CI then measured the whole suite, all 296 tests: 98.63%, with 6 statements and 4
branch arcs unexecuted out of 668 and 64. Each of the ten was read rather than
chased. Nine were behaviour nobody had tested, and six new tests cover them —
among them the guard that the web layer ships unwired, which had been checking
one endpoint of three. That brings the whole suite to **99.86%**, and that is the
number the floor is set from.

The tenth is the `isinstance` in `error_handling._handle_domain_error`: the
handler is registered for `DomainError` alone, so its false branch cannot be
reached, and it exists to narrow the type for `mypy`. It stays uncovered and
visible in the report. Reaching it would take a test calling the private handler
with an exception it can never receive, which pins how the code is written rather
than what it does; `# pragma: no branch` would hide the gap instead of explaining
it.

## Options considered

### The tool

- **`coverage.py`, invoked as `coverage run -m pytest`.** Chosen. It is the
  package that does the measuring whichever way it is invoked.
- **`pytest-cov`.** Rejected. It is a pytest plugin wrapped around `coverage.py`,
  so it is a second dependency to get the same numbers. Its conveniences — flags
  on the `pytest` command line, handling of `xdist` workers — solve problems this
  repository does not have.

### Where the report is shown

- **The run's own summary page, via `$GITHUB_STEP_SUMMARY`, and the job log.**
  Chosen. Nothing leaves GitHub, nothing needs an account.
- **Codecov or Coveralls.** Rejected for now. Either needs an account and an
  upload token — the first secret this repository would hold — and ADR 0022 ties
  that moment to 7.2. They add history graphs and pull-request comments, which
  are pleasant, not what 6.2 asks for.
- **A badge in the README.** Rejected: it needs one of the services above, and it
  shows the number on `main` to a reader who cannot act on it.

### Whether the number is enforced

- **A floor, `fail_under = 99`, in `pyproject.toml`.** Chosen, because "cannot
  quietly drift" is a rule and a rule nobody enforces is a wish.
- **Report only.** Rejected: it is the drift the build plan names.
- **100%.** Rejected. The one branch left is unreachable by design (see the
  context), and in general the last few percent are reached by tests that pin how
  the code is written rather than what it does, which `COLLABORATION.md` §7
  prohibits.
- **80%, the customary figure.** Rejected: nearly twenty points below the
  measured number, so it would let a large drop pass without a word.
- **98.** Rejected once the gaps were closed: it would let the tests that closed
  them be lost again without the floor noticing. `fail_under` compares the
  unrounded value, so the floor is always set to a whole number *below* the
  measurement, never to what the report displays.
- **93, the unit suite's number.** Rejected. It is the number a machine without
  Docker can reach, which makes local runs pass, but it leaves almost seven points
  of drop in the whole suite that nothing would notice.

### Lines or branches

**Branches too (`branch = true`).** Line coverage calls an `if` covered when only
one of its outcomes ever ran. Branch coverage is stricter, and both numbers above
are already the stricter kind.

### Where it runs

**Inside the existing `checks` job, as the test step itself.** ADR 0008's rule:
a job that would repeat the `uv` setup belongs in `checks`. Running the suite once
under `coverage` rather than twice also means the number describes exactly the run
whose result is shown.

## Decision

`coverage` joins the `dev` group. `[tool.coverage.run]` measures `rag_ingestion`
with branch coverage; `[tool.coverage.report]` sets `fail_under = 99`. In CI the
test step becomes `coverage run -m pytest`, followed by a step that writes the
report as Markdown to the run summary without enforcing, then prints it to the log
and enforces. That order puts the table on the page even on the run where the
floor fails.

Locally, `uv run pytest` is unchanged. `uv run coverage run -m pytest` followed by
`uv run coverage report` reproduces CI; on a machine without Docker, add
`-m "not integration"` to the first and `--fail-under=0` to the second, and
expect the adapters to show as uncovered.

## Consequences

- **The floor needs Docker to be met.** The unit suite alone reaches about 93%, so
  a local `coverage report` without a daemon fails even when nothing is wrong. The
  alternative — a lower floor that both runs could meet — gives up the only run
  that measures everything. Only CI's number is binding.
- **Raising the floor is manual.** Nothing ratchets it automatically. When the
  number climbs, the floor stays where it is until a pull request moves it.
- **The margin is small.** At 99.86% against 99, about six uncovered statements or
  branches in today's code turn CI red. New code moves the denominator, so the
  margin changes with every change; a pull request that adds untested code will
  usually be the one that finds out.
- **Code that is genuinely hard to test now costs something.** The relay (4.3) is
  the obvious candidate. It will need its tests in the same pull request, or a
  pull request that lowers the floor and says why. That friction is the point, but
  it is friction.
- **Coverage says what ran, not what was checked.** A test that executes a line
  and asserts nothing counts the same as one that pins its behaviour. The floor
  catches code nobody ran; it cannot catch a test that proves nothing.
- **Anything run in a subprocess is invisible.** `coverage` measures this process
  only. Nothing in the suite runs `rag_ingestion` in a child process today; if
  something starts to, it will read as uncovered rather than failing loudly.
