# Linting and git hooks

**Read this if:** a hook blocked your commit or push, you want to add a check, or you are
setting up a fresh clone.

## Setup

```bash
mise run setup   # pinned tools, the Python packages, then the git hooks
```

Without it a clone has no hooks, and nothing tells you.

## What runs when

| Stage      | Checks                                                                                                                                                      |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pre-commit | gitleaks, typos, editorconfig-checker, actionlint, zizmor, shellcheck, hadolint, dprint, ruff, `cargo fmt`, the uv lock, file hygiene, the CLAUDE.md import |
| commit-msg | conventional commit format                                                                                                                                  |
| pre-push   | mypy, vulture, deptry, clippy, `cargo doc`, cargo-shear, the tests, lychee                                                                                  |

The commit hook stays fast because a slow one gets bypassed with `--no-verify`; anything that
type-checks or builds runs on pre-push.

Secrets are scanned twice: the commit hook scans the staged diff, which stops a secret before it
enters history, and CI scans the full history, because a secret committed and later deleted
still needs rotating. Reviewed false positives go in `.gitleaksignore`.

## Fix at edit time, verify at commit time

Hooks only verify; they never rewrite files, so a commit never contains content its author
didn't see. `scripts/format.sh` is the one thing that formats, and Claude Code runs it after
every edit (`.claude/settings.json`).

```bash
mise run format                  # whole repo
mise run format path/to/file     # specific files
```

## Running checks yourself

```bash
mise run lint                    # the commit stage, exactly as CI runs it
prek run <hook-id> --all-files   # one check
mise run check                   # everything CI's main jobs check
```

## Nothing fails silently

- Tools run through `mise exec` or `uv run --locked`, so a missing tool fails the hook instead of
  falling back to whatever is on `PATH`.
- CI uses the same mise version and installs with `--locked`.
- `fail_fast` is off, so one run reports every failure.

## Every pre-push hook needs a CI counterpart

`git push --no-verify` skips pre-push, and `prek run --all-files` only runs the commit stage, so
each pre-push hook also runs in CI: mypy, vulture, deptry and the tests in the `check` job,
clippy, `cargo doc` and cargo-shear in `rust`, and lychee in `lint`. Add a pre-push hook and its
CI step in the same commit, or the check is advisory. The commit-msg hook's counterpart is the
PR-title check, since squash merging makes the title the commit on `main`.

## Left out on purpose

- **editorconfig-checker's `IndentSize`**: it rejects aligned continuation lines that the
  formatters accept.
- **markdownlint**: dprint formats Markdown, and lychee catches broken links, the failure that
  matters.
