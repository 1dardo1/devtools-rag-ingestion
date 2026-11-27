---
name: test-driven-development
description: Use in devtools-rag-ingestion when implementing an approved change or fixing a bug, before writing the production code. Red, green, refactor with pytest, the repository's fakes and real containers, and its rules on what a test may assert and which tests may never be deleted without approval.
---

# Watch it fail, then make it pass

TDD here starts **after** Carlos has approved the change (`docs/COLLABORATION.md`
section 3, step 3). It does not replace the proposal.

**If you did not watch a test fail, you do not know that it tests anything.**

## The cycle

1. **Red.** Write one test for one behaviour. Before writing it, name the
   production change that would make it fail. Run
   `uv run pytest path/to/test.py::test_name -x -q` and confirm that it fails,
   and fails for the expected reason (the behaviour is missing, not a typo or
   an import error).
2. **Green.** Write the least code that passes. Run that test, then the whole unit
   suite (`uv run pytest -m "not integration"`): green means the suite, not one file.
3. **Refactor.** Only with everything green, and without adding behaviour.

## What a test here may do

- **Assert behaviour, never implementation** (section 7). A test that breaks
  when the code is refactored without a change of behaviour is a bad test.
- **Use this repository's fakes for our own ports** (in-memory repositories, a
  fake broker, a fixed `Clock`, an injected `sleep`). **Never mock what we do not
  own**: no mocked psycopg, Redis client or HTTP library.
- **Use real containers for adapters.** Integration tests start their own through
  `testcontainers` and are marked `@pytest.mark.integration` (ADR 0011).
- **Name the time.** Nothing calls `datetime.now()`; the test sets the `Clock`.
- **Name tests as sentences about behaviour**, as the suite already does:
  `test_a_rollback_leaves_every_row_unpublished`, not `test_rollback_2`.

## When the code already exists

The original skill says to delete code written before its test. **Do not delete
approved or merged code**, and **never delete or rewrite an existing test without
Carlos's approval** (section 4). Instead, prove the new test can fail: revert the
production change temporarily, or break it on purpose, run the test and watch it
fail, then restore the code and watch it pass. Say in the pull request that you
did this. The relay's `SKIP LOCKED` test was checked this way, by switching the
query to `NOWAIT` and back.

## Bug fixes

Write a test that reproduces the bug and fails. Then fix the bug. The test stays
and guards against the bug coming back. See `systematic-debugging` for finding the
cause first.

## Checklist before calling it done

- [ ] Every new behaviour has a test, and each test was seen to fail first.
- [ ] Each failure had the expected reason.
- [ ] The whole unit suite is green, and the integration tests are green, or
      reported as not run here (`verification-before-completion`).
- [ ] No existing test was weakened, skipped or removed.

## Source

Adapted for this repository from `test-driven-development` in
[obra/superpowers](https://github.com/obra/superpowers) at commit `22f0b46`,
under the MIT licence in `LICENSE` beside this file
(Copyright (c) 2025 Jesse Vincent). The TypeScript examples, and the rule to
delete code written before its test, were replaced with this repository's
practice.
