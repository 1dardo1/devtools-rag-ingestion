"""The seventh guard: the agent tooling in `.claude/` is wired to things that exist.

`.claude/settings.json` runs three hook scripts, and `CLAUDE.md` tells the agent
which subagents and skills to use. All of it fails **silently**. Claude Code
treats a hook that cannot start as a non-blocking error and lets the action
through. An agent told to use `boundary-reviewer` when the file is called
something else just does the review itself, or skips it. Nothing goes red, so
nobody notices that the rule stopped applying.

**What this checks.** Every hook command points at an executable script, and
every script is wired. Every subagent and skill declares the name its file is
called by and a description, which is what Claude Code matches on when it
decides to delegate. `CLAUDE.md` names every subagent and skill, and names
nothing that does not exist — both directions, as in the README guard.

**What it does not check.** Whether the hooks behave correctly, or whether the
agent actually delegates. The first was verified by hand when the scripts were
written. The second is judgment, and no test can hold it.
"""

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE_DIR = _ROOT / ".claude"
_HOOKS_DIR = _CLAUDE_DIR / "hooks"
_AGENTS_DIR = _CLAUDE_DIR / "agents"
_SKILLS_DIR = _CLAUDE_DIR / "skills"
_INSTRUCTIONS = _ROOT / "CLAUDE.md"

_PROJECT_DIR = '"${CLAUDE_PROJECT_DIR}"/'
_FRONTMATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)


def _hook_commands() -> list[str]:
    settings: dict[str, Any] = json.loads(
        (_CLAUDE_DIR / "settings.json").read_text(encoding="utf-8")
    )
    return [
        hook["command"]
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]


def _frontmatter(path: Path) -> dict[str, str]:
    """The top-level `key: value` pairs, which is all these files use.

    Parsed by hand rather than with a YAML library, which would be a dependency
    for reading six lines (COLLABORATION.md section 7).
    """
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    assert match, f"{path.relative_to(_ROOT)} has no frontmatter block"
    fields = {}
    for line in match.group("body").splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _agents() -> list[Path]:
    return sorted(_AGENTS_DIR.glob("*.md"))


def _skills() -> list[Path]:
    return sorted(path.parent for path in _SKILLS_DIR.glob("*/SKILL.md"))


def test_every_hook_command_runs_a_script_that_exists() -> None:
    for command in _hook_commands():
        assert command.startswith(_PROJECT_DIR), (
            f"{command!r} should be anchored to the project, or it breaks the"
            " moment the session's working directory is not the root"
        )
        script = _ROOT / command.removeprefix(_PROJECT_DIR)
        assert script.is_file(), f"{command!r} names a script that does not exist"
        assert os.access(script, os.X_OK), f"{script.name} is not executable"


def test_every_hook_script_is_wired() -> None:
    wired = {Path(command).name for command in _hook_commands()}
    present = {path.name for path in _HOOKS_DIR.glob("*.sh")}

    assert present == wired


@pytest.mark.parametrize("agent", _agents(), ids=lambda path: path.stem)
def test_a_subagent_is_called_what_its_file_is_called(agent: Path) -> None:
    fields = _frontmatter(agent)

    assert fields.get("name") == agent.stem
    assert fields.get("description"), "the description is what delegation matches"


@pytest.mark.parametrize("skill", _skills(), ids=lambda path: path.name)
def test_a_skill_is_called_what_its_directory_is_called(skill: Path) -> None:
    fields = _frontmatter(skill / "SKILL.md")

    assert fields.get("name") == skill.name
    assert fields.get("description"), "the description is what invocation matches"


def test_the_instructions_name_every_subagent_and_skill() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    names = [path.stem for path in _agents()] + [path.name for path in _skills()]

    missing = [name for name in names if f"`{name}`" not in instructions]

    assert names, "the tooling directory is empty, so this guard proves nothing"
    assert not missing, f"CLAUDE.md never tells the agent to use {missing}"


def test_the_instructions_name_nothing_that_does_not_exist() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    table = instructions.partition("## Subagents, skills and hooks")[2]
    table = table.partition("\n## ")[0]
    built_in = {"Explore", "claude-code-guide"}
    present = {path.stem for path in _agents()} | {path.name for path in _skills()}

    named = set(re.findall(r"`([a-zA-Z][\w-]*-[\w-]+|Explore)`", table))

    assert named - built_in <= present
