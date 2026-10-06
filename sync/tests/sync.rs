//! Sync rules against an in-memory source, including the regressions where
//! re-syncing erased review data.

// The fake answers from memory, so its async methods have nothing to await.
#![allow(clippy::unused_async_trait_impl)]

use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use chrono::{DateTime, Utc};
use prsync::model::{Platform, PullRequest, Repo, State, Timestamp};
use prsync::rules::parse_time;
use prsync::source::{People, Source, SourceError};
use prsync::store::Store;
use prsync::sync::{Event, OVERLAP, Options, sync_platform};
use tempfile::TempDir;

#[derive(Clone)]
struct Pr {
    number: i64,
    updated: &'static str,
    commenters: Vec<&'static str>,
}

#[derive(Clone)]
struct Item {
    pr: Pr,
    complete: bool,
}

#[derive(Default)]
struct Fake {
    prs: Mutex<HashMap<&'static str, Vec<Pr>>>,
    since_seen: Mutex<Vec<Option<DateTime<Utc>>>>,
    completed: Mutex<Vec<i64>>,
    failing_details: Mutex<Vec<i64>>,
    failing_repos: Mutex<Vec<&'static str>>,
    auth_broken: AtomicBool,
}

impl Fake {
    fn add(&self, repo: &'static str, number: i64, commenters: &[&'static str]) {
        self.prs.lock().unwrap().entry(repo).or_default().push(Pr {
            number,
            updated: "2026-09-02T09:00:00Z",
            commenters: commenters.to_vec(),
        });
    }
}

fn repos() -> Vec<Repo> {
    [("1", "web"), ("2", "api")]
        .map(|(id, name)| Repo {
            platform: Platform::Github,
            id: id.into(),
            name: name.into(),
            raw: serde_json::Value::Null,
        })
        .into()
}

impl Source for Fake {
    type Item = Item;

    fn platform(&self) -> Platform {
        Platform::Github
    }

    async fn repositories(&self) -> Result<Vec<Repo>, SourceError> {
        if self.auth_broken.load(Ordering::Relaxed) {
            return Err(SourceError::Auth(
                "github: credentials rejected (401)".into(),
            ));
        }
        Ok(repos())
    }

    async fn pull_requests(
        &self,
        repo: &Repo,
        since: Option<DateTime<Utc>>,
    ) -> Result<Vec<Item>, SourceError> {
        self.since_seen.lock().unwrap().push(since);
        if self
            .failing_repos
            .lock()
            .unwrap()
            .contains(&repo.name.as_str())
        {
            return Err(SourceError::Api("github: 502".into()));
        }
        let prs = self
            .prs
            .lock()
            .unwrap()
            .get(repo.name.as_str())
            .cloned()
            .unwrap_or_default();
        Ok(prs
            .into_iter()
            .map(|pr| Item {
                pr,
                complete: false,
            })
            .collect())
    }

    fn number(item: &Item) -> i64 {
        item.pr.number
    }

    fn is_unchanged(&self, item: &Item, cached: &PullRequest) -> bool {
        cached.details_complete && cached.updated_at == parse_time(Some(item.pr.updated))
    }

    async fn complete(&self, _repo: &Repo, mut item: Item) -> Result<Item, SourceError> {
        self.completed.lock().unwrap().push(item.pr.number);
        item.complete = !self
            .failing_details
            .lock()
            .unwrap()
            .contains(&item.pr.number);
        Ok(item)
    }

