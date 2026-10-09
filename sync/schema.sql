-- The database schema, shared by the sync engine (sync/src/store.rs), which writes, and the
-- dashboard (eng_health/store.py), which reads. Both run this whole file when they open the
-- database, so every statement must be safe to repeat.
--
-- Raise user_version when the tables or the PR JSON in pull_requests.data change shape.
-- Each side refuses a database whose version is newer than the one it was built with. Only the
-- engine sets it: on an older database it re-syncs everything, so old records gain new fields.
--
-- 2: PR size (additions, deletions, changed_files).

CREATE TABLE IF NOT EXISTS pull_requests (
    key TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL
);
INSERT OR IGNORE INTO meta (id, revision) VALUES (1, 0);
CREATE TABLE IF NOT EXISTS pipeline_jobs (
    key TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    pipeline TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    branch TEXT NOT NULL,
    is_default_branch INTEGER NOT NULL,
    commit_sha TEXT NOT NULL,
    name TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    url TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pipeline_jobs_run ON pipeline_jobs (repo_id, run_id);
CREATE TABLE IF NOT EXISTS test_failures (
    repo_id TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    test_id TEXT NOT NULL,
    PRIMARY KEY (repo_id, run_id, test_id)
);
CREATE TABLE IF NOT EXISTS sync_state (
    platform TEXT PRIMARY KEY,
    last_sync TEXT,
    last_attempt TEXT,
    last_error TEXT
);
PRAGMA user_version = 2;
