# 3. Use a src layout with `rag_ingestion` as the import root

- **Status:** Accepted
- **Date:** 2026-08-28

## Context

The layout determines the first line of every file in the repository. It fixes
the packaging configuration, how `mypy` resolves modules, how `pytest` finds the
code under test, what the `Dockerfile` copies, and every `import` statement
written from here on. Changing it once the domain exists means touching every
file at once, which makes this the most expensive Phase 0 decision to reverse.

The existing documentation did not agree with itself. `CLAUDE.md` and
`docs/ROADMAP.md` call for a "`src/` layout", which conventionally means a
single importable package nested inside `src/`. Section 6 of
`docs/ARCHITECTURE.md` instead drew four top-level packages directly inside
`src/`. Those are different designs with different failure modes, and the
contradiction had to be resolved before any file was created.

Two names are involved, and they are independent:

- The **distribution name** (`[project].name`) identifies the installable
  artifact. It may contain hyphens and only has to be unique within the virtual
  environment.
- The **import name** is the directory under `src/`. It must be a valid Python
  identifier — no hyphens — and it occupies a slot in a global, shared
  namespace.

They need not match, and across the ecosystem they frequently do not:
`python-dateutil` imports as `dateutil`, `beautifulsoup4` as `bs4`.

Name availability was checked against PyPI on the date of this record, because
the risk under discussion is collision with an installed distribution rather
than a hypothetical one:

| Name | Status on PyPI |
|---|---|
| `domain` | taken (0.1.4) |
| `application` | taken (1.0) |
| `infrastructure` | taken (3.5.6) |
| `config` | taken (0.5.1) |
| `ingestion` | taken (0.0.42) |
| `api` | free |
| `rag-ingestion` | free |
| `devtools-rag-ingestion` | free |

## Options considered

- **Four top-level packages inside `src/`**, as section 6 drew them. Imports
  read as `from domain.document import Document`, which matches the hexagonal
  vocabulary exactly and carries no prefix noise. Rejected because it claims
  `domain`, `application`, `infrastructure` and `config` in the global import
  namespace, and all four already exist as published distributions. A single
  transitive dependency pulling any of them in produces an import shadowing bug
  that fails silently and is unpleasant to diagnose. It also requires every
  package to be declared by hand in the build configuration.

- **A flat layout with the package at the repository root**, no `src/`
  directory. Simplest tree. Rejected because it reintroduces precisely the
  problem the src layout exists to prevent: running `pytest` from the
  repository root puts the working directory on `sys.path`, so tests import the
  local source tree rather than the installed distribution. A file accidentally
  excluded from the built artifact still passes the suite and fails in
  production. It also contradicts the roadmap, which asks for `src/` explicitly.

- **`src/devtools_rag_ingestion/`**, mirroring the repository name exactly.
  Maximum literalness and no mismatch between the two names. Rejected on
  ergonomics: the `devtools_` prefix carries no information inside the codebase,
  where the containing system is never in doubt, and it would appear on every
  import line for the life of the project.

## Decision

Use a src layout with a single importable package:

```
src/rag_ingestion/{domain,application,infrastructure,api}/
```

The distribution is named `devtools-rag-ingestion`, matching the repository, so
that the artifact is identifiable from outside. The import root is
`rag_ingestion`.

The shorter import root is chosen deliberately. It is free on PyPI, it is
unambiguous within the codebase, and it establishes a prefix shared by the
sibling repositories — `rag_ingestion`, `rag_contracts`, `rag_retrieval` — which
makes the origin of any import obvious at a glance once Phase 3 introduces the
contracts package as a dependency.

Section 6 of `docs/ARCHITECTURE.md` and the tree in `README.md` are corrected to
match, removing the contradiction described above.

## Consequences

**Positive.** `src/` is not on `sys.path`, so the test suite exercises the
installed distribution rather than the source tree; a green suite is evidence
that the packaged artifact works. The import root cannot collide with any
dependency. Layer boundaries become expressible as module paths, so the
dependency arrow can later be enforced mechanically — for example by asserting
that nothing under `rag_ingestion.domain` imports from `rag_ingestion.infrastructure`
— rather than by review alone. The build backend needs no manual package
enumeration.

**Negative.** The distribution name and the import name differ, which reliably
confuses a first-time reader who looks for a `devtools_rag_ingestion` directory
and does not find one. Every import carries a prefix that the flat alternative
would not have needed. The package must be installed, normally in editable mode
via `uv sync`, before the tests can run at all; a contributor who tries to run
`pytest` against a bare checkout gets an import error rather than a test result,
which is a genuine and recurring source of confusion for anyone meeting the src
layout for the first time.