    fn convert(&self, repo: &Repo, item: &Item, people: &mut People) -> PullRequest {
        let created = parse_time(Some("2026-09-01T09:00:00Z")).unwrap();
        let mut comment_counts = BTreeMap::new();
        if item.complete {
            for who in &item.pr.commenters {
                people.insert((*who).to_owned(), who.to_uppercase());
                *comment_counts.entry((*who).to_owned()).or_insert(0) += 1;
            }
        }
        PullRequest {
            platform: Platform::Github,
            repo_id: repo.id.clone(),
            repository: repo.name.clone(),
            number: item.pr.number,
            title: "t".into(),
            author: "alice".into(),
            state: State::Merged,
            is_draft: false,
            created_at: created,
            closed_at: None,
            url: String::new(),
            is_infrastructure: false,
            updated_at: parse_time(Some(item.pr.updated)),
            reviewers: vec![],
            approvers: vec![],
            rejecters: vec![],
            comment_counts,
            first_responses: BTreeMap::<String, Timestamp>::new(),
            details_complete: item.complete,
        }
    }

    fn requests(&self) -> u64 {
        0
    }
}

struct Env {
    dir: TempDir,
    store: Arc<Mutex<Store>>,
}

fn env() -> Env {
    let dir = TempDir::new().unwrap();
    let store = Store::open(&dir.path().join("db.sqlite")).unwrap();
    Env {
        dir,
        store: Arc::new(Mutex::new(store)),
    }
}

async fn run(fake: &Fake, env: &Env, full: bool) -> prsync::sync::Report {
    let quiet = |_: Event| {};
    let opts = Options {
        full,
        workers: 4,
        stop: Arc::new(AtomicBool::new(false)),
        on_event: &quiet,
    };
    sync_platform(fake, &env.store, &opts).await.unwrap()
}

fn comments(env: &Env) -> BTreeMap<String, BTreeMap<String, i64>> {
    env.store
        .lock()
        .unwrap()
        .pull_requests(None)
        .unwrap()
        .into_iter()
        .map(|pr| (pr.key(), pr.comment_counts))
        .collect()
}

#[tokio::test]
async fn first_sync_saves_everything_and_keeps_same_numbers_apart() {
    let (fake, env) = (Fake::default(), env());
    fake.add("web", 1, &["bob"]);
    fake.add("api", 1, &[]);
    let report = run(&fake, &env, false).await;
    assert!(report.ok(), "{report:?}");
    assert_eq!(
        (report.repositories, report.listed, report.saved),
        (2, 2, 2)
    );
    assert_eq!(*fake.since_seen.lock().unwrap(), [None, None]);
    assert_eq!(comments(&env).len(), 2);
    let name: String = rusqlite::Connection::open(env.dir.path().join("db.sqlite"))
        .unwrap()
        .query_row("SELECT name FROM people WHERE id = 'bob'", [], |r| r.get(0))
        .unwrap();
    assert_eq!(name, "BOB");
}

#[tokio::test]
async fn resync_does_not_erase_review_data_of_unchanged_prs() {
    let (fake, env) = (Fake::default(), env());
    fake.add("web", 1, &["bob"]);
    run(&fake, &env, false).await;
    fake.completed.lock().unwrap().clear();

    let report = run(&fake, &env, false).await;

    assert_eq!(report.saved, 0);
    assert!(fake.completed.lock().unwrap().is_empty());
    assert_eq!(
        comments(&env)["github:1:1"],
        BTreeMap::from([("bob".to_owned(), 1)])
    );
}

#[tokio::test]
async fn changed_pr_is_refetched() {
    let (fake, env) = (Fake::default(), env());
    fake.add("web", 1, &[]);
    run(&fake, &env, false).await;
    {
        let mut prs = fake.prs.lock().unwrap();
        let pr = &mut prs.get_mut("web").unwrap()[0];
        pr.updated = "2026-09-03T09:00:00Z";
        pr.commenters = vec!["carol"];
    }
    run(&fake, &env, false).await;
    assert_eq!(
        comments(&env)["github:1:1"],
        BTreeMap::from([("carol".to_owned(), 1)])
    );
}

