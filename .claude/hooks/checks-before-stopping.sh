#!/usr/bin/env bash
# Stop hook: before the agent hands control back, run what CI's `checks` job
# runs, minus the integration tests.
#
# `docs/COLLABORATION.md` section 9: "after each step, run lint, type check and
# tests before proposing the next one." This makes that the default instead of
# a thing to remember. Exit 2 keeps the agent working, with the failures as its
# next input.
#
# Deliberately narrow:
# - Only when a Python file differs from HEAD. A turn that only talked, or only
#   touched docs, pays nothing.
# - Unit tests only. Integration tests need a Docker daemon (ADR 0011) and CI
#   runs them anyway.
# - `stop_hook_active` means this hook already sent the agent back once. Then it
#   reports and lets it stop: a check the agent cannot fix must reach the human,
#   not loop.
set -uo pipefail

input=$(cat)
if [ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)" = "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
command -v uv > /dev/null 2>&1 || exit 0

changed=$( { git diff --name-only HEAD -- '*.py'; git ls-files --others --exclude-standard -- '*.py'; } 2>/dev/null )
[ -n "$changed" ] || exit 0

failures=""
run() {
  local label=$1
  shift
  local output
  if ! output=$("$@" 2>&1); then
    failures+=$'\n'"== $label failed =="$'\n'"$(printf '%s' "$output" | tail -n 40)"$'\n'
  fi
}

run "ruff check" uv run --quiet ruff check
run "ruff format --check" uv run --quiet ruff format --check .
run "mypy --strict" uv run --quiet mypy
run "unit tests" uv run --quiet pytest -m "not integration" -q

if [ -n "$failures" ]; then
  echo "The checks CI runs are not green. Fix them, or report them to Carlos if they cannot be fixed within the approved change:" >&2
  printf '%s\n' "$failures" >&2
  exit 2
fi

exit 0
