# eng-health

A Streamlit dashboard for engineering health across Azure DevOps and GitHub. It opens on
**This week**: the headline numbers for pull requests and CI against the week before, and
what moved most, such as a workflow that got slower or a test that started failing
intermittently.

The **Pull requests** view shows how long PRs take to get reviewed and merged, how big they
are, which are waiting, and who is doing the reviewing. The **Pipelines** view covers GitHub
Actions: failure rate, slow workflows, CI minutes and their cost, time lost to reruns, and
flaky jobs and tests.

## Try it with sample data

```bash
docker compose up dashboard
```

With no credentials in `.env` the dashboard shows generated sample data. Open
<http://localhost:8501>.

## Use your own data

1. Copy `.env.example` to `.env` and fill in Azure DevOps, GitHub, or both.
2. Start the dashboard with `docker compose up -d dashboard` and press **Sync now**, or
   sync from the command line with `docker compose run --rm cli sync`.

Syncing is done by the `eng-health` command, a Rust program in `sync/` that the image
includes. Synced PRs are kept in a SQLite database under `./data`. Later syncs fetch only
what changed, so they are quick. To sync on a schedule, run the CLI from cron.

Without Docker you need [mise](https://mise.jdx.dev/getting-started.html), which installs
the pinned Python, Rust and tools:

```bash
mise run setup   # once: pinned tools, Python packages and git hooks
mise run sync    # build the sync engine and sync; or press Sync now in the dashboard
mise run dev     # the dashboard, on http://localhost:8501
```

`sync/target/release/eng-health status` shows when each platform last synced. `uv run main.py export prs.csv`
writes every stored PR to a CSV file.

## Configuration

| Variable                                        |                                                                                                                                 |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `AZURE_DEVOPS_ORGANIZATION`, `AZURE_DEVOPS_PAT` | Azure DevOps organisation and a PAT with Code (Read) scope. Every project is read.                                              |
| `GITHUB_OWNER`, `GITHUB_TOKEN`, `GITHUB_TYPE`   | GitHub organisation or user (`org` or `user`) and a token that can read its repositories.                                       |
| `DATA_DIR`                                      | Where the database lives. Default `data`.                                                                                       |
| `MAX_PARALLEL_WORKERS`                          | Concurrent API requests. Default 8.                                                                                             |
| `IDENTITY_ALIASES`                              | Merge one person's identities, e.g. `jdoe=jane.doe@example.com,jd2=jane.doe@example.com`.                                       |
| `MOCK_MODE`                                     | `true` shows sample data even when credentials are set.                                                                         |
| `GITHUB_API_URL`, `AZURE_DEVOPS_URL`            | GitHub Enterprise Server or Azure DevOps Server addresses.                                                                      |
| `LOG_LEVEL`                                     | Dashboard log level (`DEBUG`, `INFO`, `WARNING`). Default `INFO`. The log also includes `eng-health`'s output after each sync.  |
| `RUST_LOG`                                      | `eng-health` log level, e.g. `eng_health=debug` to log every API request with its status and time. Default `info`.              |
| `ENG_HEALTH_BIN`                                | Path to `eng-health`, if it is neither on `PATH` nor in `sync/target/release`.                                                  |
| `CI_MINUTE_PRICES`                              | Dollars per CI minute by runner, e.g. `linux=0.006,windows=0.010,macos=0.062`. Defaults to GitHub's list prices (October 2026). |

Setting only half of a platform's pair is reported as an error rather than ignored.

## What is counted

- **Time to merge**: from opening a PR to merging it. Shown as the median.
- **Time to review**: from opening a PR to the first comment, vote or review by anyone other
  than the author.
- **Approvals**: anyone who approved at any point. On Azure DevOps this includes votes that
  were reset by later pushes.
- **Comments**: text comments by people. System messages and bots are left out, and so are
  authors' replies on their own PRs unless you switch that on.
- **Infrastructure PRs**: titles that mention Terraform, Helm, Bicep, Kubernetes and similar
  are hidden by default. A sidebar toggle brings them back.
- **PR size**: lines added plus lines deleted, leaving out lock files, generated and minified
  code, snapshots and vendored folders (the list is `is_noise` in `sync/src/rules.rs`). Sizes
  are bucketed XS (≤10 lines), S (≤100), M (≤400), L (≤1000) and XL. A PR with more than 100
  changed files counts everything GitHub reports. GitHub only for now; Azure DevOps reports no
  line counts in its PR API.
- **Comments per 100 lines**: comments from people other than the author, per 100 changed
  lines. Low on big PRs means they are skimmed rather than read.

Filters are kept in the page URL, so a filtered view can be shared as a link. Dates and
times are shown in your browser's time zone.

This week compares the last 7 days with the 7 before. A workflow is listed under "What
moved" when its median run time or its CI minutes change by 20% or more, with at least 3 runs
or 30 minutes in each week; a test is listed the first week it fails and then passes on the
same commit.

Pipelines (GitHub Actions, last 90 days):

- **Failure rate**: finished runs on the default branch whose final attempt failed.
  Cancelled runs are left out.
- **Run time**: median and 90th percentile of successful runs, per workflow and job.
- **Lost to reruns**: time spent in attempts that were then re-run.
- **CI minutes**: every attempt of every job on every branch, each rounded up to a whole minute,
  as GitHub bills them. The runner (Linux, Windows, macOS, self-hosted) comes from the job's
  labels. **Estimated cost** uses list prices (`CI_MINUTE_PRICES`) before any minutes your
  plan includes; public repositories and self-hosted runners count as free.
- **Flaky job**: a job that failed, then passed when the same run was re-run.
- **Flaky test**: a test that failed in a run that then passed on the same commit (a
  rerun, or another run of the workflow). Test results come from JUnit or TRX files in
  artifacts whose name contains `test`, `junit`, `trx` or `result`, and are only fetched
  for runs where a job failed.

`eng-health sync --only prs` or `--only pipelines` syncs one of the two.

## Development

```bash
mise run check    # everything CI checks: lint, types, clippy, tests
mise run format   # fix formatting; the git hooks only verify it
```

`mise tasks` lists every command. Commit messages are conventional commits (`feat:`,
`fix:`), checked by a git hook. [AGENTS.md](AGENTS.md) has the rules and the traps, for
people and coding agents alike; [docs/](docs/build-gates.md) explains the gates.

In VS Code, F5 starts the dashboard with the debugger attached. With Flatpak VS Code it
runs on the host, because pyarrow crashes inside the Flatpak sandbox.

- `sync/` is the `eng-health` command: GitHub over GraphQL (a page of PRs arrives with its
  reviews and comments), Azure DevOps over REST, and the incremental sync into SQLite.
- `eng_health/` is the dashboard: `store.py` reads the database, `metrics.py` holds
  the calculations behind every chart (without Streamlit), `dashboard/` has one module per
  tab, `sync.py` runs the sync engine, and `mock.py` makes the sample data.
- The two sides share the database schema, `sync/schema.sql`, which both run on open
  (versioned with `PRAGMA user_version`), and the PR record format. `testdata/` pins that
  format: raw API payloads with the records they must produce. After an intended rule
  change, `UPDATE_GOLDENS=1 cargo test` rewrites the expected files; review the diff.
