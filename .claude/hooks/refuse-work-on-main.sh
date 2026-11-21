#!/usr/bin/env bash
# PreToolUse hook for Bash: refuse to commit on `main` or push to it.
#
# `docs/COLLABORATION.md` section 3 says "Never commit to main. Never push
# directly." The GitHub ruleset already rejects a push to `main`, but only after
# the commit exists; this stops the agent one step earlier, while the fix is
# still "switch branch" rather than "undo a commit".
#
# Exit 2 blocks the tool call and hands stderr to the agent as the reason. Any
# other outcome lets the command run: a hook that cannot read its input must not
# become the thing that stops all work.
set -uo pipefail

command=$(jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[ -n "$command" ] || exit 0

refuse() {
  echo "Refused by .claude/hooks/refuse-work-on-main.sh: $1" >&2
  echo "Create a branch first (feat/, fix/, refactor/, test/, docs/, chore/) - docs/COLLABORATION.md section 5." >&2
  exit 2
}

# A push that names `main` as its destination, from any branch.
if printf '%s' "$command" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+push([[:space:]].*)?[[:space:]](origin[[:space:]]+)?([^[:space:]]*:)?main([[:space:]]|$)'; then
  refuse "this pushes to main."
fi

# A commit or a bare push while `main` is checked out.
if printf '%s' "$command" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+(commit|push)([[:space:]]|$)'; then
  branch=$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null || true)
  if [ "$branch" = "main" ]; then
    refuse "main is checked out."
  fi
fi

exit 0
