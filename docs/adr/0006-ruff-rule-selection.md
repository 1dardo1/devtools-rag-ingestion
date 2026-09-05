# 6. Select `ruff` rules deliberately rather than by default or in bulk

- **Status:** Accepted
- **Last revised:** 2026-09-05

## Context

`ruff` does two jobs. Formatting has no decision to make: the default style is
accepted, as it would be with `black`. Linting does. `ruff` 0.16.5 ships 969
rules across roughly sixty families, and enables only `E4`, `E7`, `E9` and `F`
by default — a far more permissive baseline than the tool's reputation suggests.

Rule selection has the same asymmetry as type strictness, and for the same
reason `docs/ROADMAP.md` puts the toolchain in Phase 0: a rule enabled today
costs nothing, because there is no code. The same rule enabled after Phase 4
requires fixing every existing violation at once.

Some families interact with decisions already recorded here, which rules out
adopting a catalogue unexamined:

- `ANN` (annotations) is redundant. ADR 0005 runs `mypy --strict` over both
  `src` and `tests`, which covers the same ground and does it better.
- `TC` (formerly `TCH`) moves imports into `if TYPE_CHECKING:` blocks. Under
  Python 3.14 with PEP 649 (ADR 0002) the benefit is diminished, and it can
  break the runtime annotation introspection Pydantic depends on.
- `COM` and `ISC` conflict with the formatter by design.

## Options considered

- **The `ruff` defaults.** Four families, no configuration, no false positives.
  Rejected: it detects neither mutable default arguments, nor unordered
  imports, nor naive datetimes, nor anything from the security family. For a
  repository whose stated value is operational maturity, it is the linting
  equivalent of shipping with the warnings switched off.

- **`select = ["ALL"]` with exclusions.** Maximum coverage by definition.
  Rejected on three counts: `ALL` contains mutually contradictory families
  (`D` selects two mutually exclusive pairs of rules unless a convention is
  named — see below), it includes families that conflict with decisions above,
  and every `ruff` upgrade can add rules that break CI without a line of code
  changing. In practice it produces a long `ignore` list nobody revisits, which
  is the opposite of a deliberate selection.

- **A selected set, justified family by family.** Chosen. It is the only option
  where each rule can be defended individually, which is what
  `docs/COLLABORATION.md` requires of any decision recorded here.

## Decision

```toml
[tool.ruff]
target-version = "py314"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "UP", "B", "S", "A", "C4", "D", "DTZ",
          "T20", "SIM", "RUF", "PT", "TID", "PTH", "TRY", "LOG", "G", "ARG",
          "EM"]
ignore = ["D105", "D107"]

[tool.ruff.lint.pydocstyle]
convention = "pep257"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "ARG001", "ARG002", "D"]
```

Families that earn their place for reasons specific to this service, rather
than by general good practice:

- **`DTZ`** — naive datetimes. The outbox rows carry timestamps written to
  PostgreSQL; a `datetime` without a timezone is a latent bug there.
- **`S`** — security. Phase 13 is explicitly security hardening. Starting with
  this family off and switching it on then is precisely the retrofit the
  roadmap argues against.
- **`TID`** — bans relative imports, so every import reads
  `from rag_ingestion.<layer>...`. This makes a layer importing across a
  boundary visible in the import line itself, reinforcing ADR 0003.
- **`T20`** — a stray `print` in a service with structured logging is an
  uncontrolled data escape, not a style problem.
- **`TRY` and `EM`** — see below.

`E501` is kept. It was checked against the formatter rather than assumed: a
long single-token line such as a URL is not reported, and only a long
*splittable* string the formatter declines to break is. Those cases are
usually a signal that the text belongs somewhere else.

Excluded deliberately: `ANN`, `TC`, `COM`, `ISC` for the reasons in the context
above; `RET`, `FBT`, `ERA` and `PL` as opinionated or noisy relative to what
they contribute here.

`D` was excluded at first and admitted at the end of Phase 1, once there was
real code to judge it against. See below.

### `TRY` and `EM` were checked against realistic code, not assumed

Both were suspected of conflicting with the codebase. They do not — they push
toward the pattern this architecture wants. Verified against a domain error
module and a use case:

| Line | Result |
|---|---|
| `raise CollectionNotFoundError(collection_id)` — a named domain exception building its own message | **not flagged** |
| `raise ValueError(f"Document {h} already ingested in {c}")` | `TRY003`, `EM102` |
| `raise RuntimeError("could not normalise the hash") from exc` | `TRY003`, `EM101` |

The two families together penalise generic exceptions carrying ad-hoc strings
and leave named domain exceptions alone, which is the direction Phase 1 should
move in regardless.

**With one qualification, found when the value objects were written.** `EM101`
looks at the *argument*, not at the exception class: a named domain exception
raised with a string **literal** is still flagged, even though the literal is
an argument rather than a message.

```python
raise MissingMetadataFieldError("source_library")  # EM101
raise MissingMetadataFieldError(field_name)  # not flagged
```

The rule is satisfied by passing a variable, which in practice means hoisting
the check into a helper that takes the field name as a parameter. That turned
out to remove real duplication rather than merely appease the linter, so no
suppression was needed — but the general claim above is narrower than it first
appeared, and a future case may not resolve as tidily.

