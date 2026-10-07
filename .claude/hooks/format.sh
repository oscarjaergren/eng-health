#!/usr/bin/env bash
#
# PostToolUse hook: formats each file the agent edits (via scripts/format.sh), so its output is
# CI-clean and the git hooks only have to verify.
#
# A PostToolUse hook cannot block; the edit has already happened. Exit 2 shows stderr to the
# agent, so a real failure uses it rather than leaving the agent to assume its output is
# formatted. Exit 0 means there was nothing to do.
set -uo pipefail

file=$(mise exec -- jq -r '.tool_input.file_path // empty' 2>/dev/null) || {
  echo "format.sh: could not read the hook payload (is mise installed?), so this edit was NOT formatted." >&2
  exit 2
}

case "$file" in
  *.py | *.rs | *.md | *.json) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

root="${CLAUDE_PROJECT_DIR:-$(git -C "$(dirname "$file")" rev-parse --show-toplevel)}"
if ! output=$("$root/scripts/format.sh" "$file" 2>&1); then
  echo "format.sh: formatting $file failed, so it is NOT CI-clean:" >&2
  printf '%s\n' "$output" >&2
  exit 2
fi
