---
name: systematic-debugging
description: Use in devtools-rag-ingestion when a test fails, CI is red, a check errors, or the service behaves unexpectedly, before proposing any fix. Finds the root cause first, checks this repository's known traps, and stops to report to Carlos when the cause lies outside the approved change.
---

# Root cause before any fix

**No fix without a root cause.** A change that makes a symptom disappear without
explaining it is a guess, and `docs/COLLABORATION.md` section 7 forbids papering
over a failure.

## Phase 1: find the cause

1. **Read the whole error.** The full traceback, the exit code, the CI log of the
   failing step, not just its last line.
2. **Reproduce it as narrowly as possible:** `uv run pytest path/to/test.py::test_name -x -q`.
   If it does not reproduce, gather more evidence; do not guess.
3. **Check what changed:** `git diff origin/main`, `git log -p -5`, `uv.lock`, the
   environment (Python version, Docker present or not).
4. **Check the known traps first.** Each of these has cost a debugging session
   already, and `CLAUDE.md` records them:
   - Python 3.14.0rc2 cannot import Pydantic (`prefer_fwd_module`);
   - `\b` does not match inside `POSTGRES_PASSWORD`, because `_` is a word character;
   - `add_middleware` inserts at the front, so the last added runs first;
   - `psycopg.connect` rejects SQLAlchemy's `postgresql+psycopg://` form;
   - every domain refusal is raised before the first write, so a refused request
     never reaches the rollback;
   - hatchling validates every path `pyproject.toml` names, so the image needs them;
   - a full relock drops `greenlet` wheels on s390x and riscv64.
5. **Find the failing layer.** The request path is HTTP, use case, adapter,
   PostgreSQL. The event path is outbox, relay, broker. Look at what crosses
   each boundary until you find the layer where it goes wrong. If you add
   temporary logging, use the standard `logging` module with structured
   `extra`, never an f-string (ruff G004), and remove it before committing.

## Phase 2: compare with what works

Find the closest working code in this repository, such as an adapter, a test of
the same shape or an earlier ADR's example, and list every difference, however
small.

## Phase 3: one hypothesis at a time

State it: "X is the cause because Y". Make the smallest change that tests it, and
change one thing only. If it fails, form a new hypothesis; do not stack fixes.

## Phase 4: fix, inside the approved scope only

1. **Write the failing test first** (see `test-driven-development`).
2. **Fix the cause, once.** No "while I'm here" changes.
3. **Verify** (see `verification-before-completion`).

**If the cause is outside the change Carlos approved, stop and report it**
(`docs/COLLABORATION.md` section 3, step 3). Do not fix it in passing. This
applies in particular to the domain, a port, the schema, a dependency, CI, or
configuration, because each of those needs explicit approval.

**Never:** weaken an assertion, add `# type: ignore`, skip, delete or quarantine a
test, or re-run CI hoping it turns green. A job gets at most one re-run, and only
to confirm a failure that does not come from this change.

**After three failed fixes, stop.** The design is in question, not the next
patch. Write down what you tried and what each attempt showed, and take it to
Carlos.

## When there is no root cause in the code

If the cause is truly external, such as a provider, the network or GitHub's
scheduler, record what you investigated, handle it the way an ADR already
decides (ADR 0028's retries, for example), and say so. Most "external" causes
turn out to be investigations that stopped too early.

## Source

Adapted for this repository from `systematic-debugging` in
[obra/superpowers](https://github.com/obra/superpowers) at commit `22f0b46`,
under the MIT licence in `LICENSE` beside this file
(Copyright (c) 2025 Jesse Vincent). The original's supporting files
(a TypeScript example and a shell script) were not copied.
