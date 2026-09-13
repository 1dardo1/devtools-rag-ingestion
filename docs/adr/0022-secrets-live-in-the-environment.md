# 22. Secrets live in the environment, and a guard says so

- **Status:** Accepted
- **Last revised:** 2026-09-13

## Context

`ROADMAP.md` 6.3: "Secret management via environment — done when: no secret in the
repository, `.env.example` present."

`docs/BUILD-PLAN.md`'s graph makes this the unit that matters most right now:
`U52 --> U72` and `U63 --> U72`. 5.2 landed, so **6.3 is the last thing between
here and 7.2**, the public deployment that closes the gate — and `CLAUDE.md` says
the gate outranks everything else.

Half of it was already true without being called 6.3. `Settings` reads every value
from the environment through Pydantic Settings (ADR 0017), `alembic.ini` leaves
`sqlalchemy.url` empty on purpose (ADR 0012), and `compose.yaml` runs PostgreSQL
with `POSTGRES_HOST_AUTH_METHOD=trust` precisely so that there is no password to
commit (ADR 0021). What was missing was the example file and, more importantly,
**anything that keeps the claim true tomorrow**.

## Options considered

### How "no secret in the repository" is held

- **A guard in the test suite.** Chosen. It joins four others that exist for the
  same reason: `test_every_endpoint_is_synchronous`,
  `test_the_application_ships_unwired`,
  `test_the_body_cap_cannot_refuse_a_document_the_domain_accepts` and
  `test_the_cap_is_the_outermost_middleware`. A rule that depends on somebody
  remembering is not a rule.
- **A secret scanner in CI** — gitleaks or similar. It catches by entropy what a
  regular expression cannot, and it reads history rather than only the working
  tree. Rejected on cost against benefit here: another third-party action to pin
  by commit and audit — this repository pins every one — for a project with no
  secrets and a history of forty-odd commits, plus an allow-list file to maintain
  the first time it misfires. **Worth revisiting when there is a real credential to
  protect**, which is to say after 7.2.
- **Assert it in this ADR and stop.** Rejected: it is exactly what the four
  existing guards were written to stop doing.

### What the guard looks for, and what it refuses to excuse

Six shapes, each one something this repository could plausibly come to contain
rather than a tour of every credential format in existence: a connection URL
carrying a password, a private key block, an AWS access key id, a GitHub token, an
OpenAI-style key, and a secret-named variable assigned an actual value.

**No placeholder allowance, and that was a decision rather than an oversight.** The
obvious convenience is to ignore matches whose password reads `PASSWORD` or
`changeme`. It is also how a scanner gets talked into ignoring the real thing, so
instead the repository contains no credential-shaped string at all — `.env.example`
shows a password-free URL matching what `compose.yaml` actually runs, and says in
prose what it no longer shows.

Two exclusions, both recorded because each is a hole:

- **The guard's own file**, which necessarily contains every pattern it searches
  for. A secret hidden there would go unseen. Accepted knowingly: it is a short
  test file that anyone reviewing the guard reads.
- **`uv.lock`**, a wall of wheel hashes that are high-entropy by construction and
  are not credentials. Scanning it would mean either permanent false positives or
  a weakened pattern.

### `git ls-files` rather than walking the tree

Walking would scan `.venv` — half a gigabyte of other people's code, with its own
fixtures full of example credentials. It costs a `subprocess` call and an S603/S607
silence, both documented at the call site.

**The set scanned is `--cached --others --exclude-standard`, not the tracked set,
and the first version got that wrong.** Tracked files alone meant a brand-new file
was invisible until `git add`, so running the suite before staging gave a **false
pass** — which is precisely what happened to this ADR: green locally, then caught
from CI once the commit made it tracked.

The right set is "what would be in the repository if this were committed", and
`--exclude-standard` is what keeps that from becoming the noisy version: a
developer's real `.env` is gitignored, so it stays out, which was the reason for
not walking the tree to begin with. Both halves are asserted by mutation — an
unstaged file carrying a password is caught, and a gitignored `.env` carrying the
same password is not.

## Decision

`.env.example`, listing exactly the three settings `Settings` declares, marking
which is required, and explaining each. `.gitignore` already had `.env`, `.env.*`
and `!.env.example`, so it is tracked and the real file is not.

Three tests in `tests/unit/test_no_secret_is_committed.py`:

1. **`test_no_secret_is_committed`** scans every tracked text file for the six
   shapes and reports file and line for each hit.
2. **`test_the_guard_can_actually_see_a_secret`** runs every pattern against a
   string it must match, and fails if a pattern is added without a sample.
3. **`test_the_example_file_names_every_setting`** compares `.env.example` against
   `Settings.model_fields`, because an example that has drifted answers "what does
   a deployment need?" confidently and wrongly.

### One thing 6.3's wording asks for that is not being delivered literally

It says "no password, key **or connection string** is written down anywhere". A
connection string *is* written down — in `compose.yaml` and in `.env.example` —
and deliberately: `postgresql://postgres@localhost:5432/ingestion` names a
local database with no credential in it. Recording this rather than quietly
reading the requirement as "no secret", because the two are not the same sentence
and a reader deserves to know which one this repository satisfies. **A connection
string with no password is not a secret; one with a password is, and that is what
the guard forbids.** If the intent was the stricter reading, the fix is a variable
with no default anywhere and the compose file interpolating it — which trades
`docker compose up` working on a clean machine for protecting a value that does not
exist.

## Consequences

**6.3 is done, so 7.2 is unblocked and the gate is one unit away.** Everything else
in Phase 6 — coverage, further integration tests — is now optional polish next to
a public URL, which `CLAUDE.md` ranks above it explicitly.

**The guard found something on its first run, in a file that had been read several
times.** `config.py`'s `database_url` description illustrated the URL shape with a
literal `user:password@` in it — the exact shape of the one credential this service
could leak. It was a placeholder and it was still removed, on the no-allowance rule
above. That is the guard paying for itself before it was committed.

**Then it found the same mistake twice more, in the explanations of the first
one.** The comment added to `config.py` quoted the string it had just removed, and
so did this ADR's first draft — flagged from CI, at this very paragraph. Writing
about a forbidden pattern by reproducing it is apparently the natural reflex, and
the guard catches it every time, which is the argument for having one stated better
than any of these sentences manage.

**And `test_the_guard_can_actually_see_a_secret` justified itself immediately.**
The assignment pattern began with `\b`, which **does not match inside
`POSTGRES_PASSWORD`** because the preceding `_` is a word character — so it caught
nothing of the sort. Without that second test, `test_no_secret_is_committed` would
have passed forever while looking for a shape it could not see. A guard that
matches nothing is worse than no guard, because it reports safety.

**Negative: it finds only the shapes it knows.** A high-entropy string with no
recognisable form gets through. This is the accepted cost of declining the scanner,
and it is why the scanner is marked as worth revisiting after 7.2, when there is
something to protect.

**Negative: the exclusions are real holes,** enumerated above rather than left for
someone to discover.

**Negative: `.env.example` must be edited by hand whenever `Settings` changes.**
Test 3 makes forgetting loud rather than impossible. Generating the file from
`Settings` was considered and dropped: the value of the file is the prose beside
each variable, which no generator would write.

**Verified by mutation, because a guard nobody has watched fail is a guess.** A
planted `DATABASE_URL` with a password, a planted private key header, and a new
`Settings` field left out of the example were each caught, and each error message
named the file and line.
