//! GitHub Actions jobs against a mock server.

use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::{Duration as Days, Utc};
use prsync::config::{GitHubSettings, OwnerType};
use prsync::pipelines::{self, Job};
use prsync::rules::parse_time;
use prsync::source::github::GitHub;
use prsync::store::Store;
use prsync::sync::{Event, Options};
use serde_json::{Value, json};
use wiremock::matchers::{body_string_contains, method, path, query_param};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn client(server: &MockServer) -> GitHub {
    let url = format!("{}/graphql", server.uri());
    let settings = GitHubSettings {
        owner: "acme".into(),
        token: "tok".into(),
        owner_type: OwnerType::Org,
        api_url: url.clone(),
    };
    GitHub::with_endpoint(settings, &url, Duration::from_millis(1))
}

async fn mount_repo(server: &MockServer) {
    Mock::given(body_string_contains("organization(login"))
        .respond_with(ResponseTemplate::new(200).set_body_json(
            json!({"data": {"organization": {"repositories": {
                "pageInfo": {"hasNextPage": false, "endCursor": null},
                "nodes": [{"databaseId": 7, "name": "web", "defaultBranchRef": {"name": "main"}}]
            }}}}),
        ))
        .mount(server)
        .await;
}

async fn mount_runs(server: &MockServer, attempt: i64) {
    Mock::given(method("GET"))
        .and(path("/repos/acme/web/actions/runs"))
        .and(query_param("status", "completed"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"workflow_runs": [{
            "id": 99, "name": "CI", "path": ".github/workflows/ci.yml",
            "head_branch": "main", "head_sha": "abc", "run_attempt": attempt
        }, {
            "id": 100, "name": "Graph Update: pip in /. #123", "path": "dynamic/dependabot/update-graph",
            "head_branch": "main", "head_sha": "abc", "run_attempt": 1
        }]})))
        .mount(server)
        .await;
}

fn job(id: i64, attempt: i64, conclusion: &str) -> Value {
    json!({
        "id": id, "run_attempt": attempt, "name": "test", "conclusion": conclusion,
        "started_at": "2026-10-01T10:00:00Z", "completed_at": "2026-10-01T10:05:00Z",
        "html_url": format!("https://github.com/acme/web/actions/runs/99/job/{id}")
    })
}

async fn mount_jobs(server: &MockServer, jobs: &[Value], expect: u64) {
    Mock::given(path("/repos/acme/web/actions/runs/100/jobs"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(json!({"jobs": [job(50, 1, "success")]})),
        )
        .mount(server)
        .await;
    Mock::given(path("/repos/acme/web/actions/runs/99/jobs"))
        .and(query_param("filter", "all"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({"total_count": jobs.len(), "jobs": jobs})),
        )
        .expect(expect)
        .mount(server)
        .await;
}

fn store() -> (tempfile::TempDir, Arc<Mutex<Store>>) {
    let dir = tempfile::TempDir::new().unwrap();
    let store = Store::open(&dir.path().join("db.sqlite")).unwrap();
    (dir, Arc::new(Mutex::new(store)))
}

async fn sync(gh: &GitHub, store: &Arc<Mutex<Store>>) -> prsync::sync::Report {
    let quiet = |_: Event| {};
    let opts = Options {
        full: false,
        workers: 2,
        stop: Arc::new(AtomicBool::new(false)),
        on_event: &quiet,
    };
    pipelines::sync(gh, store, &opts).await.unwrap()
}

#[tokio::test]
async fn jobs_from_every_attempt_are_stored_and_reruns_refetched() {
    let server = MockServer::start().await;
    mount_repo(&server).await;
    mount_runs(&server, 2).await;
    mount_jobs(&server, &[job(1, 1, "failure"), job(2, 2, "success")], 1).await;
    let (dir, store) = store();
    let gh = client(&server);

    let first = sync(&gh, &store).await;
    assert!(first.ok(), "{first:?}");
    assert_eq!(
        (first.module.as_str(), first.listed, first.saved),
        ("pipelines", 2, 2)
    );
    let attempts = store.lock().unwrap().run_attempts("7").unwrap();
    assert_eq!(attempts[&99], 2);
    let names: Vec<String> = rusqlite::Connection::open(dir.path().join("db.sqlite"))
        .unwrap()
        .prepare("SELECT DISTINCT pipeline FROM pipeline_jobs ORDER BY 1")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(names, ["CI", "dynamic/dependabot/update-graph"]);

    // Same run, same attempt: nothing is fetched again (the jobs mock expects one call).
    assert_eq!(sync(&gh, &store).await.saved, 0);
}

#[tokio::test]
async fn a_new_attempt_is_fetched() {
    let server = MockServer::start().await;
    mount_repo(&server).await;
    mount_runs(&server, 3).await;
    mount_jobs(
        &server,
        &[
            job(1, 1, "failure"),
            job(2, 2, "failure"),
            job(3, 3, "success"),
        ],
        1,
    )
    .await;
    let (_dir, store) = store();
    store.lock().unwrap().upsert_jobs(&[stored_job(1)]).unwrap();

    let report = sync(&client(&server), &store).await;
    assert_eq!(report.saved, 2); // the rerun, plus the dynamic run never stored
    assert_eq!(store.lock().unwrap().run_attempts("7").unwrap()[&99], 3);
}

#[tokio::test]
async fn enterprise_rest_base_is_derived_from_graphql_url() {
    let server = MockServer::start().await;
    Mock::given(path("/api/v3/repos/acme/web/actions/runs"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"workflow_runs": []})))
        .expect(1)
        .mount(&server)
        .await;
    let url = format!("{}/api/graphql", server.uri());
    let settings = GitHubSettings {
        owner: "acme".into(),
        token: "tok".into(),
        owner_type: OwnerType::Org,
        api_url: url.clone(),
    };
    let gh = GitHub::with_endpoint(settings, &url, Duration::from_millis(1));
    let repo = prsync::model::Repo {
        platform: prsync::model::Platform::Github,
        id: "7".into(),
        name: "web".into(),
        raw: Value::Null,
    };
    assert!(gh.runs(&repo, Utc::now()).await.unwrap().is_empty());
}

fn stored_job(attempt: i64) -> Job {
    Job {
        key: format!("github:7:{attempt}"),
        repo_id: "7".into(),
        repository: "web".into(),
        pipeline: "CI".into(),
        run_id: 99,
        attempt,
        branch: "main".into(),
        is_default_branch: true,
        commit_sha: "abc".into(),
        name: "test".into(),
        conclusion: "failure".into(),
        started_at: parse_time(Some(&Utc::now().to_rfc3339())),
        finished_at: None,
        url: String::new(),
    }
}

#[test]
fn old_jobs_are_pruned() {
    let (_dir, store) = store();
    let mut old = stored_job(1);
    old.key = "github:7:old".into();
    old.started_at = parse_time(Some(&(Utc::now() - Days::days(200)).to_rfc3339()));
    let mut s = store.lock().unwrap();
    s.upsert_jobs(&[old, stored_job(2)]).unwrap();
    s.prune_jobs(Utc::now() - Days::days(90)).unwrap();
    assert_eq!(s.run_attempts("7").unwrap()[&99], 2);
}