#[tokio::test]
async fn incomplete_prs_are_saved_and_retried() {
    let (fake, env) = (Fake::default(), env());
    fake.add("web", 1, &["bob"]);
    fake.failing_details.lock().unwrap().push(1);
    let report = run(&fake, &env, false).await;
    assert_eq!(report.incomplete, 1);
    assert!(!env.store.lock().unwrap().pull_requests(None).unwrap()[0].details_complete);

    fake.failing_details.lock().unwrap().clear();
    run(&fake, &env, false).await;
    let pr = env
        .store
        .lock()
        .unwrap()
        .pull_requests(None)
        .unwrap()
        .remove(0);
    assert!(pr.details_complete);
    assert_eq!(pr.comment_counts, BTreeMap::from([("bob".to_owned(), 1)]));
}

#[tokio::test]
async fn incremental_sync_starts_before_the_last_success() {
    let (fake, env) = (Fake::default(), env());
    run(&fake, &env, false).await;
    let last = env
        .store
        .lock()
        .unwrap()
        .sync_state("github")
        .unwrap()
        .last_sync
        .unwrap();
    fake.since_seen.lock().unwrap().clear();
    run(&fake, &env, false).await;
    assert_eq!(*fake.since_seen.lock().unwrap(), [Some(last - OVERLAP); 2]);

    fake.since_seen.lock().unwrap().clear();
    run(&fake, &env, true).await;
    assert_eq!(*fake.since_seen.lock().unwrap(), [None, None]);
}

#[tokio::test]
async fn a_failed_repository_does_not_advance_the_window() {
    let (fake, env) = (Fake::default(), env());
    run(&fake, &env, false).await;
    let before = env
        .store
        .lock()
        .unwrap()
        .sync_state("github")
        .unwrap()
        .last_sync;
    fake.failing_repos.lock().unwrap().push("api");
    let report = run(&fake, &env, false).await;
    let state = env.store.lock().unwrap().sync_state("github").unwrap();
    assert!(!report.ok());
    assert_eq!(state.last_sync, before);
    assert!(state.last_error.unwrap().contains("api"));
}

#[tokio::test]
async fn rejected_credentials_are_reported_not_raised() {
    let (fake, env) = (Fake::default(), env());
    fake.auth_broken.store(true, Ordering::Relaxed);
    let report = run(&fake, &env, false).await;
    assert!(!report.ok());
    let state = env.store.lock().unwrap().sync_state("github").unwrap();
    assert!(state.last_error.unwrap().contains("credentials"));
    assert_eq!(state.last_sync, None);
}

#[tokio::test]
async fn stopping_keeps_saved_work_but_not_the_window() {
    let (fake, env) = (Fake::default(), env());
    fake.add("web", 1, &[]);
    let stop = Arc::new(AtomicBool::new(true));
    let quiet = |_: Event| {};
    let opts = Options {
        full: false,
        workers: 1,
        stop,
        on_event: &quiet,
    };
    let report = sync_platform(&fake, &env.store, &opts).await.unwrap();
    assert!(report.interrupted && !report.ok());
    let state = env.store.lock().unwrap().sync_state("github").unwrap();
    assert_eq!(state.last_sync, None);
    assert_eq!(state.last_error.as_deref(), Some("interrupted"));
}

#[tokio::test]
async fn progress_events_cover_both_phases() {
    let (fake, env) = (Fake::default(), env());
    fake.add("web", 1, &[]);
    let events = Mutex::new(Vec::new());
    let record = |e: Event| {
        events
            .lock()
            .unwrap()
            .push(serde_json::to_value(e).unwrap());
    };
    let opts = Options {
        full: false,
        workers: 2,
        stop: Arc::new(AtomicBool::new(false)),
        on_event: &record,
    };
    sync_platform(&fake, &env.store, &opts).await.unwrap();
    let events = events.into_inner().unwrap();
    assert!(
        events
            .iter()
            .all(|e| e["type"] == "progress" && e["platform"] == "github")
    );
    let last = events.last().unwrap()["fraction"].as_f64().unwrap();
    assert!((last - 1.0).abs() < 1e-9, "{last}");
}
