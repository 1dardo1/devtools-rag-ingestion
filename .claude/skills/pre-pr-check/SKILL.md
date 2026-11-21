---
name: pre-pr-check
description: Run the full pre-pull-request checklist for devtools-rag-ingestion. Use every time before opening or updating a pull request, without being asked. Runs the checks CI runs, sends the diff to the boundary and transaction reviewer subagents in parallel, checks the size and scope rules, and drafts the description in the repository's template.
---

# Before a pull request

This is `docs/COLLABORATION.md` section 9 ("Before opening a PR") turned into
steps. It runs in this order because each step is cheaper than the next.

## 1. The checks CI runs

```bash
uv run ruff check
```
```bash
uv run ruff format --check .
```
```bash
uv run mypy
```
```bash
uv run coverage run -m pytest
```

With no Docker daemon, run `uv run pytest -m "not integration"` instead, and
say in the pull request that the integration tests were not run locally. The
coverage floor (99) is binding only in CI. Without the integration tests a
local report is around 93%, so use `--fail-under=0` locally (ADR 0024).

**If any check fails, stop and report it.** Do not weaken an assertion, add a
`noqa`, or add a `# type: ignore` (section 7).

## 2. The reviewers, in parallel

Send both in a single message, so they run at the same time:
- `boundary-reviewer` — always, when anything under `src/` changed;
- `transaction-reviewer` — when `infrastructure/`, `application/`, `main.py`,
  the migrations or any SQL changed.

Relay every finding to Carlos. Do not fix a finding outside the approved scope:
report it (section 3, step 3).

## 3. Scope and size

- `git diff main...HEAD --stat`: **under 400 lines** (section 5). If it is
  larger, propose a split.
- **One concern.** If the description needs the word "and", it is probably two
  pull requests.
- No unrelated diff: no reformatting, renaming or "improvements" outside the
  approved change.
- Everything in English. Conventional Commits. A branch named `feat/`, `fix/`,
  `refactor/`, `test/`, `docs/` or `chore/`, unless the environment fixes the
  branch name.

## 4. The records

- Does `CLAUDE.md`'s "Current phase" still describe the repository? If not,
  update it in the same pull request. A stale one misleads the next session.
- Does a decision need an ADR? If yes, use the `new-adr` skill.

## 5. The description

Fill `.github/pull_request_template.md`: What, Why, Decisions made (each with
the rejected alternative), What I did NOT do, How to verify, Questions for the
reviewer. If there are no questions, say so. Do not invent filler.

## 6. After merge

Ask Carlos one comprehension question about the change (section 6).
