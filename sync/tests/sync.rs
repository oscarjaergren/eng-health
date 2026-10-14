//! Sync rules against an in-memory source, including the regressions where
//! re-syncing erased review data.

#![expect(
    clippy::unwrap_used,
    reason = "test helpers panic, like the tests that call them"
)]
#![expect(
    clippy::unused_async_trait_impl,
    reason = "the fake answers from memory, so its async methods have nothing to await"
)]

use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use chrono::{DateTime, Duration, Utc};
use eng_health::Store;
use eng_health::{Bookmark, Event, OVERLAP, Options, sync_platform};
use eng_health::{Page, People, Source, SourceError};
use eng_health::{Platform, PullRequest, Repo, State, Team, Timestamp};
use tempfile::TempDir;

/// PRs a page, small so a few PRs make several pages.
const PAGE: usize = 2;

#[derive(Clone)]
struct Pr {
    number: i64,
    updated: DateTime<Utc>,
    commenters: Vec<&'static str>,
}

#[derive(Clone)]
struct Item {
    pr: Pr,
    complete: bool,
}

/// What the sync asked for: the repository, how far back, and from where.
type Ask = (String, DateTime<Utc>, Option<String>);

/// A platform like GitHub: PRs listed most recently changed first, a page at a time.
#[derive(Default)]
struct Fake {
    prs: Mutex<HashMap<&'static str, Vec<Pr>>>,
    asked: Mutex<Vec<Ask>>,
    completed: Mutex<Vec<i64>>,
    failing_details: Mutex<Vec<i64>>,
    failing_repos: Mutex<Vec<&'static str>>,
    /// Pages that fail, by cursor: the API budget running out partway.
    failing_cursors: Mutex<Vec<&'static str>>,
    /// Every PR in one page, as Azure DevOps lists them.
    one_page: AtomicBool,
    auth_broken: AtomicBool,
}

/// `days` ago, in whole seconds as the store keeps it.
fn ago(days: i64) -> DateTime<Utc> {
    DateTime::from_timestamp((Utc::now() - Duration::days(days)).timestamp(), 0).unwrap()
}

impl Fake {
    fn add(&self, repo: &'static str, number: i64, commenters: &[&'static str]) {
        self.add_at(repo, number, 1, commenters);
    }

    fn add_at(&self, repo: &'static str, number: i64, days: i64, commenters: &[&'static str]) {
        self.prs.lock().unwrap().entry(repo).or_default().push(Pr {
            number,
            updated: ago(days),
            commenters: commenters.to_vec(),
        });
    }

    fn asked(&self) -> Vec<Ask> {
        self.asked.lock().unwrap().clone()
    }
}

