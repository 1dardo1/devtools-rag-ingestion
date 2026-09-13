"""The fifth guard: nothing credential-shaped is in the repository. ADR 0022.

`ROADMAP.md` 6.3 asks for "no secret in the repository, `.env.example` present",
and the plan's own graph makes it the last thing standing between here and 7.2,
the public deployment that closes the gate.

**A guard rather than an assertion in an ADR**, for the reason the other four
exist: a rule that depends on somebody remembering is not a rule. It is weaker
than an entropy-based scanner and that is recorded rather than hidden — it finds
only the shapes it knows. What it buys instead is that it runs in every pull
request with no third party to pin and audit, and it encodes exactly what *this*
project could plausibly leak.
"""

import re
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

_NO_GIT = "git is not on PATH, so the set of committed files cannot be determined"

# This file is excluded because it necessarily contains every pattern it looks
# for, and a test that fails on its own source is no use. That is a real hole —
# a secret hidden *here* would go unseen — and it is accepted knowingly: this is
# a test file, short, and read by anybody reviewing the guard itself.
#
# `uv.lock` is excluded because it is a wall of wheel hashes. They are
# high-entropy by construction and none of them is a credential; scanning it
# would mean either constant false positives or a weakened pattern, and a
# weakened pattern is the thing this guard exists to avoid.
_NOT_SCANNED = frozenset(
    {
        "tests/unit/test_no_secret_is_committed.py",
        "uv.lock",
    }
)

# Each pattern is something this repository could realistically come to contain,
# not a tour of every credential format in existence. A pattern that can never
# match is a pattern nobody maintains.
_FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        # The one that matters most here, because it is the shape of the service's
        # single required setting. `DATABASE_URL` carrying a password is how this
        # project would leak a credential if it ever did.
        "a connection URL carrying a password",
        re.compile(r"\b(?:postgres(?:ql)?|redis|amqp|mysql)://[^\s:/@]+:[^\s:/@]+@"),
    ),
    (
        "a private key block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
    (
        "an AWS access key id",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "a GitHub token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"),
    ),
    (
        "an OpenAI-style API key",
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    ),
    (
        # An assignment with an actual value, rather than the bare name. `PASSWORD=`
        # with nothing after it is what `.env.example` and a compose file legitimately
        # contain; `PASSWORD=hunter2` is not.
        #
        # **No `\b` before the keyword**, and that is not a detail: `\b` does not
        # match inside `POSTGRES_PASSWORD`, because the preceding `_` is a word
        # character. The first version of this pattern had one and matched nothing
        # of the sort — which `test_the_guard_can_actually_see_a_secret` caught on
        # its first run, which is the entire reason that test exists. Leading
        # identifier characters are consumed instead, so any name *ending* in one
        # of these words counts.
        "a secret assigned a value",
        re.compile(
            r"(?i)[A-Za-z0-9_-]*(?:password|passwd|secret|api[_-]?key|"
            r"access[_-]?token|private[_-]?key)\s*[:=]\s*['\"]?[^\s'\"{}$<(#,)\]]+"
        ),
    ),
)


def _tracked_text_files() -> list[Path]:
    """Every file that is in the repository or about to be.

    `git ls-files` rather than walking the tree, because walking would scan
    `.venv` — half a gigabyte of other people's code, with its own fixtures full
    of example credentials.

    **`--others --exclude-standard` as well as the tracked set, and that was not
    the first version.** Tracked files alone meant a brand-new file was invisible
    until `git add`, so running the suite before staging gave a *false pass* — which
    is exactly what happened to ADR 0022 itself: green locally, then caught from CI
    once the commit made it tracked. The set that matters is "what would be in the
    repository if this were committed", and `--exclude-standard` is what keeps that
    honest: a developer's real `.env` is gitignored, so it stays out, which was the
    whole reason for not walking the tree in the first place.
    """
    # The absolute path, because `ruff`'s S607 objects to a partial one: a bare
    # `git` resolves through `PATH`, which a hostile environment controls.
    git = shutil.which("git")
    assert git is not None, _NO_GIT
    # S603 wants a check for untrusted input. There is none: the argument list is
    # three literals and a path `shutil.which` resolved. Silenced rather than
    # restructured, because the alternative — walking the tree instead — would scan
    # *untracked* files, and an untracked `.env` on a developer's machine is not in
    # the repository. A guard that cries about those is a guard people learn to
    # ignore.
    listed = subprocess.run(  # noqa: S603 - a literal argv with a resolved path
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = []
    for name in listed.stdout.split("\0"):
        if not name or name in _NOT_SCANNED:
            continue
        path = _ROOT / name
        if path.is_file():
            paths.append(path)
    return paths


def test_no_secret_is_committed() -> None:
    found: list[str] = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Not text, so not a committed secret in any form this can read.
            continue
        for description, pattern in _FORBIDDEN:
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                relative = path.relative_to(_ROOT)
                found.append(f"{relative}:{line} looks like {description}")

    assert not found, "Something credential-shaped is committed:\n  " + "\n  ".join(
        found
    )


def test_the_guard_can_actually_see_a_secret() -> None:
    """Because a guard that matches nothing passes for the wrong reason.

    Every pattern is exercised against a string it must catch. Without this, a
    typo in a regex would make `test_no_secret_is_committed` pass forever while
    checking nothing — the failure mode that makes a green suite a liar.
    """
    samples = {
        "a connection URL carrying a password": (
            "postgresql://ingestion:hunter2@db.example.com:5432/ingestion"
        ),
        "a private key block": "-----BEGIN RSA PRIVATE KEY-----",
        "an AWS access key id": "AKIAIOSFODNN7EXAMPLE",
        "a GitHub token": "ghp_" + "a" * 36,
        "an OpenAI-style API key": "sk-" + "b" * 24,
        "a secret assigned a value": "POSTGRES_PASSWORD=hunter2",
    }

    assert set(samples) == {description for description, _ in _FORBIDDEN}, (
        "a pattern was added or renamed without a sample that proves it matches"
    )
    for description, pattern in _FORBIDDEN:
        assert pattern.search(samples[description]), (
            f"the pattern for {description} no longer matches its own example"
        )


def test_the_example_file_names_every_setting() -> None:
    """`.env.example` and `Settings` must not drift apart.

    An example file that has gone stale is worse than none: it answers "what does
    a deployment need?" confidently and wrongly. This is the only thing keeping
    the two in step, since nothing imports the file.
    """
    from rag_ingestion.config import Settings

    example = (_ROOT / ".env.example").read_text(encoding="utf-8")
    named = {
        line.split("=", 1)[0].strip()
        for line in example.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }

    expected = {name.upper() for name in Settings.model_fields}

    assert named == expected, (
        ".env.example and Settings disagree."
        f" Only in the file: {sorted(named - expected)}."
        f" Only in Settings: {sorted(expected - named)}."
    )
