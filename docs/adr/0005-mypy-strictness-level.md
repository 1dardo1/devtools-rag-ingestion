# 5. Close the three gaps that `mypy --strict` leaves open

- **Status:** Accepted
- **Last revised:** 2026-08-28

## Context

`docs/ARCHITECTURE.md` section 3 and `CLAUDE.md` both require `mypy` in strict
mode, and `docs/ROADMAP.md` justifies the whole of Phase 0 with it: strict typing
is enforced from the first commit because adding it later means fixing hundreds
of errors at once.

`--strict` is not a single setting. It is an umbrella over roughly fifteen flags
covering the code you write, and three decisions of consequence fall outside it:

1. **Untyped third-party code.** `--strict` says nothing about what happens when
   an installed library ships no annotations and no `py.typed` marker.
2. **Scope.** `--strict` does not decide whether `tests/` is checked at all.
3. **Silencing.** `--strict` warns about a `# type: ignore` that has become
   unnecessary, but does not require the suppression to name what it suppresses.

Point 2 carries more weight in this codebase than it looks. Ports are
`typing.Protocol` (a non-negotiable principle, section 4.3), which is structural
typing: a class satisfies a protocol by shape, and nothing forces it to declare
the relationship. The in-memory fakes of Phase 2 and the PostgreSQL adapter of
Phase 4 will implement the same ports. Whether the fake and the real adapter
genuinely agree is checkable statically — but only if the type checker is
pointed at `tests/`. Left unchecked, the claim that the use cases are exercised
against the real port shape is an assertion rather than a verified fact.

This is a learning project, and the stated preference is for the strict reading
of all three even where it costs effort.

## Options considered

- **`--strict` and nothing further.** Check `src/` only, set
  `ignore_missing_imports = true` globally, allow bare `# type: ignore`. No
  friction, never blocks anyone. Rejected because all three gaps stay open at
  once: `Any` from untyped libraries propagates silently through perfectly
  annotated code, the fakes are never checked against the ports, and
  suppressions accumulate without a record of what they hide. The result is
  strict in name.

- **Close the library and suppression gaps, leave `tests/` unchecked.** Keeps
  most of the rigour and all of the speed when writing tests. Rejected because
  it gives up precisely the part with architectural value: under structural
  typing, checking the tests is the only mechanism that proves the doubles match
  the ports.

- **Close all three.** Chosen.

## Decision

`--strict`, plus the three gaps closed explicitly:

```toml
[tool.mypy]
python_version = "3.14"
strict = true
files = ["src", "tests"]
warn_unreachable = true
enable_error_code = [
    "ignore-without-code",
    "redundant-expr",
    "possibly-undefined",
    "truthy-bool",
]
```

- **Untyped libraries.** `ignore_missing_imports` is left at its default of
  `false` and no global override is added. A library without types fails the
  check, and the exception is granted per module in a
  `[[tool.mypy.overrides]]` block naming that module, so every piece of debt is
  visible in `pyproject.toml` rather than ambient.
- **Scope.** Both `src` and `tests` are checked.
- **Silencing.** `warn_unused_ignores` already comes with `--strict`;
  `ignore-without-code` is added on top so a bare `# type: ignore` is itself an
  error and the suppression must name the error code it suppresses. A written
  justification alongside it remains a review requirement, per
  `docs/COLLABORATION.md` section 7, which the tooling supports but cannot
  enforce.

`warn_unreachable` and the three remaining error codes go beyond the three gaps
under discussion and are included as a consistent reading of the same
preference. They are listed separately here so they can be dropped
individually; each is one line.

The configuration above was checked against mypy 2.3.1 before being recorded,
rather than quoted from memory. It is accepted without warnings, it rejects an
unannotated function inside `tests/`, it rejects an import of a library without
stubs, and it rejects `# type: ignore` written without an error code.

## Consequences

**Positive.** The roadmap's justification for Phase 0 becomes literally true and
mechanically verified. The in-memory doubles are checked against the ports they
claim to implement, so a drift between a fake and the real adapter surfaces
without running anything — the guarantee a nominally typed language would give
from the class declaration alone. Every untyped dependency is named in
`pyproject.toml`, which turns type debt into a list somebody can read. Every
suppression states what it suppresses, and mypy reports it once it stops being
needed. The cost of adopting all of this today is zero, because no code exists.

**Negative.** Writing tests is slower, and the in-memory fakes are where it will
be felt: annotating a double whose correctness is obvious to the author is
tedious, and the tedium arrives exactly when the interesting work is the
behaviour being tested. Exploratory throwaway tests stop being cheap.

`testcontainers` is the likely first casualty in Phase 6; expect to write an
explicit override for it, and to spend time understanding why before doing so.
`enable_error_code` entries such as `redundant-expr` and `truthy-bool` flag
patterns that are legal and often deliberate, so some of their findings will
read as noise rather than as bugs.

The standing risk is a rule strict enough to be routed around: a project that
answers every hard type error with an override or a coded ignore has the
configuration without the benefit, and nothing in CI can tell the difference.
That is a review problem, not a configuration one.