fn repos() -> Vec<Repo> {
    [("1", "web"), ("2", "api")]
        .map(|(id, name)| Repo {
            platform: Platform::Github,
            id: id.into(),
            name: name.into(),
            owner: String::new(),
            archived: false,
            fork: false,
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

    async fn viewer(&self) -> Result<Option<String>, SourceError> {
        Ok(Some("bob".into()))
    }

    async fn teams(&self) -> Result<Vec<Team>, SourceError> {
        Ok(vec![Team {
            id: "web-team".into(),
            name: "Web".into(),
            members: vec!["bob".into()],
            repos: vec!["1".into()],
        }])
    }

    async fn pull_requests(
        &self,
        repo: &Repo,
        since: DateTime<Utc>,
        cursor: Option<&str>,
    ) -> Result<Page<Item>, SourceError> {
        self.asked
            .lock()
            .unwrap()
            .push((repo.name.clone(), since, cursor.map(str::to_owned)));
        if self
            .failing_repos
            .lock()
            .unwrap()
            .contains(&repo.name.as_str())
            || cursor.is_some_and(|c| self.failing_cursors.lock().unwrap().contains(&c))
        {
            return Err(SourceError::Api("github: 502".into()));
        }
        let mut prs = self
            .prs
            .lock()
            .unwrap()
            .get(repo.name.as_str())
            .cloned()
            .unwrap_or_default();
        prs.sort_by_key(|p| std::cmp::Reverse(p.updated));
        let start: usize = cursor.map_or(0, |c| c.parse().unwrap());
        let size = if self.one_page.load(Ordering::Relaxed) {
            prs.len()
        } else {
            PAGE
        };
        let page: Vec<Pr> = prs.iter().skip(start).take(size).cloned().collect();
        let end = start + page.len();
        Ok(Page {
            done: page.last().is_none_or(|p| p.updated < since),
            next: (end < prs.len()).then(|| end.to_string()),
            items: page
                .into_iter()
                .map(|pr| Item {
                    pr,
                    complete: false,
                })
                .collect(),
        })
    }

    fn number(item: &Item) -> i64 {
        item.pr.number
    }

    fn is_unchanged(&self, item: &Item, cached: &PullRequest) -> bool {
        cached.details_complete && cached.updated_at == Some(Timestamp::new(item.pr.updated))
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
            created_at: Timestamp::new(item.pr.updated),
            closed_at: None,
            url: String::new(),
            is_infrastructure: false,
            additions: None,
            deletions: None,
            changed_files: None,
            updated_at: Some(Timestamp::new(item.pr.updated)),
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

async fn run(fake: &Fake, env: &Env, full: bool) -> eng_health::Report {
    let quiet = |_: Event| {};
    let opts = Options {
        full,
        workers: 4,
        stop: Arc::new(AtomicBool::new(false)),
        on_event: &quiet,
    };
    sync_platform(fake, &env.store, &opts).await.unwrap()
}

/// Whether `t` is `days` ago, give or take the test's own runtime.
fn about(t: DateTime<Utc>, days: i64) -> bool {
    (t - (Utc::now() - Duration::days(days)))
        .num_seconds()
        .abs()
        < 60
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

fn numbers(env: &Env) -> Vec<i64> {
    let mut n: Vec<_> = env
        .store
        .lock()
        .unwrap()
        .pull_requests(None)
        .unwrap()
        .iter()
        .map(|p| p.number)
        .collect();
    n.sort_unstable();
    n
}

fn bookmark(env: &Env, repo_id: &str) -> Option<Bookmark> {
    env.store
        .lock()
        .unwrap()
        .bookmarks(Platform::Github)
        .unwrap()
        .remove(repo_id)
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
    // A repository read for the first time starts with its last 90 days.
    let asked = fake.asked();
    assert_eq!(asked.len(), 2);
    assert!(
        asked
            .iter()
            .all(|(_, since, cursor)| about(*since, 90) && cursor.is_none())
    );
    assert_eq!(comments(&env).len(), 2);
    let db = rusqlite::Connection::open(env.dir.path().join("db.sqlite")).unwrap();
    let name: String = db
        .query_row("SELECT name FROM people WHERE id = 'bob'", [], |r| r.get(0))
        .unwrap();
    assert_eq!(name, "BOB");
    let listed: i64 = db
        .query_row("SELECT COUNT(*) FROM repositories", [], |r| r.get(0))
        .unwrap();
    assert_eq!(listed, 2, "the dashboard needs every listed repository");
    let me: String = db
        .query_row(
            "SELECT identity FROM me WHERE platform = 'github'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(me, "bob");
    let team: (String, String, String) = db
        .query_row(
            "SELECT t.name, m.identity, r.repo_id FROM teams t \
             JOIN team_members m USING (platform, team_id) JOIN team_repos r USING (platform, team_id)",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    assert_eq!(team, ("Web".into(), "bob".into(), "1".into()));
}

#[tokio::test]
async fn recent_work_comes_first_then_history_back_two_years() {
    let (fake, env) = (Fake::default(), env());
    for (number, days) in [(1, 1), (2, 10), (3, 100), (4, 400), (5, 800), (6, 900)] {
        fake.add_at("web", number, days, &[]);
    }
    fake.add_at("web", 7, 1000, &[]);
    fake.add_at("web", 8, 1100, &[]);
    fake.add_at("api", 1, 1, &[]);
    let report = run(&fake, &env, false).await;
    assert!(report.ok(), "{report:?}");

    // Pages of two: 1-2, then 3-4, past 90 days, so the first pass stops there. History goes on
    // to 5-6, past two years, and stops.
    assert_eq!(numbers(&env), [1, 1, 2, 3, 4, 5, 6]);
    let asked = fake.asked();
    let history: Vec<_> = asked
        .iter()
        .filter(|(_, since, _)| about(*since, 730))
        .collect();
    assert_eq!(history.len(), 1);
    assert_eq!(
        (history[0].0.as_str(), history[0].2.as_deref()),
        ("web", Some("4"))
    );
    // Every repository's recent PRs were read before any older history.
    assert_eq!(asked.last(), Some(history[0]));
    assert_eq!(bookmark(&env, "1").unwrap().cursor, None);
}

#[tokio::test]
async fn a_sync_that_stops_partway_continues_where_it_stopped() {
    let (fake, env) = (Fake::default(), env());
    for (number, days) in [(1, 1), (2, 10), (3, 100), (4, 400), (5, 500)] {
        fake.add_at("web", number, days, &[]);
    }
    fake.failing_cursors.lock().unwrap().push("4");
    let report = run(&fake, &env, false).await;
    assert!(!report.ok());
    assert_eq!(numbers(&env), [1, 2, 3, 4]);
    assert_eq!(bookmark(&env, "1").unwrap().cursor.as_deref(), Some("4"));

    fake.failing_cursors.lock().unwrap().clear();
    fake.asked.lock().unwrap().clear();
    let report = run(&fake, &env, false).await;
    assert!(report.ok(), "{report:?}");
    assert_eq!(numbers(&env), [1, 2, 3, 4, 5]);
    // The recent pages aren't read again: only what changed since, then history from page 3.
    let web: Vec<_> = fake
        .asked()
        .into_iter()
        .filter(|(repo, ..)| repo == "web")
        .map(|(_, _, cursor)| cursor)
        .collect();
    assert_eq!(web, [None, Some("4".to_owned())]);
    assert_eq!(bookmark(&env, "1").unwrap().cursor, None);
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
        pr.updated = ago(0);
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
    fake.asked.lock().unwrap().clear();
    run(&fake, &env, false).await;
    let since: Vec<_> = fake
        .asked()
        .into_iter()
        .map(|(_, since, _)| since)
        .collect();
    assert_eq!(since, [last - OVERLAP; 2]);

    // A full sync forgets the bookmarks and starts again from the newest.
    fake.asked.lock().unwrap().clear();
    run(&fake, &env, true).await;
    assert!(fake.asked().iter().all(|(_, since, _)| about(*since, 90)));
}

#[tokio::test]
async fn a_failed_repository_keeps_its_bookmark_and_the_window() {
    let (fake, env) = (Fake::default(), env());
    run(&fake, &env, false).await;
    let before = env
        .store
        .lock()
        .unwrap()
        .sync_state("github")
        .unwrap()
        .last_sync;
    let api = bookmark(&env, "2");
    fake.failing_repos.lock().unwrap().push("api");
    let report = run(&fake, &env, false).await;
    let state = env.store.lock().unwrap().sync_state("github").unwrap();
    assert!(!report.ok());
    assert_eq!(state.last_sync, before);
    assert!(state.last_error.unwrap().contains("api"));
    // The repository that was read moves on regardless.
    assert_eq!(bookmark(&env, "2"), api);
    assert!(bookmark(&env, "1").unwrap().synced > before.unwrap());
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
    assert_eq!(bookmark(&env, "1"), None);
}

#[tokio::test]
async fn progress_runs_through_the_changes_then_the_history() {
    let (fake, env) = (Fake::default(), env());
    for repo in ["web", "api"] {
        for (number, days) in [(1, 1), (2, 10), (3, 100), (4, 400), (5, 500)] {
            fake.add_at(repo, number, days, &[]);
        }
    }
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
    let fractions: Vec<_> = events
        .iter()
        .map(|e| e["fraction"].as_f64().unwrap())
        .collect();
    // Each repository's changes are the first half, their history the second.
    assert_eq!(fractions, [0.25, 0.5, 0.75, 1.0, 1.0]);
}

#[tokio::test]
async fn a_page_bigger_than_a_batch_is_saved_whole() {
    // Azure DevOps lists a repository in one go, so one page can hold thousands of PRs.
    let (fake, env) = (Fake::default(), env());
    fake.one_page.store(true, Ordering::Relaxed);
    for number in 1..=120 {
        fake.add("web", number, &[]);
    }
    let report = run(&fake, &env, false).await;
    assert_eq!(report.saved, 120);
    assert_eq!(numbers(&env).len(), 120);
}
