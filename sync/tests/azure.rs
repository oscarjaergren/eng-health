//! Azure DevOps REST client against a mock server.

use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::{TimeZone, Utc};
use eng_health::AzureSettings;
use eng_health::Store;
use eng_health::azure::{Azure, Threads};
use eng_health::{Event, Options, sync_platform};
use eng_health::{Platform, Repo, State};
use eng_health::{Source, SourceError};
use serde_json::{Value, json};
use wiremock::matchers::{header, method, path, query_param};
use wiremock::{Mock, MockServer, ResponseTemplate};

const PRS: &str = "/org/p1/_apis/git/repositories/r1/pullrequests";

fn client(server: &MockServer) -> Azure {
    let settings = AzureSettings {
        organization: "org".into(),
        token: "pat".into(),
        bearer: false,
        api_url: server.uri(),
    };
    Azure::with_backoff(&settings, Duration::from_millis(1))
}

fn repo() -> Repo {
    Repo {
        platform: Platform::AzureDevops,
        id: "r1".into(),
        name: "api".into(),
        raw: json!({"webUrl": "https://dev.azure.com/org/p/_git/api", "project": {"id": "p1"}}),
    }
}

fn pr(id: i64, status: &str) -> Value {
    json!({
        "pullRequestId": id, "title": "Add search", "status": status,
        "createdBy": {"displayName": "Alice", "uniqueName": "alice@example.com"},
        "creationDate": "2026-09-01T09:00:00Z", "reviewers": []
    })
}

fn list(items: &[Value]) -> ResponseTemplate {
    ResponseTemplate::new(200).set_body_json(json!({ "value": items, "count": items.len() }))
}

#[tokio::test]
async fn repositories_skip_disabled_ones_and_keep_project_and_url() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/org/_apis/git/repositories"))
        .and(query_param("api-version", "7.1"))
        // Basic auth with an empty user name: base64(":pat")
        .and(header("authorization", "Basic OnBhdA=="))
        .respond_with(list(&[
            json!({"id": "r1", "name": "api", "webUrl": "https://x/_git/api", "project": {"id": "p1"}}),
            json!({"id": "r2", "name": "old", "isDisabled": true, "project": {"id": "p1"}}),
        ]))
        .mount(&server)
        .await;
    let repos = client(&server).repositories().await.unwrap();
    assert_eq!(repos.len(), 1);
    assert_eq!(repos[0].raw["project"]["id"], "p1");
    assert_eq!(repos[0].raw["webUrl"], "https://x/_git/api");
}

#[tokio::test]
async fn an_azure_cli_token_is_sent_as_a_bearer_token() {
    let server = MockServer::start().await;
    Mock::given(path("/org/_apis/git/repositories"))
        .and(header("authorization", "Bearer entra-token"))
        .respond_with(list(&[]))
        .expect(1)
        .mount(&server)
        .await;
    let settings = AzureSettings {
        organization: "org".into(),
        token: "entra-token".into(),
        bearer: true,
        api_url: server.uri(),
    };
    let az = Azure::with_backoff(&settings, Duration::from_millis(1));
    assert_eq!(az.repositories().await.unwrap().len(), 0);
}

#[tokio::test]
async fn full_listing_pages_until_a_short_page() {
    let server = MockServer::start().await;
    for (skip, count) in [("0", 100), ("100", 100), ("200", 5)] {
        Mock::given(path(PRS))
            .and(query_param("searchCriteria.status", "all"))
            .and(query_param("$skip", skip))
            .respond_with(list(
                &(0..count).map(|i| pr(i, "completed")).collect::<Vec<_>>(),
            ))
            .expect(1)
            .mount(&server)
            .await;
    }
    let items = client(&server).pull_requests(&repo(), None).await.unwrap();
    assert_eq!(items.len(), 205);
}

#[tokio::test]
async fn incremental_listing_reads_open_prs_and_prs_closed_since() {
    let server = MockServer::start().await;
    Mock::given(path(PRS))
        .and(query_param("searchCriteria.status", "active"))
        .respond_with(list(&[pr(1, "active"), pr(2, "active")]))
        .mount(&server)
        .await;
    Mock::given(path(PRS))
        .and(query_param("searchCriteria.status", "all"))
        .and(query_param("searchCriteria.queryTimeRangeType", "closed"))
        .and(query_param(
            "searchCriteria.minTime",
            "2026-09-01T00:00:00Z",
        ))
        .respond_with(list(&[pr(2, "completed"), pr(3, "abandoned")]))
        .mount(&server)
        .await;
    let since = Utc.with_ymd_and_hms(2026, 9, 1, 0, 0, 0).unwrap();
    let items = client(&server)
        .pull_requests(&repo(), Some(since))
        .await
        .unwrap();
    let mut got: Vec<_> = items
        .iter()
        .map(|i| (i.pr.pull_request_id, i.pr.status.clone()))
        .collect();
    got.sort();
    assert_eq!(
        got,
        [
            (1, "active".into()),
            (2, "completed".into()),
            (3, "abandoned".into())
        ]
    );
}

