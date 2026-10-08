# AGENTS.md

Instructions for coding agents, read natively by most of them, including Claude Code.

eng-health is a Streamlit dashboard (Python, `eng_health/`) over a SQLite database that a Rust
sync engine (`sync/`, the `eng-health` command) fills from GitHub and Azure DevOps: pull requests
and reviews, and GitHub Actions runs for CI health.

## Commands

`mise tasks` lists every command; `mise run <task>` runs one, from the repo root.

- `mise run setup` once, then `mise run check` before pushing: what CI checks.
- `mise run test`, `mise run format` (the git hooks only verify formatting).
- `mise run dev` starts the dashboard; with no credentials in `.env` it shows sample data.
- `mise run sync` builds the engine and syncs; arguments pass through, e.g. `--only pipelines`.
- `mise run image`, then `mise run image-check`; `mise run mutate` mutation-tests changed Rust.

## Layout

```
eng_health/          the dashboard: store.py reads, metrics.py and pipelines.py compute
eng_health/dashboard/  the only code that draws (Streamlit, plotly)
eng_health/mock.py   sample data, shown when no credentials are set
sync/                the eng-health command: sources, sync rules, store
sync/schema.sql      the database schema; the engine and the dashboard both run it on open
testdata/            API payloads and the records they must produce
tests/               Python tests; seed.py writes the database the way the engine does
```

## Rules

- **The engine is the only writer.** The dashboard reads; Python tests write through
  `tests/seed.py`.
- **`sync/schema.sql` is the contract.** Changing a table means raising `user_version` there and
  `SCHEMA_VERSION` in `sync/src/store.rs` (a test checks they match), and the sample data must
  still fit (`test_sample_data_fits_the_schema`).
- **Streamlit and plotly stay in `eng_health/dashboard/`**, so the metrics are testable without a
  UI. ruff enforces it (`TID251`).
- **The Rust library's surface is the re-export list in `sync/src/lib.rs`.** Everything else is
  `pub(crate)`, so rustc reports dead code. Export only what `main.rs` or a test needs.
- **Warnings are errors**: pytest, mypy strict, clippy pedantic, rustdoc. Suppress narrowly with a
  reason: per file in `pyproject.toml`, `#[expect(lint, reason = "...")]` in Rust. Never weaken a
  gate to pass. [build-gates.md](docs/build-gates.md)
- **Expected failures are returned as errors.** A Rust panic is for a broken invariant and says
  which, `expect("why this can't fail")`; no bare `unwrap()` outside tests.
- **Commits and PR titles are conventional commits** (`feat:`, `fix:`, `build:`, `ci:`, `docs:`,
  `refactor:`, `test:`, `chore:`). PRs are squash-merged, so the title is the commit on `main`.

## Traps

Each of these fails silently, cryptically, or only on someone else's machine.

- **Flatpak VS Code: pyarrow segfaults inside the sandbox** (its OpenSSL clashes with the
  interpreter's). F5 runs the dashboard on the host through `flatpak-spawn --host`; don't start it
  inside the sandbox.
- **GitHub's jobs endpoint needs `filter=all`**, or only the latest attempt comes back, and reruns
  and flaky jobs disappear.
- **The goldens in `testdata/expected` are rewritten, not edited**: `UPDATE_GOLDENS=1 cargo test`
  in `sync/` after an intended rule change, then read the diff.
- **Python 3.14 syntax is used**, such as `except A, B:` without parentheses (PEP 758). Older
  interpreters fail to parse it.
- **After changing `[tools]` in `.config/mise.toml`, run `mise lock --platform linux-x64`.** CI
  installs with `--locked` and fails on a tool without a recorded download URL.
- **actionlint skips its shell checks when shellcheck is missing.** Run hooks through mise, which
  has it pinned.
- **pandas joins on an empty frame can change the index.** Merge on columns; `flaky_jobs` crashed
  for selections with no failures this way.
- **`mise run mutate` edits `sync/src` in place** (the tests read `../testdata`, which a copy
  lacks). If it is interrupted, `git diff sync/src` shows any mutant left behind.
- **A `CLAUDE.md` in the repo replaces this file for Claude Code** unless it imports `@AGENTS.md`;
  a hook rejects one without the import.

## Docs

Open a page only when its trigger matches.

| If you're…                                         | Read                                                   |
| -------------------------------------------------- | ------------------------------------------------------ |
| blocked by a gate, or adding or relaxing one       | [docs/build-gates.md](docs/build-gates.md)             |
| blocked by a git hook, or setting up a fresh clone | [docs/linting-and-hooks.md](docs/linting-and-hooks.md) |
| looking for configuration or what a metric counts  | [README.md](README.md)                                 |
