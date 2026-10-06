//! CI pipelines from GitHub Actions.
//!
//! One request per run (`jobs?filter=all`) returns the jobs of every attempt,
//! which is enough for durations, reruns and flaky jobs. Runs and attempts are
//! derived from jobs by the dashboard, so only jobs are stored.

use std::collections::BTreeSet;
use std::io::Read;
use std::sync::LazyLock;

use chrono::{DateTime, Duration, Utc};
use futures::{StreamExt, stream};
use quick_xml::events::{BytesStart, Event as Xml};
use regex::Regex;
use serde::Deserialize;
use serde::de::DeserializeOwned;

use crate::model::{Repo, Timestamp};
use crate::rules::parse_time;
use crate::source::github::GitHub;
use crate::source::{Source, SourceError};
use crate::sync::{Event, Options, Report, Shared, SyncError, db, f64_ratio, finish};

/// Sync state key, next to the PR module's `github`.
pub const MODULE_KEY: &str = "github:pipelines";
pub const HISTORY_DAYS: i64 = 90;
/// A rerun keeps its run's creation date, so look back further than the PR sync does.
const LOOKBACK: Duration = Duration::days(3);
const BATCH: usize = 50;
const PER_PAGE: usize = 100;
const FAILED: [&str; 2] = ["failure", "timed_out"];
/// Artifacts worth opening for test results, by name.
static TEST_ARTIFACT: LazyLock<Regex> =
    LazyLock::new(|| Regex::new("(?i)test|junit|trx|result").expect("valid regex"));
