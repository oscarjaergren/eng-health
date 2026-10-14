//! Reads changed pull requests from a source into the store.
//!
//! Each repository keeps a bookmark: when it was last read, and where its older history continues
//! while some is left. A sync reads every repository's changes first (a repository it never read,
//! its recent PRs), then older history. Each page is saved as it arrives and the bookmark moves
//! with it, so a sync that runs out of API budget continues where it stopped, not from the top.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use chrono::{DateTime, Duration, Utc};
use futures::{StreamExt, stream};
use serde::Serialize;
use tokio::sync::{Semaphore, SemaphorePermit};

use crate::model::{Platform, PullRequest, Repo};
use crate::source::{People, Source, SourceError};
use crate::store::{Bookmark, Store, StoreError};

/// Re-read a little before the last sync so PRs that changed while it ran are not missed.
pub const OVERLAP: Duration = Duration::hours(1);
/// How far back a sync reads: the dashboard's longest view is 12 months, against the 12 before.
/// Reading every PR ever made would cost a large organisation days of API budget.
const HISTORY: Duration = Duration::days(2 * 365);
/// How far back a repository read for the first time goes before any repository's older history,
/// so the first sync of a large organisation shows recent work first.
const RECENT: Duration = Duration::days(90);
const BATCH: usize = 50;

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Report {
    pub platform: String,
    /// `prs` or `pipelines`.
    pub module: String,
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

/// Emitted as the sync runs; `eng-health --progress json` prints one per line.
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

pub(crate) type Shared = Arc<Mutex<Store>>;

pub(crate) async fn db<T: Send + 'static>(
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
        module: "prs".to_owned(),
        ..Report::default()
    };
    let started = Utc::now();
    let say = |fraction: f64, message: String| {
        (opts.on_event)(Event::Progress {
            platform: platform.to_string(),
            fraction,
            message,
        });
    };

    let outcome = run(source, store, opts, started, &mut report, &say).await?;
    report.requests = source.requests();
    finish(store, platform.as_str(), started, outcome, opts, report).await
}

