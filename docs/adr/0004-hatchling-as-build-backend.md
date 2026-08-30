# 4. Use hatchling as the build backend

- **Status:** Accepted
- **Last revised:** 2026-08-30

## Context

PEP 517 splits Python packaging into a *frontend*, which resolves and installs
(`uv`, already fixed in `docs/ARCHITECTURE.md` section 3), and a *build
backend*, which turns the source tree into an installable artifact. The backend
is declared in the `[build-system]` table of `pyproject.toml`, and until it is
chosen that file cannot be written at all. Without it there is no `uv sync`, no
installed package, and therefore no test run — which makes this the last
decision blocking the Phase 0.1 scaffold.

Three facts about this project narrow the choice considerably:

- **It is pure Python.** No C extensions, no compilation step, no code
  generation. Most of the reasons to want a capable backend do not apply.
- **It is a deployed service, not a published library.** Nothing is uploaded to
  PyPI; the artifact that reaches production is a container image. The wheel
  exists so that the package can be installed into a virtual environment and
  into that image.
- **The layout is a canonical src layout** (ADR 0003), but the distribution name
  and the import root deliberately differ, which defeats the automatic package
  detection every candidate backend offers. See the decision below.

Current versions on PyPI on 2026-08-28: `hatchling` 1.32.0,
`setuptools` 84.0.0, `uv-build` 0.12.7. All three support Python 3.14
(ADR 0002).

## Options considered

- **setuptools.** The historical backend, with by far the deepest accumulated
  documentation; any problem worth having has been solved publicly since 2015.
  Rejected because that depth is also the cost: `setup.py`, `setup.cfg` and
  `pyproject.toml` configurations coexist across the search results, so
  answering a question means first working out which era the answer belongs to.
  It also needs package discovery declared explicitly under a src layout. For a
  new project with no unusual requirements, that is inherited complexity bought
  in exchange for capabilities this project will not use.

- **uv_build.** The backend shipped with `uv` itself, written in Rust,
  substantially the fastest of the three and requiring no additional build
  dependency, since `uv` is present already. Rejected on maturity and coupling:
  it is the youngest of the three and deliberately minimal, so a requirement
  appearing in Phase 5 or 6 that it does not cover — data files to include, a
  build hook — would force the change under time pressure rather than now. It
  also ties packaging to one frontend, whereas the alternatives keep
  `pip install .` working for anyone who does not use `uv`.

- **hatchling.** The backend behind Hatch, and what `uv init --package`
  generates by default.

## Decision

Use `hatchling`. `pyproject.toml` declares:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

One piece of `[tool.hatch.*]` configuration is required, and only one:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/rag_ingestion"]
```

`hatchling` auto-detects a package at `src/<normalised project name>`, which
here would be `src/devtools_rag_ingestion`. That directory does not exist,
because ADR 0003 deliberately gave the distribution and the import root
different names. Without these two lines the build fails outright —
`Call to hatchling.build.build_editable failed` — so this is not a
configuration preference but a consequence of ADR 0003 that has to be paid
somewhere. The alternative is renaming one of the two names to match the other,
which ADR 0003 considered and rejected on its own merits.

Beyond those two lines no `[tool.hatch.*]` configuration is added, and more is
introduced only if something concrete requires it.

The speed advantage of `uv_build` is real and irrelevant at this scale: a
container build is dominated by dependency download, not by the backend. The
maturity advantage of `setuptools` is real and equally irrelevant, because it
applies to capabilities a pure-Python service never exercises.

## Consequences

**Positive.** The packaging setup is two lines, and both state something a
reader can verify against the directory tree. Anyone can build the project with
standard tooling (`pip install .`, `python -m build`) without knowing that `uv`
is involved, which keeps CI and container builds free of a hard dependency on
one frontend. The choice matches what most current Python tutorials and
generators produce, so searching for help returns answers that apply.

**Negative.** `hatchling` is one more build-time dependency to download inside
`docker build`, where `uv_build` would have come free — small, but not zero, and
it appears on every cold image build.

The `[tool.hatch.*]` table now exists, which removes the natural barrier against
adding to it: its configuration surface is an ecosystem of its own, and the next
entry will be easier to justify than this one was. Nothing prevents that drift
automatically. Any proposal to add a third line should be treated as a decision,
not a detail.

Reversing this decision costs roughly seven lines in `pyproject.toml` — the
`[build-system]` table and the package path — and touches no import. The
equivalent path exists for every candidate backend, so the switch stays cheap;
it is `[tool.hatch.*]` growing beyond the package path that would make it
expensive. That cheapness is a property of PEP 517's frontend/backend split.
