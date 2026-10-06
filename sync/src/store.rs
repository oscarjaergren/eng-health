//! SQLite storage shared with the Python dashboard (`pr_analytics/store.py`).

use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::time::Duration;

use chrono::{DateTime, Utc};
use rusqlite::{Connection, OptionalExtension, params};

use crate::model::{Platform, PullRequest, Timestamp};
use crate::pipelines::Job;

/// Shared with `pr_analytics/store.py`. Bump both together when the tables or
/// the PR JSON change shape.
pub const SCHEMA_VERSION: i64 = 1;

const SCHEMA: &str = "
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
CREATE TABLE IF NOT EXISTS sync_state (
    platform TEXT PRIMARY KEY,
    last_sync TEXT,
    last_attempt TEXT,
    last_error TEXT
);
";

#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    #[error(
        "{path} uses schema version {found}, but prsync understands {SCHEMA_VERSION}. Update prsync."
    )]
    NewerSchema { path: String, found: i64 },
    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("could not encode pull request {key}: {source}")]
    Encode {
        key: String,
        source: serde_json::Error,
    },
    #[error("stored pull request {key} is not valid: {source}")]
    BadRecord {
        key: String,
        source: serde_json::Error,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct SyncState {
    pub last_sync: Option<DateTime<Utc>>,
    pub last_attempt: Option<DateTime<Utc>>,
    pub last_error: Option<String>,
}

pub struct Store {
    conn: Connection,
}

impl Store {
    pub fn open(path: &Path) -> Result<Self, StoreError> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let conn = Connection::open(path)?;
        conn.busy_timeout(Duration::from_secs(30))?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        let found: i64 = conn.pragma_query_value(None, "user_version", |r| r.get(0))?;
        if found > SCHEMA_VERSION {
            return Err(StoreError::NewerSchema {
                path: path.display().to_string(),
                found,
            });
        }
        conn.execute_batch(SCHEMA)?;
        conn.pragma_update(None, "user_version", SCHEMA_VERSION)?;
        Ok(Self { conn })
    }

    /// Insert or replace pull requests, and record display names.
    pub fn upsert(
        &mut self,
        prs: &[PullRequest],
        people: &BTreeMap<String, String>,
    ) -> Result<usize, StoreError> {
        let tx = self.conn.transaction()?;
        {
            let mut put = tx.prepare_cached(
                "INSERT INTO pull_requests (key, platform, data) VALUES (?1, ?2, ?3) \
                 ON CONFLICT(key) DO UPDATE SET data = excluded.data",
            )?;
            for pr in prs {
                let data = serde_json::to_string(pr).map_err(|source| StoreError::Encode {
                    key: pr.key(),
                    source,
                })?;
                put.execute(params![pr.key(), pr.platform.as_str(), data])?;
            }
            let mut name = tx.prepare_cached(
                "INSERT INTO people (id, name) VALUES (?1, ?2) ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            )?;
            for (id, display) in people {
                name.execute(params![id, display])?;
            }
            bump(&tx)?;
        }
        tx.commit()?;
        Ok(prs.len())
    }

    pub fn pull_requests(
        &self,
        platform: Option<Platform>,
    ) -> Result<Vec<PullRequest>, StoreError> {
        let mut stmt = self
            .conn
            .prepare("SELECT key, data FROM pull_requests WHERE ?1 IS NULL OR platform = ?1")?;
        let rows = stmt.query_map([platform.map(Platform::as_str)], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        rows.map(|row| {
            let (key, data) = row?;
            serde_json::from_str(&data).map_err(|source| StoreError::BadRecord { key, source })
        })
        .collect()
    }

    /// `key` is a platform (`github`) or platform and module (`github:pipelines`).
    pub fn sync_state(&self, key: &str) -> Result<SyncState, StoreError> {
        let row: Option<(Option<String>, Option<String>, Option<String>)> = self
            .conn
            .query_row(
                "SELECT last_sync, last_attempt, last_error FROM sync_state WHERE platform = ?1",
                [key],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()?;
        let Some((last_sync, last_attempt, last_error)) = row else {
            return Ok(SyncState::default());
        };
        let parse = |s: Option<String>| {
            s.and_then(|s| DateTime::parse_from_rfc3339(&s).ok())
                .map(|t| t.with_timezone(&Utc))
        };
        Ok(SyncState {
            last_sync: parse(last_sync),
            last_attempt: parse(last_attempt),
            last_error,
        })
    }

    /// Record a sync attempt. `last_sync` only moves when the attempt succeeded,
    /// so a failed repository is re-read next time.
    pub fn record_sync(
        &mut self,
        key: &str,
        attempted: DateTime<Utc>,
        succeeded: bool,
        error: Option<&str>,
    ) -> Result<(), StoreError> {
        let at = Timestamp::new(attempted).to_string();
        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO sync_state (platform, last_sync, last_attempt, last_error) VALUES (?1, ?2, ?3, ?4) \
             ON CONFLICT(platform) DO UPDATE SET \
             last_sync = COALESCE(excluded.last_sync, sync_state.last_sync), \
             last_attempt = excluded.last_attempt, last_error = excluded.last_error",
            params![key, succeeded.then_some(&at), at, error],
        )?;
        bump(&tx)?;
        tx.commit()?;
        Ok(())
    }

    pub fn clear(&mut self) -> Result<(), StoreError> {
        let tx = self.conn.transaction()?;
        tx.execute_batch("DELETE FROM pull_requests; DELETE FROM people; DELETE FROM sync_state;")?;
        bump(&tx)?;
        tx.commit()?;
        Ok(())
    }
}

impl Store {
    pub fn upsert_jobs(&mut self, jobs: &[Job]) -> Result<usize, StoreError> {
        let tx = self.conn.transaction()?;
        {
            let mut put = tx.prepare_cached(
                "INSERT OR REPLACE INTO pipeline_jobs VALUES \
                 (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
            )?;
            for j in jobs {
                put.execute(params![
                    j.key,
                    j.repo_id,
                    j.repository,
                    j.pipeline,
                    j.run_id,
                    j.attempt,
                    j.branch,
                    j.is_default_branch,
                    j.commit_sha,
                    j.name,
                    j.conclusion,
                    j.started_at.map(|t| t.to_string()),
                    j.finished_at.map(|t| t.to_string()),
                    j.url,
                ])?;
            }
            bump(&tx)?;
        }
        tx.commit()?;
        Ok(jobs.len())
    }

    /// Highest stored attempt per run, so a rerun is fetched but nothing else is.
    pub fn run_attempts(&self, repo_id: &str) -> Result<HashMap<i64, i64>, StoreError> {
        let mut stmt = self.conn.prepare(
            "SELECT run_id, MAX(attempt) FROM pipeline_jobs WHERE repo_id = ?1 GROUP BY run_id",
        )?;
        let rows = stmt.query_map([repo_id], |r| Ok((r.get(0)?, r.get(1)?)))?;
        Ok(rows.collect::<Result<_, _>>()?)
    }

    pub fn prune_jobs(&mut self, before: DateTime<Utc>) -> Result<(), StoreError> {
        let tx = self.conn.transaction()?;
        tx.execute(
            "DELETE FROM pipeline_jobs WHERE started_at < ?1",
            [Timestamp::new(before).to_string()],
        )?;
        bump(&tx)?;
        tx.commit()?;
        Ok(())
    }
}

fn bump(tx: &rusqlite::Transaction<'_>) -> rusqlite::Result<()> {
    tx.execute("UPDATE meta SET revision = revision + 1", [])
        .map(|_| ())
}