### `ARG` conflicts, and the conflict is confined to `tests/`

`ARG` was suspected of clashing with `Protocol`-imposed signatures. It does,
and the clash was reproduced rather than predicted. Two distinct cases, both in
test code:

- An in-memory fake implementing `DocumentRepository` and legitimately ignoring
  a parameter the port declares raises `ARG002`. The `Protocol` definition
  itself is not flagged, because stub bodies are exempt.
- A pytest fixture requested for its side effect and unused in the body raises
  `ARG001`.

The apparent fix — renaming the parameter to `_collection_id` — silences `ruff`
and **is disqualified**. It passes `mypy --strict`: the fake still satisfies the
protocol structurally, so `as_port: DocumentRepository = fake` type-checks
clean. But calling through the port by keyword then fails at runtime:

```
TypeError: InMemoryDocumentRepository.save() got an unexpected keyword
argument 'collection_id'. Did you mean '_collection_id'?
```

Code that passes every static check and crashes at runtime is exactly the
failure mode ADR 0005 exists to prevent, so the rename is not available as a
workaround. `ARG001` and `ARG002` are therefore disabled for `tests/**`
instead, where both legitimate cases live, and left active in `src/`.

`S101` is likewise disabled under `tests/**`: `assert` is pytest's mechanism.

### `D` was deferred to the end of Phase 1, then measured

`D` was held back from the first commit for one reason: it would have demanded
a docstring on every function before there was any code to judge whether the
demand was reasonable. Phase 1 finished with fourteen domain modules and 132
tests, and the family was run against them rather than argued about.

| Rule | `src/` | `tests/` |
|---|---|---|
| `D100` module without a docstring | **0** | **0** |
| `D101`/`D102`/`D103` public class, method, function | **0** | 86 |
| `D2xx` formatting, `D4xx` punctuation | **0** | 0 |
| `D105` magic method | 13 | 0 |
| `D107` `__init__` | 13 | 4 |
| `D401` non-imperative summary | 2 | 0 |

The finding that decided it: **`src/` already satisfied every expensive rule**
— the ones that require writing documentation — without the linter ever having
run. `D` therefore corrects nothing today. It is enabled as a ratchet for
Phases 2 to 13, where the cost of adding it later is the cost of fixing every
violation at once.

`convention = "pep257"` is not optional. Without it `ruff` reports:

```
warning: D203 and D211 are incompatible. Ignoring D203.
warning: D212 and D213 are incompatible. Ignoring D213.
```

Naming the convention makes that choice deliberate instead of incidental, and
it is the same objection that ruled out `select = ["ALL"]` above.

Two rules are switched off, each for a reason rather than for volume:

- **`D105`** (magic methods) — the 13 sites are `__post_init__`, `__eq__`,
  `__hash__` and `__str__`. What they do is defined by Python; a docstring
  there restates the language.
- **`D107`** (`__init__`) — the 13 sites are the domain exceptions in
  `errors.py`. Each is a single `super().__init__(f"...")` under a class that
  already carries a `Raised when …` docstring. The rule would produce a copy of
  the line above it.

`D401` is kept, and it earned its place immediately: it caught the only three
docstrings in `src/` written as statements rather than as instructions — the
state transitions on `Document`. The other fifteen already began *Mint*,
*Rebuild*, *Fingerprint*, *Reject*, *Announce*, *Store*, *Retrieve*, *Count*.
The rule found a genuine inconsistency in one class, not a style preference.

`tests/**` is exempt from the family entirely. A test here is named as a
sentence — `test_content_present_in_another_collection_does_not_count_as_present`
— and a mandatory docstring would restate that name in prose for all 132. The
tests that carry a docstring carry it because there was a reason to record, and
that stays voluntary.

## Consequences

**Positive.** Every family can be justified individually, which is the standard
this repository holds decisions to. `D` in particular was admitted on evidence
rather than on principle, after the code existed to produce it. The set catches
real defects rather than style alone — mutable default arguments, naive
datetimes, security findings, stray `print` calls — and it does so from the
first commit, when the cost of compliance is zero. `TID` turns a hexagonal
boundary violation into something visible in an import line. `TRY` and `EM`
push exception design toward named domain errors before any exception exists to
migrate.

**Negative.** The list has to be maintained and understood; it is more
configuration to read than a default. `S` and `PTH` are large families and some
of their findings will be mechanical rather than meaningful. `TRY003` in
particular is among the more contested rules in the ecosystem, and it will
force a named exception class in cases where an inline message would have been
enough.

Ignoring `D105` and `D107` globally is broader than the cases that justify it.
Both were judged against the domain layer, where every magic method is a
dataclass or identity method and every `__init__` is an exception constructor.
An adapter in Phase 4 with a genuinely complex `__init__` will go undocumented
without the linter saying so.

Suppressing `ARG001` and `ARG002` across `tests/**` is broader than the two
cases that justify it: a genuinely forgotten parameter in a test helper will now
pass unnoticed. The narrower alternative, a per-line `noqa` on each fake, was
rejected as noise on a pattern that will recur in every fake this project
writes.

The selection is a snapshot of `ruff` 0.16.5. Upgrades add rules to existing
families and can surface new findings without a code change — smaller in blast
radius than `ALL`, but not zero.