/// Record how a sync went. `last_sync` only moves forward when everything was read and nothing
/// was interrupted.
pub(crate) async fn finish(
    store: &Shared,
    key: &'static str,
    started: chrono::DateTime<Utc>,
    outcome: Result<(), SourceError>,
    opts: &Options<'_>,
    mut report: Report,
) -> Result<Report, SyncError> {
    if let Err(e) = outcome {
        report.errors.push(e.to_string());
    }
    report.interrupted = opts.stop.load(Ordering::Relaxed);
    let error = if report.interrupted {
        Some("interrupted".to_owned())
    } else {
        (!report.errors.is_empty()).then(|| report.errors[..report.errors.len().min(5)].join("; "))
    };
    let succeeded = report.ok();
    db(store, move |s| {
        s.record_sync(key, started, succeeded, error.as_deref())
    })
    .await?;
    tracing::info!(
        "{key}: {} repos, {} listed, {} saved, {} incomplete, {} requests, {} errors",
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
    started: DateTime<Utc>,
    report: &mut Report,
    say: &(dyn Fn(f64, String) + Sync),
) -> Result<Result<(), SourceError>, SyncError> {
    let platform = source.platform();
    let repos = match source.repositories().await {
        Ok(r) => r,
        Err(e) => return Ok(Err(e)),
    };
    report.repositories = repos.len();
    let listed = repos.clone();
    db(store, move |s| s.save_repositories(platform, &listed)).await?;
    match source.viewer().await {
        Ok(Some(me)) => db(store, move |s| s.save_me(platform, &me)).await?,
        Ok(None) => {}
        // Only "Mine" in the dashboard needs it, so it doesn't fail the sync.
        Err(e) => tracing::warn!("{platform}: could not tell whose credentials these are: {e}"),
    }
    match source.teams().await {
        Ok(teams) => db(store, move |s| s.save_teams(platform, &teams)).await?,
        // Reading teams can need a permission the PR sync doesn't (GitHub's read:org).
        Err(e) => tracing::warn!("{platform}: could not read teams: {e}"),
    }
    if opts.full {
        db(store, move |s| s.forget_bookmarks(platform)).await?;
    }
    let marks = db(store, move |s| s.bookmarks(platform)).await?;
    tracing::info!(
        "{platform}: {} repositories, {} read before",
        repos.len(),
        marks.len()
    );
    let mut reader = Reader {
        source,
        store,
        opts,
        cached: cached(store, platform).await?,
        started,
        permits: Semaphore::new(opts.workers),
    };

    let changes = repos
        .iter()
        .map(|r| {
            (
                r,
                marks.get(&r.id).cloned().map_or(Pass::First, Pass::Changes),
            )
        })
        .collect();
    let progress = |done, total, repo: &Repo| {
        say(
            0.5 * f64_ratio(done, total),
            format!("{platform}: read {}", repo.name),
        );
    };
    if let Err(e) = read_all(&reader, changes, report, &progress).await? {
        return Ok(Err(e));
    }
    if reader.stopped() {
        return Ok(Ok(()));
    }

    let marks = db(store, move |s| s.bookmarks(platform)).await?;
    let history: Vec<_> = repos
        .iter()
        .filter_map(|r| {
            marks
                .get(&r.id)
                .filter(|m| m.cursor.is_some())
                .map(|m| (r, Pass::History(m.clone())))
        })
        .collect();
    if !history.is_empty() {
        // What the first pass saved counts as stored now, so it isn't fetched again.
        reader.cached = cached(store, platform).await?;
        let progress = |done, total, repo: &Repo| {
            say(
                0.5 + 0.5 * f64_ratio(done, total),
                format!("{platform}: older PRs of {}", repo.name),
            );
        };
        if let Err(e) = read_all(&reader, history, report, &progress).await? {
            return Ok(Err(e));
        }
    }
    say(1.0, format!("{platform}: done"));
    Ok(Ok(()))
}

async fn cached(
    store: &Shared,
    platform: Platform,
) -> Result<HashMap<String, PullRequest>, SyncError> {
    Ok(db(store, move |s| s.pull_requests(Some(platform)))
        .await?
        .into_iter()
        .map(|pr| (pr.key(), pr))
        .collect())
}

/// Read each repository's pass, several at once. Rejected credentials or a spent API budget stop
/// them all; any other failure is one repository's, which is reported while the rest go on.
async fn read_all<S: Source>(
    reader: &Reader<'_, S>,
    passes: Vec<(&Repo, Pass)>,
    report: &mut Report,
    progress: &dyn Fn(usize, usize, &Repo),
) -> Result<Result<(), SourceError>, SyncError> {
    let total = passes.len();
    let mut reading = stream::iter(passes)
        .map(|(repo, pass)| async move { (repo, reader.read(repo, &pass).await) })
        .buffer_unordered(reader.opts.workers);
    let mut done = 0;
    while let Some((repo, result)) = reading.next().await {
        let (counts, outcome) = result?;
        done += 1;
        progress(done, total, repo);
        report.listed += counts.listed;
        report.saved += counts.saved;
        report.incomplete += counts.incomplete;
        match outcome {
            Ok(()) => {}
            Err(e) if e.stops_the_sync() => return Ok(Err(e)),
            Err(e) => report.errors.push(format!("{}: {e}", repo.name)),
        }
    }
    Ok(Ok(()))
}

/// Which read of a repository this is: how far back it goes, and what its bookmark says after
/// each page.
enum Pass {
    /// Never read: back from the newest PR, the bookmark following each page.
    First,
    /// Read before: what changed since. The bookmark moves once all of it is in.
    Changes(Bookmark),
    /// Older history, from the bookmark's cursor.
    History(Bookmark),
}

impl Pass {
    fn since(&self, started: DateTime<Utc>) -> DateTime<Utc> {
        let since = match self {
            Self::First => started - RECENT,
            Self::Changes(mark) => mark.synced - OVERLAP,
            Self::History(_) => started - HISTORY,
        };
        since.max(started - HISTORY)
    }

    /// The bookmark once a page is saved, if it moves: `next` is where older PRs continue, and
    /// `last` says the page was this read's last.
    fn bookmark(
        &self,
        started: DateTime<Utc>,
        next: Option<String>,
        last: bool,
    ) -> Option<Bookmark> {
        match self {
            Self::First => Some(Bookmark {
                synced: started,
                cursor: next,
            }),
            Self::Changes(mark) => last.then(|| Bookmark {
                synced: started,
                cursor: mark.cursor.clone(),
            }),
            Self::History(mark) => Some(Bookmark {
                synced: mark.synced,
                cursor: next.filter(|_| !last),
            }),
        }
    }
}

#[derive(Default)]
struct Counts {
    listed: usize,
    saved: usize,
    incomplete: usize,
}

/// What reading a repository needs, shared by all the repositories a sync reads at once.
struct Reader<'a, S> {
    source: &'a S,
    store: &'a Shared,
    opts: &'a Options<'a>,
    cached: HashMap<String, PullRequest>,
    started: DateTime<Utc>,
    /// One per request in flight: repositories are read side by side, and so are a page's PRs.
    permits: Semaphore,
}

