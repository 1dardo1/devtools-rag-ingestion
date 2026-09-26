# 24. Coverage is measured in CI, and it has a floor

- **Status:** Accepted
- **Last revised:** 2026-09-26

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

- **A floor, `fail_under = 93`, in `pyproject.toml`.** Chosen, because "cannot
  quietly drift" is a rule and a rule nobody enforces is a wish.
- **Report only.** Rejected: it is the drift the build plan names.
- **100%.** Rejected. The last few percent are reached by tests that pin how the
  code is written rather than what it does, which `COLLABORATION.md` §7 prohibits.
- **80%, the customary figure.** Rejected: thirteen points below the measured
  number, so it would let a large drop pass without a word.

**The floor comes from the unit suite, while CI measures the whole suite.** That
is deliberate. The unit number is the one that could be measured here, and the
whole suite is a superset of it, so the first CI run cannot fail on a floor set
above what it will reach. It also means the floor starts with slack — see the
consequences.

### Lines or branches

**Branches too (`branch = true`).** Line coverage calls an `if` covered when only
one of its outcomes ever ran. Branch coverage is stricter, and the 93.31% above is
already the stricter number.

### Where it runs

**Inside the existing `checks` job, as the test step itself.** ADR 0008's rule:
a job that would repeat the `uv` setup belongs in `checks`. Running the suite once
under `coverage` rather than twice also means the number describes exactly the run
whose result is shown.

## Decision

`coverage` joins the `dev` group. `[tool.coverage.run]` measures `rag_ingestion`
with branch coverage; `[tool.coverage.report]` sets `fail_under = 93`. In CI the
test step becomes `coverage run -m pytest`, followed by a step that writes the
report as Markdown to the run summary without enforcing, then prints it to the log
and enforces. That order puts the table on the page even on the run where the
floor fails.

Locally, `uv run pytest` is unchanged. `uv run coverage run -m pytest` followed by
`uv run coverage report` reproduces CI; on a machine without Docker, add
`-m "not integration"` and expect the adapters to show as uncovered.

## Consequences

- **The floor is slack on day one.** The integration tests will lift the CI number
  above 93, so the first few points of any later drop go unnoticed until the floor
  is raised to the number CI actually reports. Raising it is a separate, small
  change, and it has to be made by hand — nothing ratchets it automatically.
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
