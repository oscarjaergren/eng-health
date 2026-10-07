#!/usr/bin/env bash
#
# Keeps the repo's command line and its docs in step: every task describes itself, and every
# `mise run <task>` a markdown file mentions exists. A renamed task can't leave a stale doc.
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

tasks=$(mise tasks ls --json)
status=0

undescribed=$(jq -r '.[] | select(.description == "") | .name' <<<"$tasks")
for task in $undescribed; do
  echo "error: task '$task' has no description, so 'mise tasks' can't explain it." >&2
  status=1
done

names=$(jq -r '.[].name' <<<"$tasks")
# git grep exits 1 for no match, which is fine; anything higher is a real error.
mentions=$(git grep -o -E 'mise run [a-z][a-z0-9-]*' -- '*.md') || [ "$?" -eq 1 ]
while IFS= read -r match; do
  [ -n "$match" ] || continue
  file=${match%%:*}
  task=${match##* }
  grep -qxF "$task" <<<"$names" || {
    echo "error: $file mentions 'mise run $task', which isn't a task." >&2
    status=1
  }
done <<<"$mentions"

exit "$status"