#[tokio::test]
async fn completing_fetches_threads_or_marks_failure() {
    let server = MockServer::start().await;
    Mock::given(path(
        "/org/p1/_apis/git/repositories/r1/pullRequests/1/threads",
    ))
    .respond_with(list(&[
        json!({"comments": [{"commentType": "text", "author": {"uniqueName": "bob@example.com"}}]}),
    ]))
    .mount(&server)
    .await;
    Mock::given(path(
        "/org/p1/_apis/git/repositories/r1/pullRequests/2/threads",
    ))
    .respond_with(ResponseTemplate::new(500))
    .mount(&server)
    .await;
    let az = client(&server);
    let item = |id| eng_health::azure::Item {
        pr: serde_json::from_value(pr(id, "completed")).unwrap(),
        threads: Threads::NotFetched,
    };

    let ok = az.complete(&repo(), item(1)).await.unwrap();
    assert!(matches!(&ok.threads, Threads::Fetched(t) if t.len() == 1));
    let pr1 = az.convert(&repo(), &ok, &mut eng_health::People::new());
    assert!(pr1.details_complete);
    assert_eq!(pr1.comment_counts["bob@example.com"], 1);

    let failed = az.complete(&repo(), item(2)).await.unwrap();
    assert!(matches!(failed.threads, Threads::Failed));
    assert!(
        !az.convert(&repo(), &failed, &mut eng_health::People::new())
            .details_complete
    );
}

#[tokio::test]
async fn rejected_credentials_are_auth_errors() {
    for status in [401, 203, 403] {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .respond_with(ResponseTemplate::new(status))
            .mount(&server)
            .await;
        let az = client(&server);
        assert!(
            matches!(az.repositories().await, Err(SourceError::Auth(_))),
            "{status}"
        );
        let item = eng_health::azure::Item {
            pr: serde_json::from_value(pr(1, "active")).unwrap(),
            threads: Threads::NotFetched,
        };
        assert!(
            matches!(az.complete(&repo(), item).await, Err(SourceError::Auth(_))),
            "{status}"
        );
    }
}

#[tokio::test]
async fn second_sync_only_refetches_open_prs() {
    let server = MockServer::start().await;
    Mock::given(path("/org/_apis/git/repositories"))
        .respond_with(list(&[json!({"id": "r1", "name": "api", "webUrl": "https://x/_git/api", "project": {"id": "p1"}})]))
        .mount(&server)
        .await;
    Mock::given(path(PRS))
        .and(query_param("searchCriteria.status", "all"))
        .respond_with(list(&[pr(1, "completed"), pr(2, "active")]))
        .mount(&server)
        .await;
    Mock::given(path(PRS))
        .and(query_param("searchCriteria.status", "active"))
        .respond_with(list(&[pr(2, "active")]))
        .mount(&server)
        .await;
    Mock::given(path(
        "/org/p1/_apis/git/repositories/r1/pullRequests/1/threads",
    ))
    .respond_with(list(&[]))
    .expect(1)
    .mount(&server)
    .await;
    Mock::given(path(
        "/org/p1/_apis/git/repositories/r1/pullRequests/2/threads",
    ))
    .respond_with(list(&[]))
    .expect(2)
    .mount(&server)
    .await;

    let dir = tempfile::TempDir::new().unwrap();
    let store = Arc::new(Mutex::new(
        Store::open(&dir.path().join("db.sqlite")).unwrap(),
    ));
    let quiet = |_: Event| {};
    let opts = Options {
        full: false,
        workers: 2,
        stop: Arc::new(AtomicBool::new(false)),
        on_event: &quiet,
    };
    let az = client(&server);
    let first = sync_platform(&az, &store, &opts).await.unwrap();
    let second = sync_platform(&az, &store, &opts).await.unwrap();
    assert!(first.ok() && second.ok(), "{first:?} {second:?}");
    assert_eq!((first.saved, second.saved), (2, 1));
    let states: Vec<_> = store
        .lock()
        .unwrap()
        .pull_requests(None)
        .unwrap()
        .into_iter()
        .map(|p| p.state)
        .collect();
    assert!(states.contains(&State::Merged) && states.contains(&State::Open));
}
