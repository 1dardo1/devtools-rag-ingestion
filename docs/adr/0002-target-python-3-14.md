# 2. Target Python 3.14

- **Status:** Accepted
- **Last revised:** 2026-08-28

## Context

The interpreter version is the most upstream decision in this repository. It
fixes `requires-python` in `pyproject.toml`, `target-version` for `ruff`,
`python_version` for `mypy`, the base image in the `Dockerfile` (Phase 5), and
the matrix in GitHub Actions (Phase 7). It also bounds which language features
the domain layer may use.

Until now the repository carried "Python 3.12+" in `docs/ARCHITECTURE.md` and
"Python 3.12" in `README.md`. Neither was the result of an examined choice; the
value was inherited from the initial documentation pass. This record replaces
that default with a decision.

The choice is being made while the repository contains no source code at all —
the cheapest possible moment. Reversing it today costs four configuration lines.
Reversing it after Phase 4 costs a dependency audit.

Two facts about the calendar matter. Python 3.13 leaves its bugfix window around
October 2026, a few weeks from this date, and enters security-only maintenance.
Python 3.14 was released in October 2025 and remains in bugfix maintenance until
roughly October 2027. This service is a portfolio artifact intended to be
deployed, maintained and discussed through 2027.

Ecosystem support was verified against PyPI on 2026-08-28 rather
than assumed:

| Package | Latest version | Compiled wheels published |
|---|---|---|
| `pydantic-core` | 2.48.0 | cp312, cp313, **cp314**, cp315 |
| `psycopg-binary` | 3.3.4 | cp312, cp313, **cp314** |
| `testcontainers` | 4.15.0 | pure Python, no ABI constraint |

FastAPI and Pydantic resolve to identical dependency sets under 3.12, 3.13 and
3.14. No component of the planned stack blocks 3.14.

## Options considered

- **Python 3.12.** The most conservative option and the one already written in
  the documentation. It has been in security-only maintenance since April 2025.
  It offers nothing that 3.13 does not, while being nearly three years old.
  Rejected: choosing the oldest version that still works is a defensible
  engineering instinct only when something forces it, and nothing here does.

- **Python 3.13.** Roughly twenty-two months of production exposure and
  universal library support. The safest option by a small margin, and the
  version already present on most base images. Rejected because its bugfix
  window closes within weeks of this decision: the service would ship on a
  security-only interpreter and sit one release behind for its entire visible
  lifetime, with no technical reason to point at.

- **Python 3.14.** The longest remaining support runway of the three, verified
  wheel coverage across the whole planned stack, and deferred evaluation of
  annotations by default (PEP 649 / PEP 749), which removes the need for
  `from __future__ import annotations` in a codebase that will be dense with
  annotations and Pydantic models.

## Decision

Target Python 3.14. `pyproject.toml` declares `requires-python = ">=3.14"`, and
`ruff` and `mypy` are configured for the same version.

The constraint is expressed as a floor rather than an exact pin because this is
a deployed service, not a library. Nobody installs this package into a
pre-existing environment they control; the runtime version that actually matters
is the one pinned in the `Dockerfile`, decided separately in Phase 5. The
`requires-python` floor exists to stop resolution from silently succeeding on an
interpreter the code was never checked against.

## Consequences

**Positive.** One interpreter version spans development, CI and production, so
there is a single runtime to reason about when something misbehaves. Modern
syntax is available unconditionally, with no compatibility branches. The support
runway outlasts the period during which this service is expected to be
maintained and presented.

**Negative.** PEP 649 changes *when* annotations are evaluated, and both Pydantic
and FastAPI perform aggressive annotation introspection. That code path has less
production mileage on 3.14 than on 3.13, so an obscure type-resolution failure,
if one appears, will most likely appear here and will be harder to search for.

Peripheral tooling not yet chosen — coverage plugins, future linters — may lag
behind the interpreter and constrain later decisions.

Some sandboxed environments still ship a `uv` whose interpreter catalogue
predates the 3.14 release and offers only `3.14.0rc2`; those environments need
`uv` updated, or an explicitly provisioned interpreter, before they can build
this project.

Should any of these turn into a real obstacle, the fallback is Python 3.13 and
costs four lines of configuration, provided it is taken before infrastructure
work begins in Phase 4.
