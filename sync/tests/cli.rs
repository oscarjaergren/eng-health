//! The real binary against a mock GitHub, the way the dashboard runs it.

#![expect(
    clippy::unwrap_used,
    reason = "test helpers panic, like the tests that call them"
)]

use std::process::Command;

use serde_json::{Value, json};
use tempfile::TempDir;
use wiremock::matchers::body_string_contains;
use wiremock::{Mock, MockServer, ResponseTemplate};

fn cli(dir: &TempDir, envs: &[(&str, &str)], args: &[&str]) -> std::process::Output {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_eng-health"));
    cmd.args(args)
        .current_dir(dir.path())
        .env_clear()
        .env("DATA_DIR", dir.path());
    for (k, v) in envs {
        cmd.env(k, v);
    }
    cmd.output().unwrap()
}

#[test]
fn missing_configuration_exits_with_code_2() {
    let dir = TempDir::new().unwrap();
    let out = cli(&dir, &[], &["sync"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("No platform configured"));

    let out = cli(&dir, &[("GITHUB_TOKEN", "tok")], &["sync"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("GITHUB_OWNER is not set"));
}

#[tokio::test(flavor = "multi_thread")]
async fn json_progress_and_a_populated_database() {
    let server = MockServer::start().await;
    Mock::given(body_string_contains("organization(login"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"data": {"organization": {"repositories": {
            "pageInfo": {"hasNextPage": false, "endCursor": null}, "nodes": [{"databaseId": 101, "name": "web"}]
        }}}})))
        .mount(&server)
        .await;
    let fixture: Value = serde_json::from_str(include_str!(
        "../../testdata/github/reviews_and_comments.graphql.json"
    ))
    .unwrap();
    Mock::given(body_string_contains("pullRequests(first"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"data": {
            "rateLimit": {"cost": 1, "remaining": 5000, "resetAt": "2030-01-01T00:00:00Z"},
            "repository": {"pullRequests": {
                "pageInfo": {"hasNextPage": false, "endCursor": null}, "nodes": [fixture["node"]]
            }}
        }})))
        .mount(&server)
        .await;

    let dir = TempDir::new().unwrap();
    let envs = [
        ("GITHUB_OWNER", "acme".to_owned()),
        ("GITHUB_TOKEN", "tok".to_owned()),
        ("GITHUB_API_URL", format!("{}/graphql", server.uri())),
    ];
    let data_dir = dir.path().to_owned();
    // Run the blocking child process off the runtime that serves the mock.
    let out = tokio::task::spawn_blocking(move || {
        Command::new(env!("CARGO_BIN_EXE_eng-health"))
            .args(["sync", "--progress", "json", "--only", "prs"])
            .env_clear()
            .env("DATA_DIR", &data_dir)
            .envs(envs)
            .output()
            .unwrap()
    })
    .await
    .unwrap();

    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let events: Vec<Value> = String::from_utf8(out.stdout)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    let report = events.last().unwrap();
    assert_eq!(report["type"], "report");
    assert_eq!(
        (report["repositories"].as_u64(), report["saved"].as_u64()),
        (Some(1), Some(1))
    );
    assert_eq!(report["requests"].as_u64(), Some(2));
    assert!(
        events[..events.len() - 1]
            .iter()
            .all(|e| e["type"] == "progress")
    );

    let status = cli(&dir, &[], &["status"]);
    assert!(String::from_utf8_lossy(&status.stdout).contains("github: last synced 20"));
    let store = eng_health::Store::open(&dir.path().join("eng_health.db")).unwrap();
    let prs = store.pull_requests(None).unwrap();
    assert_eq!(prs[0].key(), "github:101:1");
}