const MAX_ARTIFACT_BYTES: u64 = 50 * 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Job {
    pub key: String,
    pub repo_id: String,
    pub repository: String,
    pub pipeline: String,
    pub run_id: i64,
    pub attempt: i64,
    pub branch: String,
    pub is_default_branch: bool,
    pub commit_sha: String,
    pub name: String,
    pub conclusion: String,
    pub started_at: Option<Timestamp>,
    pub finished_at: Option<Timestamp>,
    pub url: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Run {
    pub id: i64,
    pub name: Option<String>,
    /// `.github/workflows/ci.yml`, or `dynamic/...` for GitHub's own workflows.
    pub path: Option<String>,
    pub head_branch: Option<String>,
    pub head_sha: String,
    #[serde(default = "one")]
    pub run_attempt: i64,
}

#[derive(Deserialize)]
struct Runs {
    workflow_runs: Vec<Run>,
}

#[derive(Deserialize)]
struct Jobs {
    jobs: Vec<JobInfo>,
}

#[derive(Deserialize)]
struct JobInfo {
    id: i64,
    #[serde(default = "one")]
    run_attempt: i64,
    name: String,
    conclusion: Option<String>,
    started_at: Option<String>,
    completed_at: Option<String>,
    html_url: Option<String>,
}

#[derive(Deserialize)]
struct Artifacts {
    artifacts: Vec<Artifact>,
}

#[derive(Deserialize)]
struct Artifact {
    id: i64,
    name: String,
    size_in_bytes: u64,
    #[serde(default)]
    expired: bool,
}

fn one() -> i64 {
    1
}

/// Failed test ids in every `JUnit` (`*.xml`) or `VSTest` (`*.trx`) file in a zip.
#[must_use]
pub fn failed_tests(zip_bytes: &[u8]) -> Vec<String> {
    let Ok(mut archive) = zip::ZipArchive::new(std::io::Cursor::new(zip_bytes)) else {
        return Vec::new();
    };
    let mut out = BTreeSet::new();
    for i in 0..archive.len() {
        let Ok(mut file) = archive.by_index(i) else {
            continue;
        };
        let ext = std::path::Path::new(file.name())
            .extension()
            .map(|e| e.to_string_lossy().to_lowercase());
        let mut text = String::new();
        if matches!(ext.as_deref(), Some("xml" | "trx")) && file.read_to_string(&mut text).is_ok() {
            out.extend(failures_in(&text));
        }
    }
    out.into_iter().collect()
}

/// `JUnit`: a `testcase` holding a `failure` or `error`. TRX: a `UnitTestResult`
/// with `outcome="Failed"`. Anything else in the file is ignored.
#[must_use]
pub fn failures_in(xml: &str) -> Vec<String> {
    let mut reader = quick_xml::Reader::from_str(xml);
    let mut out = Vec::new();
    let mut case: Option<String> = None;
    loop {
        match reader.read_event() {
            Ok(Xml::Start(e)) if e.local_name().as_ref() == "testcase" => {
                let name = attr(&e, "name");
                let class = attr(&e, "classname");
                case = Some(if class.is_empty() {
                    name
                } else {
                    format!("{class}::{name}")
                });
            }
            Ok(Xml::Start(e) | Xml::Empty(e)) => match e.local_name().as_ref() {
                "failure" | "error" => out.extend(case.take()),
                "UnitTestResult" if attr(&e, "outcome") == "Failed" => {
                    out.push(attr(&e, "testName"));
                }
                _ => {}
            },
            Ok(Xml::End(e)) if e.local_name().as_ref() == "testcase" => case = None,
            Ok(Xml::Eof) | Err(_) => return out,
            _ => {}
        }
    }
}

fn attr(e: &BytesStart<'_>, key: &str) -> String {
    e.attributes()
        .flatten()
        .find(|a| a.key.local_name().as_ref() == key)
        .and_then(|a| {
            a.normalized_value(quick_xml::XmlVersion::Implicit1_0)
                .ok()
                .map(std::borrow::Cow::into_owned)
        })
        .unwrap_or_default()
}

impl GitHub {
    /// REST base for the configured GraphQL endpoint. GitHub Enterprise Server
    /// serves them at `/api/graphql` and `/api/v3`.
    fn rest_base(&self) -> String {
        let gql = self.settings.api_url.trim_end_matches('/');
        match gql.strip_suffix("/api/graphql") {
            Some(host) => format!("{host}/api/v3"),
            None => gql.trim_end_matches("/graphql").to_owned(),
        }
    }

    /// Pages of a `repos/{owner}/{repo}/...` list, until a short page.
    async fn rest_pages<T: DeserializeOwned, I>(
        &self,
        path: &str,
        query: &[(&str, String)],
        items: impl Fn(T) -> Vec<I>,
    ) -> Result<Vec<I>, SourceError> {
        let url = format!("{}/repos/{}/{path}", self.rest_base(), self.settings.owner);
        let mut out = Vec::new();
        for page in 1.. {
            let mut q = query.to_vec();
            q.push(("per_page", PER_PAGE.to_string()));
            q.push(("page", page.to_string()));
            let body: T = self
                .http
                .send(|c| c.get(&url).query(&q))
                .await?
                .json()
                .await
                .map_err(|e| {
                    SourceError::Api(format!("github: unexpected response from {url}: {e}"))
                })?;
            let batch = items(body);
            let n = batch.len();
            out.extend(batch);
            if n < PER_PAGE {
                break;
            }
        }
        Ok(out)
    }

    /// Completed runs created since `since`.
    pub async fn runs(&self, repo: &Repo, since: DateTime<Utc>) -> Result<Vec<Run>, SourceError> {
        // ponytail: GitHub caps a filtered run list at 1,000 results; split the
        // date range if a repository runs more than that within the window.
        let created = format!(">={}", since.format("%Y-%m-%dT%H:%M:%SZ"));
        let query = [("status", "completed".to_owned()), ("created", created)];
        self.rest_pages(&format!("{}/actions/runs", repo.name), &query, |r: Runs| {
            r.workflow_runs
        })
        .await
    }

    /// Jobs from every attempt of a run.
    pub async fn jobs(&self, repo: &Repo, run: &Run) -> Result<Vec<Job>, SourceError> {
        let path = format!("{}/actions/runs/{}/jobs", repo.name, run.id);
        let infos = self
            .rest_pages(&path, &[("filter", "all".to_owned())], |j: Jobs| j.jobs)
            .await?;
        let branch = run.head_branch.clone().unwrap_or_default();
        // GitHub's own workflows (Dependabot, dependency graph) put a run id in
        // the name, so each run would look like a new workflow; their path is stable.
        let pipeline = match (&run.path, &run.name) {
            (Some(path), _) if path.starts_with("dynamic/") => path.clone(),
            (_, Some(name)) => name.clone(),
            _ => "unnamed".to_owned(),
        };
        let default = repo.raw.get("default_branch").and_then(|b| b.as_str());
        Ok(infos
            .into_iter()
            .map(|j| Job {
                key: format!("github:{}:{}", repo.id, j.id),
                repo_id: repo.id.clone(),
                repository: repo.name.clone(),
                pipeline: pipeline.clone(),
                run_id: run.id,
                attempt: j.run_attempt,
                is_default_branch: default == Some(branch.as_str()),
                branch: branch.clone(),
                commit_sha: run.head_sha.clone(),
                name: j.name,
                conclusion: j.conclusion.unwrap_or_else(|| "unknown".to_owned()),
                started_at: parse_time(j.started_at.as_deref()),
                finished_at: parse_time(j.completed_at.as_deref()),
                url: j.html_url.unwrap_or_default(),
            })
            .collect())
    }
}

impl GitHub {
    /// Failed tests from a run's test-result artifacts. Artifacts belong to the
    /// run, not an attempt, so failures are recorded per run.
    pub async fn test_failures(&self, repo: &Repo, run: &Run) -> Result<Vec<String>, SourceError> {
        let path = format!("{}/actions/runs/{}/artifacts", repo.name, run.id);
        let artifacts = self
            .rest_pages(&path, &[], |a: Artifacts| a.artifacts)
            .await?;
        let mut out = BTreeSet::new();
        for a in artifacts {
            if a.expired || a.size_in_bytes > MAX_ARTIFACT_BYTES || !TEST_ARTIFACT.is_match(&a.name)
            {
                continue;
            }
            let url = format!(
                "{}/repos/{}/{}/actions/artifacts/{}/zip",
                self.rest_base(),
                self.settings.owner,
                repo.name,
                a.id
            );
            // GitHub redirects to blob storage; reqwest follows it and drops the token.
            let bytes = self
                .http
                .send(|c| c.get(&url))
                .await?
                .bytes()
                .await
                .map_err(|e| SourceError::Api(format!("github: artifact {}: {e}", a.name)))?;
            out.extend(failed_tests(&bytes));
        }
        Ok(out.into_iter().collect())
    }
}

/// Sync GitHub Actions jobs for the last `HISTORY_DAYS`.
pub async fn sync(gh: &GitHub, store: &Shared, opts: &Options<'_>) -> Result<Report, SyncError> {
    let mut report = Report {
        platform: "github".to_owned(),
        module: "pipelines".to_owned(),
        ..Report::default()
    };
    let started = Utc::now();
    let oldest = started - Duration::days(HISTORY_DAYS);
    let state = db(store, |s| s.sync_state(MODULE_KEY)).await?;
    let since = match state.last_sync {
        Some(t) if !opts.full => (t - LOOKBACK).max(oldest),
        _ => oldest,
    };
    let outcome = run(gh, store, opts, since, &mut report).await?;
    db(store, move |s| s.prune_jobs(oldest)).await?;
    report.requests = gh.requests();
    finish(store, MODULE_KEY, started, outcome, opts, report).await
}

async fn run(
    gh: &GitHub,
    store: &Shared,
    opts: &Options<'_>,
    since: DateTime<Utc>,
    report: &mut Report,
) -> Result<Result<(), SourceError>, SyncError> {
    let say = |fraction: f64, message: String| {
        (opts.on_event)(Event::Progress {
            platform: "github".to_owned(),
            fraction,
            message,
        });
    };
    let repos = match gh.repositories().await {
        Ok(r) => r,
        Err(e) => return Ok(Err(e)),
    };
    report.repositories = repos.len();

    // Phase 1: list runs, keeping new runs and new attempts of stored ones.
    let mut todo = Vec::new();
    let mut listing = stream::iter(&repos)
        .map(|repo| async move { (repo, gh.runs(repo, since).await) })
        .buffer_unordered(opts.workers);
    let mut done = 0;
    while let Some((repo, result)) = listing.next().await {
        done += 1;
        say(
            0.3 * f64_ratio(done, repos.len().max(1)),
            format!("pipelines: listed {}", repo.name),
        );
        match result {
            Ok(runs) => {
                report.listed += runs.len();
                let id = repo.id.clone();
                let stored = db(store, move |s| s.run_attempts(&id)).await?;
                todo.extend(
                    runs.into_iter()
                        .filter(|r| stored.get(&r.id).is_none_or(|a| *a < r.run_attempt))
                        .map(|r| (repo, r)),
                );
            }
            Err(e @ SourceError::Auth(_)) => return Ok(Err(e)),
            Err(e) => report.errors.push(format!("{}: {e}", repo.name)),
        }
    }
    drop(listing);

    // Phase 2: jobs per run, plus failed tests for runs where a job failed (a
    // flaky test needs a failure, so green runs cost no extra requests).
    // Saved in batches so an interrupted sync keeps what it has.
    let total = todo.len().max(1);
    let mut fetching = stream::iter(todo)
        .map(|(repo, r)| async move {
            let jobs = gh.jobs(repo, &r).await;
            let failed = jobs
                .as_ref()
                .is_ok_and(|j| j.iter().any(|j| FAILED.contains(&j.conclusion.as_str())));
            let tests = if failed {
                // ponytail: a failed artifact download only loses that run's test
                // ids (logged); retry per run if that turns out to matter.
                gh.test_failures(repo, &r).await.unwrap_or_else(|e| {
                    tracing::warn!("{}: run {}: {e}", repo.name, r.id);
                    Vec::new()
                })
            } else {
                Vec::new()
            };
            (repo, r.id, jobs, tests)
        })
        .buffer_unordered(opts.workers);
    let (mut jobs_batch, mut tests_batch) = (Vec::new(), Vec::new());
    let mut done = 0;
    while let Some((repo, run_id, result, tests)) = fetching.next().await {
        done += 1;
        match result {
            Ok(jobs) => {
                report.saved += 1;
                jobs_batch.extend(jobs);
                tests_batch.extend(tests.into_iter().map(|t| (repo.id.clone(), run_id, t)));
            }
            Err(e @ SourceError::Auth(_)) => return Ok(Err(e)),
            Err(e) => {
                report.incomplete += 1;
                report.errors.push(format!("{}: {e}", repo.name));
            }
        }
        if jobs_batch.len() >= BATCH {
            let (jobs, tests) = (
                std::mem::take(&mut jobs_batch),
                std::mem::take(&mut tests_batch),
            );
            db(store, move |s| s.save_runs(&jobs, &tests)).await?;
        }
        say(
            0.3 + 0.7 * f64_ratio(done, total),
            format!("pipelines: {done}/{total} runs"),
        );
        if opts.stop.load(std::sync::atomic::Ordering::Relaxed) {
            break;
        }
    }
    db(store, move |s| s.save_runs(&jobs_batch, &tests_batch)).await?;
    Ok(Ok(()))
}
