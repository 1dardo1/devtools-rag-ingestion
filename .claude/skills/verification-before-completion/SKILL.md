---
name: verification-before-completion
description: Use before saying that anything in devtools-rag-ingestion is done, fixed, green or passing, and before every commit, push, pull request or report to Carlos. Names the exact command that proves each claim in this repository, what this container can and cannot run, and how to report a check that was not run.
---

# Evidence before claims

`docs/COLLABORATION.md` section 7 forbids hiding uncertainty behind confident
prose. This skill is that rule made mechanical.

**No claim of success without the output of the command that proves it, run in
this turn, on the code as it stands now.** A run from before the last edit proves
nothing about the code after it.

## The gate

1. **Name the command** that would prove the claim (table below).
2. **Run it**, complete, not a subset.
3. **Read the output**: exit code, counts, warnings.
4. **Say what it showed.** If it did not prove the claim, report the real state.
5. **If it cannot run here, say so** and name what would settle it. Never
   substitute a guess.

## What proves what in this repository

| Claim | Proved by | Not proved by |
|---|---|---|
| Lint is clean | `uv run ruff check` | an editor, the hook on one file |
| Formatting is clean | `uv run ruff format --check .` (it reads Markdown too) | `ruff check` |
| Types are clean | `uv run mypy` (strict, `src` and `tests`) | tests passing |
| Unit tests pass | `uv run pytest -m "not integration"` | the one file you changed |
| Integration tests pass | `uv run pytest -m integration` with Docker, or the local PostgreSQL route in `CLAUDE.md` | unit tests, fakes |
| Coverage floor holds | CI's `coverage report` (`fail_under = 99`, ADR 0024) | a local report without Docker, which is about 93% by design |
| The image builds and starts | CI's `image` job (ADR 0020) | a `Dockerfile` that looks right |
| CI is green | `gh api repos/1dardo1/devtools-rag-ingestion/commits/<head sha>/check-runs` on the **current** head | an earlier head, a notification that a suite finished |
| A subagent finished its task | `git diff` of its branch and the checks above, run by you | its report |

## Traps specific to this container

- **Python 3.14.0rc2 cannot import Pydantic.** Collection fails with
  `_eval_type() got an unexpected keyword argument 'prefer_fwd_module'`. That is
  the interpreter, not the change. Install a final 3.14 with
  `uvx uv@0.12.10 python install 3.14` and point `UV_PYTHON` at it.
- **There is no Docker daemon.** Integration tests and the `image` and `compose`
  jobs cannot run here. Either use the local PostgreSQL route described in
  `CLAUDE.md`, or report them as "not run here; CI decides".
- **A local coverage report fails the floor without Docker.** Pass
  `--fail-under=0` locally and never report the floor as met from a local run.
- **Hooks are not optional.** A hook that cannot run lets the action through. A
  turn that passed only because a hook did not run has not passed.

## Red flags: stop and verify

- "should pass", "probably", "looks right", "seems fine";
- "Done", "Fixed", "All green" before the command ran in this turn;
- quoting a subagent's "all tests pass" as your own result;
- reporting CI from a head that is no longer the PR's head.

## How this relates to the other skills

`pre-pr-check` is the checklist before a pull request. This skill is the rule
that every item on that checklist, and every other claim, is backed by output.

## Source

Adapted for this repository from `verification-before-completion` in
[obra/superpowers](https://github.com/obra/superpowers) at commit `22f0b46`,
under the MIT licence in `LICENSE` beside this file
(Copyright (c) 2025 Jesse Vincent). The commands, the table and the traps are
this repository's; the gate is the original's.
