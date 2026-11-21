#!/usr/bin/env bash
# PostToolUse hook for Edit and Write: lint and format-check the one Python file
# that was just changed.
#
# Only `ruff`, because it answers in milliseconds and the agent reads the result
# before its next edit. `mypy` needs the whole program and runs once, when the
# agent tries to stop (checks-before-stopping.sh).
#
# Exit 2 on PostToolUse cannot undo the edit; it shows stderr to the agent so the
# next step is fixing what it just broke. Nothing is reformatted automatically:
# a silent rewrite would be a diff nobody proposed (COLLABORATION.md section 7).
set -uo pipefail

file=$(jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0
command -v uv > /dev/null 2>&1 || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

if ! output=$( { uv run --quiet ruff check "$file" && uv run --quiet ruff format --check "$file"; } 2>&1 ); then
  echo "ruff rejected $file:" >&2
  echo "$output" >&2
  echo "Fix it before the next edit. Do not add a noqa to silence it (COLLABORATION.md section 7)." >&2
  exit 2
fi

exit 0
