#!/usr/bin/env bash
#
# Mutation tests the Rust changed since a branch (default origin/main), and fails if the tests miss
# a mutant in it: a change no test notices is an untested line, whatever coverage says.
#
# --in-place: the tests read ../testdata, which a copy of the crate wouldn't have. cargo-mutants
# restores each file after testing its mutants.
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel)/sync"

diff=$(mktemp)
trap 'rm -f "$diff"' EXIT
git diff --relative "${1:-origin/main}...HEAD" -- . >"$diff"
cargo mutants --in-place --in-diff "$diff"
