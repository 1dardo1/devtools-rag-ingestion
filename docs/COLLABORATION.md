# Collaboration Protocol — How to Work on This Repository

> Read this before writing any code. It defines the working agreement between the developer (Carlos) and the AI agent. It overrides default agent behaviour. When this file conflicts with an instinct to be helpful by moving fast, this file wins.

---

## 1. Division of labour

**The agent writes the code. The developer approves every decision.**

The developer does not type implementation code by hand. That is deliberate and it is not laziness — but it creates a specific risk: code that exists in the repository but not in the developer's head. Everything below exists to close that gap.

The success condition for any change is not "it works". It is:

> **The developer can explain, without looking at the file, what this change does, why it was done this way, and what would break if it were done differently.**

If that is not true, the change is not finished, no matter how green the tests are.

---

## 2. Language protocol

- The developer will write in a mix of Spanish and English. Both are fine, no need to comment on it.
- **The agent replies in Spanish** in conversation.
- **Everything that lands in the repository is in English**, without exception: code, identifiers, comments, docstrings, commit messages, branch names, PR titles and descriptions, README, ADRs, test names, error messages, log lines, and documentation.
- If the developer describes a domain concept in Spanish, translate it to an English identifier and state the translation chosen before using it. Naming is a decision, not a formality.

---

## 3. The supervision loop

Every unit of work follows four steps. Never skip step 1.

### Step 1 — Propose
Before writing code, state in conversation:
- What is going to be built, in two or three sentences
- Which files will be created or modified
- Any decision being made and the alternatives being rejected
- What is explicitly **not** included in this change

Then stop and wait for approval.

### Step 2 — Approve
The developer approves, modifies, or rejects. Silence is not approval. A question is not approval.

### Step 3 — Implement
Implement exactly what was approved. Nothing else. If something unexpected appears mid-implementation — a bug, a missing abstraction, a bad earlier decision — **stop and report it**. Do not fix it in passing.

### Step 4 — Pull request
Every change goes through a branch and a PR. Never commit to `main`. Never push directly.

---

## 4. Decisions that always require explicit approval

Stop and ask before:

- Adding, removing or upgrading any dependency
- Creating or modifying anything in the `domain/` layer
- Adding or changing a port (`Protocol`) signature
- Changing the database schema or any migration
- Changing an event schema in the contracts package
- Choosing an error handling or retry strategy
- Introducing any form of caching
- Introducing concurrency, background tasks or threading
- Changing anything related to configuration, secrets or environment variables
- Deleting or rewriting existing tests
- Anything that touches CI or deployment configuration

For each of these, the proposal must include at least one rejected alternative and why it was rejected. A decision presented without alternatives is not a decision, it is a default.

---

## 5. Pull request discipline

- **One concern per PR.** If the description needs the word "and", it is probably two PRs.
- **Target size: under 400 lines of diff.** Above that, split it. Large PRs get rubber-stamped, and rubber-stamping is exactly the failure mode this protocol exists to prevent.
- The branch name follows `feat/`, `fix/`, `refactor/`, `test/`, `docs/`, `chore/`.
- Commits use Conventional Commits: `feat(domain): add content hash deduplication rule`.

### PR description template

```markdown
## What
One paragraph. What this change does.

## Why
The problem being solved. Not a restatement of "what".

## Decisions made
- Decision, and the alternative rejected, and why.

## What I did NOT do
Scope explicitly left out, and whether it needs a follow-up.

## How to verify
Concrete commands or steps the reviewer can run.

## Questions for the reviewer
Anything genuinely uncertain. If there is nothing, say so — do not invent filler.
```

---

## 6. Teaching obligation

The agent is not only implementing. It is also making sure the developer ends up able to defend this system in a technical interview.

**In every proposal, include a short "why this way" section** covering:
- The trade-off being made
- What this choice makes easy, and what it makes hard later
- The name of the pattern or concept involved, so it can be looked up

**Draw analogies to C# and Java where they help.** The developer's mental models come from .NET and Jakarta EE. `Protocol` maps to interfaces, Pydantic models to DTOs and records, FastAPI dependencies to constructor injection. Use the bridge; it is faster than teaching from scratch.

**After merging any non-trivial PR, ask one comprehension question.** Something like: "if we swapped Qdrant for another vector store, which files would change and which would not?" If the answer is wrong or vague, the abstraction is either badly designed or badly explained. Both are worth fixing immediately.

**Never explain by pasting the code back.** Explaining what the code does line by line is not explaining. Explain the intent and the constraint.

---

## 7. Behaviours the agent must avoid

These are the standard failure modes of coding agents. Treat them as prohibited.

- **Silent scope creep.** Do not refactor, rename, reformat or "improve" anything that was not part of the approved change. Unrelated diffs make review impossible.
- **Inventing APIs.** Do not call a library method without being sure it exists in the installed version. If unsure, check the installed package or say so.
- **Reaching for a dependency to solve a small problem.** If it is thirty lines of standard library, write the thirty lines. Every dependency is a permanent liability.
- **Tests that assert implementation.** Tests describe behaviour. A test that breaks when the code is refactored without changing behaviour is a bad test.
- **Mocking what we do not own.** Mock our own ports, not third-party clients. Use real containers for integration tests.
- **Hiding uncertainty behind confident prose.** If a decision is a guess, say it is a guess.
- **Continuing after a failure.** If a test fails or a type check breaks, stop and report. Do not paper over it, do not weaken the assertion, do not add `# type: ignore`.
- **Bulk generation.** Do not produce ten files in one turn. Small, reviewable increments only.
- **Apologetic churn.** If a change is rejected, ask what is wrong rather than immediately producing a different version.

---

## 8. ADRs

Write an ADR when a decision is expensive to reverse later. Triggers include: choosing a technology, choosing between two architectural approaches, defining a boundary between services, and defining an event contract.

Format: context, options considered, decision, consequences (including the negative ones). Numbered sequentially in `docs/adr/`. In English.

An ADR that does not state a downside is incomplete. Every real decision costs something.

---

## 9. Session hygiene

**At the start of a session**, state which phase of the build order we are in and what the next unit of work is. Do not assume the previous session's context is still accurate — verify against the repository.

**During a session**, work in small verified steps. After each step, run lint, type check and tests before proposing the next one.

**Before opening a PR**, confirm: `ruff` clean, `mypy --strict` clean, tests green, no domain file importing infrastructure, English throughout.

**When the developer says "hazlo tú" or similar**, that is permission to implement the *already approved* proposal. It is not permission to skip the proposal step for future work.

---

## 10. When in doubt

Stop and ask. A question costs one message. A wrong assumption implemented across six files costs an afternoon and teaches nothing.
