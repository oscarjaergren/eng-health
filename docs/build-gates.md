# Build gates

**Read this if:** a gate is blocking you, you want to relax or add one, or you wonder why the
build is this strict.

The point is a signal an agent can act on: a build that passes with forty warnings doesn't say
whether the work is done.

## What is enforced

Python (`pyproject.toml`):

- ruff with a curated rule set, including blind `except`, security, naive datetimes, unused
  arguments and commented-out code. Streamlit and plotly are banned outside
  `eng_health/dashboard/`.
- mypy `strict` with `warn_unreachable`, over the package and the tests.
- pytest turns every warning into an error, so a deprecation fails before an upgrade breaks.
- vulture reports unused code; deptry reports unused and undeclared dependencies.

Rust (`sync/Cargo.toml`, `sync/deny.toml`):

- clippy `pedantic`, warnings as errors; no bare `unwrap()` outside tests; suppressions are
  `#[expect]` with a reason, so a stale one fails.
- The modules are private and `lib.rs` re-exports the crate's surface, so `dead_code` sees every
  unused item. A `pub mod` would hide them: rustc never reports a library's public item as dead.
- `cargo doc` with warnings as errors, private items included.
- cargo-shear (unused dependencies) and cargo-deny (advisories, licences, sources, no wildcard
  versions).

The image (`scripts/image-check.sh`): it answers its health check, runs as non-root, can run the
engine and load the schema, has no dev dependencies, and stays under a size ceiling.

CI adds: a full-history secret scan, pip-audit against the lock, CodeQL (Python, Rust, the
workflows), dependency review, conventional PR titles, and mutation testing of changed Rust.

## Tests that check other tests

Coverage is reported, not gated: a test that runs code without checking it still counts.

- **Mutation testing** (cargo-mutants) changes the Rust a PR touches, such as `*` to `+`, and
  fails if no test notices. It found a test that never pinned the boundary it was written for.
- **Property tests**: Hypothesis compares the flaky-job and flaky-test metrics with a plain-Python
  reading of their definitions on random runs; proptest feeds the artifact parsers arbitrary
  input. Hypothesis found a crash for selections with no failures.

Python isn't mutation tested: mutmut copies only part of the project, and the property tests are
the stronger check for the metric modules.

## Relaxing a gate

Assume the code is wrong before the rule is. A suppression is legitimate only when the rule
can't be satisfied here, for a reason that is written down next to it: in `pyproject.toml`
(`per-file-ignores`, `ignore_names`) or as `#[expect(lint, reason = "...")]`. Never relax a gate
to get one build through; change it on purpose, in its own commit.

## Adding a gate

Put it where the tool reads its config, give it a pre-push hook or a CI step (see
[linting-and-hooks.md](linting-and-hooks.md)), then introduce a violation, watch it fail, and
revert. An unverified gate is decoration.