impl<S: Source> Reader<'_, S> {
    fn stopped(&self) -> bool {
        self.opts.stop.load(Ordering::Relaxed)
    }

    async fn permit(&self) -> SemaphorePermit<'_> {
        self.permits
            .acquire()
            .await
            .expect("the semaphore is never closed")
    }

    /// One repository's pass, page by page, saving each page and then its bookmark. Returns what
    /// it read, with the failure that stopped it early, if one did.
    async fn read(
        &self,
        repo: &Repo,
        pass: &Pass,
    ) -> Result<(Counts, Result<(), SourceError>), SyncError> {
        let platform = self.source.platform();
        let since = pass.since(self.started);
        let mut cursor = match pass {
            Pass::History(mark) => mark.cursor.clone(),
            _ => None,
        };
        let mut counts = Counts::default();
        loop {
            if self.stopped() {
                return Ok((counts, Ok(())));
            }
            let page = {
                let _permit = self.permit().await;
                self.source
                    .pull_requests(repo, since, cursor.as_deref())
                    .await
            };
            let page = match page {
                Ok(page) => page,
                Err(e) => return Ok((counts, Err(e))),
            };
            counts.listed += page.items.len();
            let wanted = page.items.into_iter().filter(|item| {
                let stored = self.cached.get(&key(platform, repo, S::number(item)));
                // Older history only fills in what is missing: a PR that changed since shows up
                // in the changes instead. On Azure DevOps, which can't tell, open PRs would
                // otherwise be fetched twice.
                stored.is_none_or(|p| match pass {
                    Pass::History(_) => !p.details_complete,
                    _ => !self.source.is_unchanged(item, p),
                })
            });
            if let Err(e) = self.save(repo, wanted, &mut counts).await? {
                return Ok((counts, Err(e)));
            }
            if self.stopped() {
                return Ok((counts, Ok(()))); // part of the page may be unsaved: the bookmark waits
            }
            // Where this read goes on, unless the page was its last. A source answering with the
            // cursor it was given would otherwise have the same page read forever.
            let next = page
                .next
                .clone()
                .filter(|n| !page.done && cursor.as_ref() != Some(n));
            if let Some(mark) = pass.bookmark(self.started, page.next, next.is_none()) {
                let id = repo.id.clone();
                db(self.store, move |s| s.save_bookmark(platform, &id, &mark)).await?;
            }
            if next.is_none() {
                return Ok((counts, Ok(())));
            }
            cursor = next;
        }
    }

    /// Fill in what the listing left out of `items`, a few at a time, and save them in batches.
    async fn save(
        &self,
        repo: &Repo,
        items: impl Iterator<Item = S::Item>,
        counts: &mut Counts,
    ) -> Result<Result<(), SourceError>, SyncError> {
        let mut people = People::new();
        let mut batches = stream::iter(items)
            .map(|item| async move {
                let _permit = self.permit().await;
                self.source.complete(repo, item).await
            })
            .buffer_unordered(self.opts.workers)
            .chunks(BATCH);
        while let Some(batch) = batches.next().await {
            let mut prs = Vec::with_capacity(batch.len());
            let mut failure = None;
            for result in batch {
                match result {
                    Ok(item) => prs.push(self.source.convert(repo, &item, &mut people)),
                    Err(e) => failure = Some(e),
                }
            }
            counts.incomplete += prs.iter().filter(|p| !p.details_complete).count();
            counts.saved += save(self.store, prs, &people).await?;
            if let Some(e) = failure {
                return Ok(Err(e));
            }
            if self.stopped() {
                break;
            }
        }
        Ok(Ok(()))
    }
}

async fn save(store: &Shared, prs: Vec<PullRequest>, people: &People) -> Result<usize, SyncError> {
    let people = people.clone();
    db(store, move |s| s.upsert(&prs, &people)).await
}

#[expect(
    clippy::cast_precision_loss,
    reason = "progress fractions; counts are far below 2^52"
)]
pub(crate) fn f64_ratio(done: usize, total: usize) -> f64 {
    done as f64 / total as f64
}
