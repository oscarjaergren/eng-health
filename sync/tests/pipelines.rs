//! GitHub Actions jobs against a mock server.

#![expect(
    clippy::unwrap_used,
    reason = "test helpers panic, like the tests that call them"
)]

use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::{Duration as Days, Utc};
use eng_health::Store;
use eng_health::github::GitHub;
use eng_health::parse_time;
use eng_health::{Event, Options};
use eng_health::{GitHubSettings, OwnerType};
use eng_health::{Job, failed_tests, failures_in, sync_pipelines};
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
                "nodes": [{"databaseId": 7, "name": "web", "isPrivate": false,
                           "defaultBranchRef": {"name": "main"}}]
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

async fn sync(gh: &GitHub, store: &Arc<Mutex<Store>>) -> eng_health::Report {
    let quiet = |_: Event| {};
    let opts = Options {
        full: false,
        workers: 2,
        stop: Arc::new(AtomicBool::new(false)),
        on_event: &quiet,
    };
    sync_pipelines(gh, store, &opts).await.unwrap()
}

#[tokio::test]
async fn jobs_from_every_attempt_are_stored_and_reruns_refetched() {
    let server = MockServer::start().await;
    mount_repo(&server).await;
    mount_runs(&server, 2).await;
    let mut windows = job(1, 1, "failure");
    windows["labels"] = json!(["windows-latest"]);
    let mut own = job(2, 2, "success");
    own["labels"] = json!(["self-hosted", "Linux", "X64"]);
    mount_jobs(&server, &[windows, own], 1).await;
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
    // Runners by price; Dependabot's job carries no labels, so it counts as Linux.
    let runners: Vec<(String, bool)> = rusqlite::Connection::open(dir.path().join("db.sqlite"))
        .unwrap()
        .prepare("SELECT runner, is_private FROM pipeline_jobs ORDER BY key")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        runners,
        [
            ("windows".to_owned(), false),
            ("self-hosted".to_owned(), false),
            ("linux".to_owned(), false)
        ]
    );

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
    let repo = eng_health::Repo {
        platform: eng_health::Platform::Github,
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
        runner: "linux",
        is_private: true,
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

fn fixture(name: &str) -> String {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../testdata/pipelines");
    std::fs::read_to_string(root.join(name)).unwrap()
}

#[test]
fn junit_failures_and_errors_count_skips_do_not() {
    assert_eq!(
        failures_in(&fixture("pytest-junit.xml")),
        [
            "tests.test_store::test_version",
            "tests.test_app::test_renders"
        ]
    );
}

#[test]
fn trx_failed_results_with_escaped_names() {
    assert_eq!(
        failures_in(&fixture("dotnet.trx")),
        [
            "Api.Tests.OrderTests.Rejects_empty_cart",
            r#"Api.Tests.ParserTests.Parses(input: "a&b")"#
        ]
    );
}

/// A zip with both fixtures and a file that is not test results.
fn results_zip() -> Vec<u8> {
    use std::io::Write;
    let mut zip = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
    let opts = zip::write::SimpleFileOptions::default();
    for (name, body) in [
        ("TestResults/run.trx", fixture("dotnet.trx")),
        ("junit/Results.XML", fixture("pytest-junit.xml")),
        ("coverage/report.html", "<html/>".to_owned()),
    ] {
        zip.start_file(name, opts).unwrap();
        zip.write_all(body.as_bytes()).unwrap();
    }
    zip.finish().unwrap().into_inner()
}

#[test]
fn every_results_file_in_a_zip_is_read() {
    assert_eq!(failed_tests(&results_zip()).len(), 4);
    assert_eq!(failed_tests(b"not a zip").len(), 0);
}

#[tokio::test]
async fn failed_runs_get_test_failures_from_their_artifacts() {
    let server = MockServer::start().await;
    mount_repo(&server).await;
    mount_runs(&server, 1).await;
    mount_jobs(&server, &[job(1, 1, "failure")], 1).await;
    Mock::given(path("/repos/acme/web/actions/runs/99/artifacts"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(json!({"artifacts": [
                {"id": 5, "name": "test-results", "size_in_bytes": 2048, "expired": false},
                {"id": 6, "name": "coverage", "size_in_bytes": 10, "expired": false}
            ]})),
        )
        .mount(&server)
        .await;
    Mock::given(path("/repos/acme/web/actions/artifacts/5/zip"))
        .respond_with(
            ResponseTemplate::new(302)
                .insert_header("location", format!("{}/blob/5", server.uri())),
        )
        .mount(&server)
        .await;
    Mock::given(path("/blob/5"))
        .respond_with(ResponseTemplate::new(200).set_body_bytes(results_zip()))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(path("/repos/acme/web/actions/artifacts/6/zip"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&server)
        .await;

    let (dir, store) = store();
    assert!(sync(&client(&server), &store).await.ok());
    let tests: Vec<String> = rusqlite::Connection::open(dir.path().join("db.sqlite"))
        .unwrap()
        .prepare("SELECT test_id FROM test_failures WHERE run_id = 99 ORDER BY 1")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(tests.len(), 4);
    assert!(tests.contains(&"tests.test_app::test_renders".to_owned()));
}

fn zip_of(entries: &[(&str, &[u8])]) -> Vec<u8> {
    use std::io::Write;
    let mut zip = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
    for (name, body) in entries {
        zip.start_file(*name, zip::write::SimpleFileOptions::default())
            .unwrap();
        zip.write_all(body).unwrap();
    }
    zip.finish().unwrap().into_inner()
}

#[test]
fn a_results_file_is_read_up_to_the_cap_and_skipped_past_it() {
    // A failing test, padded past 20 MB: it compresses to a few kilobytes, the way a zip bomb
    // does, so only the cap on decompressed size stops it.
    let failing = r#"<testsuite><testcase name="t"><failure/></testcase></testsuite>"#;
    let padded = |name: &str, len: usize| {
        let mut body = failing
            .replace(r#"name="t""#, &format!(r#"name="{name}""#))
            .into_bytes();
        body.resize(len, b' ');
        body
    };
    let cap = 20 * 1024 * 1024;
    let zip = zip_of(&[
        ("over.xml", &padded("bomb", cap + 1)),
        ("at_cap.xml", &padded("fits", cap)),
        ("small.xml", failing.as_bytes()),
    ]);
    assert!(zip.len() < 200_000);
    assert_eq!(failed_tests(&zip), vec!["fits".to_owned(), "t".to_owned()]);
}

proptest::proptest! {
    // Artifacts are untrusted: a fork's PR run can upload anything.

    #[test]
    fn failures_in_never_panics(xml in ".*") {
        let _ = failures_in(&xml);
    }

    #[test]
    fn failures_in_never_panics_on_report_shaped_input(
        parts in proptest::collection::vec(
            proptest::prop_oneof![
                proptest::strategy::Just("<testcase name=\"a\" classname=\"C\">".to_owned()),
                proptest::strategy::Just("</testcase>".to_owned()),
                proptest::strategy::Just("<failure/>".to_owned()),
                proptest::strategy::Just("<error>".to_owned()),
                proptest::strategy::Just("<UnitTestResult outcome=\"Failed\" testName=\"x\"/>".to_owned()),
                "[<>/=\"a-z &;]{0,12}",
            ],
            0..40,
        )
    ) {
        let _ = failures_in(&parts.concat());
    }

    #[test]
    fn failed_tests_never_panics(bytes in proptest::collection::vec(proptest::num::u8::ANY, 0..2048)) {
        let _ = failed_tests(&bytes);
    }

    #[test]
    fn failed_tests_never_panics_on_any_entry_in_a_real_zip(
        body in proptest::collection::vec(proptest::num::u8::ANY, 0..2048)
    ) {
        let _ = failed_tests(&zip_of(&[("r.xml", &body), ("r.trx", &body)]));
    }
}

#[test]
fn reopening_a_current_database_keeps_its_jobs() {
    let dir = tempfile::TempDir::new().unwrap();
    let path = dir.path().join("db.sqlite");
    Store::open(&path)
        .unwrap()
        .upsert_jobs(&[stored_job(1)])
        .unwrap();
    // Only an older schema version drops pipeline_jobs.
    assert_eq!(
        Store::open(&path).unwrap().run_attempts("7").unwrap()[&99],
        1
    );
}
