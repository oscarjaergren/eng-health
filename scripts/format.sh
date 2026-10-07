#!/usr/bin/env bash
#
# Formats the repo, or the files given. Fixing only; verification belongs to the git hooks.
#
# Usage: scripts/format.sh [files...]
#
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# Pinned tools through mise, because editor hook environments often lack its shims. A formatter
# that silently does nothing is worse than one that fails, so there is no PATH fallback.
run() { mise exec -- "$@"; }

py=() rs=() other=()
for f in "$@"; do
  rel="${f#"$ROOT"/}"
  case "$rel" in
    *.py) py+=("$rel") ;;
    *.rs) rs+=("$rel") ;;
    *.md | *.json) other+=("$rel") ;;
  esac
done

if [ "$#" -eq 0 ] || [ "${#py[@]}" -gt 0 ]; then
  # --fix applies only safe fixes, such as import order; the rest stay for the hooks to report.
  run uv run --locked ruff check --fix --quiet --exit-zero ${py[@]+"${py[@]}"}
  run uv run --locked ruff format --quiet ${py[@]+"${py[@]}"}
fi

# rustfmt formats a whole crate as cheaply as one file.
if [ "$#" -eq 0 ] || [ "${#rs[@]}" -gt 0 ]; then
  run cargo fmt --manifest-path sync/Cargo.toml
fi

if [ "$#" -eq 0 ] || [ "${#other[@]}" -gt 0 ]; then
  run dprint fmt ${other[@]+"${other[@]}"}
fi
