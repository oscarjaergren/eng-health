# PR Analytics

A Streamlit dashboard for pull request flow and code review across Azure DevOps and GitHub.
It shows how long PRs take to get reviewed and merged, which PRs are waiting, and who is
doing the reviewing.

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

Syncing is done by `prsync`, a Rust program in `sync/` that the image includes. Synced
PRs are kept in a SQLite database under `./data`. Later syncs fetch only what changed,
so they are quick. To sync on a schedule, run the CLI from cron.

Without Docker you need Python 3.12 and a Rust toolchain:

```bash
cargo build --release --manifest-path sync/Cargo.toml   # the dashboard finds it there
sync/target/release/prsync sync                          # or press Sync now in the dashboard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run dashboard_main.py
```

`prsync status` shows when each platform last synced. `python main.py export prs.csv`
writes every stored PR to a CSV file.

## Configuration

| Variable | |
|---|---|
| `AZURE_DEVOPS_ORGANIZATION`, `AZURE_DEVOPS_PAT` | Azure DevOps organisation and a PAT with Code (Read) scope. Every project is read. |
| `GITHUB_OWNER`, `GITHUB_TOKEN`, `GITHUB_TYPE` | GitHub organisation or user (`org` or `user`) and a token that can read its repositories. |
| `DATA_DIR` | Where the database lives. Default `data`. |
| `MAX_PARALLEL_WORKERS` | Concurrent API requests. Default 8. |
| `IDENTITY_ALIASES` | Merge one person's identities, e.g. `jdoe=jane.doe@example.com,jd2=jane.doe@example.com`. |
| `MOCK_MODE` | `true` shows sample data even when credentials are set. |
| `GITHUB_API_URL`, `AZURE_DEVOPS_URL` | GitHub Enterprise Server or Azure DevOps Server addresses. |
| `PRSYNC_BIN` | Path to `prsync`, if it is neither on `PATH` nor in `sync/target/release`. |

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

Filters are kept in the page URL, so a filtered view can be shared as a link. Dates and
times are shown in your browser's time zone.

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && mypy && pytest
cd sync && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

- `sync/` is `prsync`: GitHub over GraphQL (a page of PRs arrives with its reviews and
  comments), Azure DevOps over REST, and the incremental sync into SQLite.
- `pr_analytics/` is the dashboard: `store.py` reads the database, `metrics.py` holds
  the calculations behind every chart (without Streamlit), `dashboard/` has one module per
  tab, `prsync.py` runs the sync engine, and `mock.py` makes the sample data.
- The two sides share the database schema (versioned with `PRAGMA user_version`) and the
  PR record format. `testdata/` pins that format: raw API payloads with the records they
  must produce. After an intended rule change, `UPDATE_GOLDENS=1 cargo test` rewrites
  the expected files; review the diff.
