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

Synced PRs are kept in a SQLite database under `./data`. Later syncs fetch only what
changed, so they are quick. To sync on a schedule, run the CLI from cron.

Without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py sync
streamlit run dashboard_main.py
```

`python main.py export prs.csv` writes every stored PR to a CSV file.

## Configuration

| Variable | |
|---|---|
| `AZURE_DEVOPS_ORGANIZATION`, `AZURE_DEVOPS_PAT` | Azure DevOps organisation and a PAT with Code (Read) scope. Every project is read. |
| `GITHUB_OWNER`, `GITHUB_TOKEN`, `GITHUB_TYPE` | GitHub organisation or user (`org` or `user`) and a token that can read its repositories. |
| `DATA_DIR` | Where the database lives. Default `data`. |
| `MAX_PARALLEL_WORKERS` | Concurrent API requests. Default 8. |
| `IDENTITY_ALIASES` | Merge one person's identities, e.g. `jdoe=jane.doe@example.com,jd2=jane.doe@example.com`. |
| `MOCK_MODE` | `true` shows sample data even when credentials are set. |

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
```

`pr_analytics/` is laid out as:

- `clients/`: Azure DevOps and GitHub API access
- `processing.py`: raw API data to `PullRequest` records
- `sync.py` and `store.py`: incremental sync into SQLite
- `metrics.py`: the calculations behind every chart, without Streamlit
- `dashboard/`: the Streamlit app, one module per tab
- `mock.py`: sample data, built from fake API payloads so it runs through the real processing

`sync/` is the Rust sync engine (`prsync`) that is replacing the Python sync. It
writes the same database. `testdata/` holds shared fixtures: raw API payloads and
the expected records, generated from the Python code with
`python -m tests.export_goldens`. Both test suites check against them.

```bash
cd sync && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

`prsync` syncs both platforms (GitHub over GraphQL, Azure DevOps over REST).
The Python sync still exists until the dashboard switches over:

```bash
cd sync && cargo run --release -- sync      # or: sync --full, sync --reset, status
```

It reads the same `.env`. `GITHUB_API_URL` and `AZURE_DEVOPS_URL` point it at
GitHub Enterprise Server or Azure DevOps Server.
