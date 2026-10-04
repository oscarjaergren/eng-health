//! Reads changed pull requests from a source into the store.
//!
//! Start an hour before the last successful sync, skip PRs whose stored copy
//! is still accurate, save in batches, and only move the window forward when
//! every repository was read.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use chrono::{Duration, Utc};
use futures::{StreamExt, stream};
use serde::Serialize;

use crate::model::{Platform, PullRequest, Repo};
use crate::source::{People, Source, SourceError};
use crate::store::{Store, StoreError};

/// Re-read a little before the last sync so PRs that changed while it ran are not missed.
pub const OVERLAP: Duration = Duration::hours(1);
const BATCH: usize = 50;

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Report {
    pub platform: String,
    pub repositories: usize,
    pub listed: usize,
    pub saved: usize,
    pub incomplete: usize,
    pub requests: u64,
    pub interrupted: bool,
    pub errors: Vec<String>,
}

impl Report {
    #[must_use]
    pub fn ok(&self) -> bool {
        self.errors.is_empty() && !self.interrupted
    }
}

/// Emitted as the sync runs; `prsync --progress json` prints one per line.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Event {
    Progress {
        platform: String,
        fraction: f64,
        message: String,
    },
    Report(Report),
}

#[derive(Debug, thiserror::Error)]
pub enum SyncError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error("database task failed: {0}")]
    Join(String),
}

pub struct Options<'a> {
    pub full: bool,
    pub workers: usize,
    /// Set from another task (Ctrl-C) to stop after the current batch.
    pub stop: Arc<AtomicBool>,
    pub on_event: &'a (dyn Fn(Event) + Sync),
}

type Shared = Arc<Mutex<Store>>;

async fn db<T: Send + 'static>(
    store: &Shared,
    f: impl FnOnce(&mut Store) -> Result<T, StoreError> + Send + 'static,
) -> Result<T, SyncError> {
    let store = Arc::clone(store);
    tokio::task::spawn_blocking(move || f(&mut store.lock().expect("store lock")))
        .await
        .map_err(|e| SyncError::Join(e.to_string()))?
        .map_err(SyncError::from)
}

fn key(platform: Platform, repo: &Repo, number: i64) -> String {
    format!("{platform}:{}:{number}", repo.id)
}

/// Sync one platform. Source problems end up in the report; only database
/// failures are returned as errors.
pub async fn sync_platform<S: Source>(
    source: &S,
    store: &Shared,
    opts: &Options<'_>,
) -> Result<Report, SyncError> {
    let platform = source.platform();
    let mut report = Report {
        platform: platform.to_string(),
        ..Report::default()
    };
    let started = Utc::now();
    let state = db(store, move |s| s.sync_state(platform)).await?;
    let since = if opts.full {
        None
    } else {
        state.last_sync.map(|t| t - OVERLAP)
    };
    let say = |fraction: f64, message: String| {
        (opts.on_event)(Event::Progress {
            platform: platform.to_string(),
            fraction,
            message,
        });
    };

    let outcome = run(source, store, opts, since, &mut report, &say).await;
    if let Err(e) = outcome? {
        report.errors.push(e.to_string());
    }
    if opts.stop.load(Ordering::Relaxed) {
        report.interrupted = true;
    }
    report.requests = source.requests();

    let error = if report.interrupted {
        Some("interrupted".to_owned())
    } else {
        (!report.errors.is_empty()).then(|| {
            report
                .errors
                .iter()
                .take(5)
                .cloned()
                .collect::<Vec<_>>()
                .join("; ")
        })
    };
    let succeeded = report.ok();
    db(store, move |s| {
        s.record_sync(platform, started, succeeded, error.as_deref())
    })
    .await?;
    tracing::info!(
        "{platform}: {} repos, {} PRs listed, {} saved, {} missing review data, {} requests, {} errors",
        report.repositories,
        report.listed,
        report.saved,
        report.incomplete,
        report.requests,
        report.errors.len()
    );
    Ok(report)
}

/// The body of a sync. The outer `Result` is the database; the inner one is a
/// failure that stops this platform (listing repositories, or credentials).
async fn run<S: Source>(
    source: &S,
    store: &Shared,
    opts: &Options<'_>,
    since: Option<chrono::DateTime<Utc>>,
    report: &mut Report,
    say: &(dyn Fn(f64, String) + Sync),
) -> Result<Result<(), SourceError>, SyncError> {
    let platform = source.platform();
    let repos = match source.repositories().await {
        Ok(r) => r,
        Err(e) => return Ok(Err(e)),
    };
    report.repositories = repos.len();
    let cached: HashMap<String, PullRequest> = db(store, move |s| s.pull_requests(Some(platform)))
        .await?
        .into_iter()
        .map(|pr| (pr.key(), pr))
        .collect();

    // Phase 1: list PRs per repository; keep the new and changed ones.
    let mut to_complete = Vec::new();
    let total = repos.len().max(1);
    let mut listing = stream::iter(&repos)
        .map(|repo| async move { (repo, source.pull_requests(repo, since).await) })
        .buffer_unordered(opts.workers);
    let mut done = 0;
    while let Some((repo, result)) = listing.next().await {
        done += 1;
        say(
            0.3 * f64_ratio(done, total),
            format!("{platform}: listed {}", repo.name),
        );
        match result {
            Ok(items) => {
                report.listed += items.len();
                for item in items {
                    let prev = cached.get(&key(platform, repo, S::number(&item)));
                    if prev.is_none_or(|p| !source.is_unchanged(&item, p)) {
                        to_complete.push((repo, item));
                    }
                }
            }
            Err(e @ SourceError::Auth(_)) => return Ok(Err(e)),
            Err(e) => report.errors.push(format!("{}: {e}", repo.name)),
        }
        if opts.stop.load(Ordering::Relaxed) {
            return Ok(Ok(()));
        }
    }
    drop(listing);

    // Phase 2: fill in details for those PRs, saving in batches so an
    // interrupted sync keeps what it already has.
    let total = to_complete.len().max(1);
    let mut people = People::new();
    let mut batch = Vec::with_capacity(BATCH);
    let mut completing = stream::iter(to_complete)
        .map(|(repo, item)| async move { (repo, source.complete(repo, item).await) })
        .buffer_unordered(opts.workers);
    let mut done = 0;
    let mut failure = None;
    while let Some((repo, result)) = completing.next().await {
        done += 1;
        let item = match result {
            Ok(item) => item,
            Err(e) => {
                failure = Some(e);
                break;
            }
        };
        let pr = source.convert(repo, &item, &mut people);
        report.incomplete += usize::from(!pr.details_complete);
        batch.push(pr);
        if batch.len() >= BATCH {
            report.saved += save(store, &mut batch, &people).await?;
        }
        say(
            0.3 + 0.7 * f64_ratio(done, total),
            format!("{platform}: {done}/{total} PRs"),
        );
        if opts.stop.load(Ordering::Relaxed) {
            break;
        }
    }
    report.saved += save(store, &mut batch, &people).await?;
    Ok(failure.map_or(Ok(()), Err))
}

async fn save(
    store: &Shared,
    batch: &mut Vec<PullRequest>,
    people: &People,
) -> Result<usize, SyncError> {
    if batch.is_empty() {
        return Ok(0);
    }
    let prs = std::mem::take(batch);
    let people = people.clone();
    db(store, move |s| s.upsert(&prs, &people)).await
}

#[allow(clippy::cast_precision_loss)] // progress fractions; counts are far below 2^52
fn f64_ratio(done: usize, total: usize) -> f64 {
    done as f64 / total as f64
}
