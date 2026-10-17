# eng-health

A Streamlit dashboard for engineering health across Azure DevOps and GitHub. It opens on
**Today**: the headline numbers against the period before, and an inbox of what needs a look,
such as PRs waiting on review, a test that started failing intermittently or a workflow that
got slower.

Each number opens a view that answers one question. **Shipping**: are we shipping? **Review**:
is review the bottleneck? **CI**: is CI slowing us down? **Cost**: what is it costing?
**People**: who is doing what? The period (7, 30 or 90 days, or 12 months) and the filters
apply to every view.

## Try it with sample data

```bash
docker compose up dashboard
```

With no credentials in `.env` the dashboard shows generated sample data. Open
<http://localhost:8501>.

## Use your own data

**Connect with your CLI logins** (no tokens to create). Sign in with `gh auth login` and/or
`az login`, start the dashboard with `mise run dev` (below), open **Settings** (the gear in
the top bar), pick an account or organisation and press **Sync now**. Nothing secret is saved: the choice
goes in `connections.json` in the data folder, and each sync asks `gh` or `az` for a fresh
token. `mise run sync` uses the same connections.

**Or use tokens in `.env`**, which also works in Docker, where there is no `gh` or `az`:

1. Copy `.env.example` to `.env` and fill in Azure DevOps, GitHub, or both. `.env` takes
   precedence over a connection.
2. Start the dashboard with `docker compose up -d dashboard` and press **Sync now**, or
   sync from the command line with `docker compose run --rm cli sync`.

Syncing is done by the `eng-health` command, a Rust program in `sync/` that the image
includes. Synced PRs are kept in a SQLite database under `./data`. A sync reads two years
back, the dashboard's 12 months and the 12 they are compared with; later syncs fetch only what
changed, so they are quick. On a large organisation the first sync can run out of API budget: it
reads every repository's last 90 days before older history, keeps each page as it arrives, and
the next sync continues where it stopped. To sync on a schedule, run the CLI from cron.

Without Docker you need [mise](https://mise.jdx.dev/getting-started.html), which installs
the pinned Python, Rust and tools:

```bash
mise run setup   # once: pinned tools, Python packages and git hooks
mise run sync    # build the sync engine and sync; or press Sync now in the dashboard
mise run dev     # the dashboard, on http://localhost:8501
```

`sync/target/release/eng-health status` shows when each platform last synced.

## Configuration

| Variable                                        |                                                                                                                                 |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `AZURE_DEVOPS_ORGANIZATION`, `AZURE_DEVOPS_PAT` | Azure DevOps organisation and a PAT with Code (Read) scope, and Project and Team (Read) for teams. Every project is read.       |
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

- **Time to merge**: from a PR being ready for review to merging it. Shown as the median.
- **Time to review**: from a PR being ready for review to the first comment, vote or review by
  anyone other than the author.
- **Ready for review**: when the PR opened, or for a GitHub draft, when it was marked ready, so
  time spent as a draft doesn't count. Azure DevOps doesn't say when a draft was published.
- **Approvals**: anyone who approved at any point. On Azure DevOps this includes votes that
  were reset by later pushes.
- **Comments**: text comments by people. System messages and bots are left out, and so are
  authors' replies on their own PRs unless you switch that on.
- **Mine**: repositories where, in the last 90 days, you opened a PR or first commented on,
  reviewed or voted on someone else's, plus any where you still have a PR open. "You" are whoever
  the GitHub or Azure DevOps credentials belong to; `IDENTITY_ALIASES` joins the two. The
  dashboard opens on Mine when it knows who you are, and then on whichever scope you picked last
  (kept in `dashboard.json` in the data folder).
- **Teams**: the scope switcher also lists the teams GitHub and Azure DevOps already have, yours
  first, with nothing to set up. A GitHub team covers the repositories it owns; an Azure DevOps
  team, which owns none, covers where its members work, the way Mine does. Reading teams takes
  `read:org` on GitHub (the gh CLI has it) and Project and Team (Read) on Azure DevOps; without
  it there are no teams to pick, and everything else works as before.
- **Repository pages**: click a repository's name in any table for the same view about just
  that repository. The ✕ next to its name goes back.
- **Repositories**: archived repositories and forks are left out unless you pick them in the
  Repository filter, which lists the busiest first and searches as you type. Two repositories with
  the same name, in different Azure DevOps projects or on both platforms, are shown as
  `project/name` and never counted together.
- **Infrastructure PRs**: titles that mention Terraform, Helm, Bicep, Kubernetes and similar
  are hidden by default, and so are Dependabot and Renovate PRs. Toggles in the filter bar
  bring them back.
- **PR size**: lines added plus lines deleted, leaving out lock files, generated and minified
  code, snapshots and vendored folders (the list is `is_noise` in `sync/src/rules.rs`). Sizes
  are bucketed XS (≤10 lines), S (≤100), M (≤400), L (≤1000) and XL. A PR with more than 100
  changed files counts everything GitHub reports. GitHub only for now; Azure DevOps reports no
  line counts in its PR API.
- **Comments per 100 lines**: comments from people other than the author, per 100 changed
  lines. Low on big PRs means they are skimmed rather than read.

Filters are kept in the page URL, so a filtered view can be shared as a link. Dates and
times are shown in your browser's time zone.

Every number covers the period you pick and compares it with the one before; charts split it
into days, weeks or months. Today lists open PRs that have waited 2 days or more, tests that
became flaky in the period, and workflows whose median run time or CI minutes changed by 20% or
more, with at least 3 runs or 30 minutes in each period. ✓ marks an item handled for the rest
of the browser session.

CI and Cost (GitHub Actions, last 90 days). Workflows and jobs only compare within one
repository, so with several these views compare repositories; pick one (or click its name) for
its workflows and jobs.

- **Failure rate**: finished runs on the default branch whose final attempt failed.
  Cancelled runs are left out.
- **Broken main**: from a workflow failing on the default branch to its next passing run,
  with a repository's workflows' overlapping stretches merged. GitHub's own workflows
  (Dependabot, default CodeQL) are left out: theirs failing doesn't mean the code is broken.
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
  the calculations behind every chart (without Streamlit), `dashboard/views.py` draws the six
  views, `sync.py` runs the sync engine, and `mock.py` makes the sample data.
- The two sides share the database schema, `sync/schema.sql`, which both run on open
  (versioned with `PRAGMA user_version`), and the PR record format. `testdata/` pins that
  format: raw API payloads with the records they must produce. After an intended rule
  change, `UPDATE_GOLDENS=1 cargo test` rewrites the expected files; review the diff.
