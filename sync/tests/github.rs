//! GitHub GraphQL client against a mock server.

use std::time::Duration;

use chrono::{TimeZone, Utc};
use prsync::config::{GitHubSettings, OwnerType};
use prsync::model::{Platform, Repo};
use prsync::source::github::GitHub;
use prsync::source::{Source, SourceError};
use serde_json::{Value, json};
use wiremock::matchers::{body_partial_json, body_string_contains, header, method};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn client(server: &MockServer, owner_type: OwnerType) -> GitHub {
    let settings = GitHubSettings {
        owner: "acme".into(),
        token: "tok".into(),
        owner_type,
        api_url: String::new(),
    };
    GitHub::with_endpoint(
        settings,
        &format!("{}/graphql", server.uri()),
        Duration::from_millis(1),
    )
}

fn repo() -> Repo {
    Repo {
        platform: Platform::Github,
        id: "101".into(),
        name: "web".into(),
        raw: Value::Null,
    }
}

fn pr(number: i64, updated: &str) -> Value {
    json!({
        "number": number, "title": "Add search", "url": format!("https://github.com/acme/web/pull/{number}"),
        "isDraft": false, "state": "MERGED", "createdAt": "2026-08-01T09:00:00Z", "updatedAt": updated,
        "closedAt": updated, "mergedAt": updated, "author": {"__typename": "User", "login": "alice"},
        "reviewRequests": {"nodes": []},
        "reviews": {"totalCount": 0, "nodes": []},
        "comments": {"totalCount": 0, "nodes": []},
        "reviewThreads": {"totalCount": 0, "nodes": []}
    })
}

fn pulls_page(nodes: &[Value], next: Option<&str>) -> ResponseTemplate {
    ResponseTemplate::new(200).set_body_json(json!({"data": {
        "rateLimit": {"cost": 1, "remaining": 4999, "resetAt": "2030-01-01T00:00:00Z"},
        "repository": {"pullRequests": {
            "pageInfo": {"hasNextPage": next.is_some(), "endCursor": next}, "nodes": nodes
        }}
    }}))
}

#[tokio::test]
async fn org_repositories_page_through_and_use_database_ids() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(header("authorization", "Bearer tok"))
        .and(body_string_contains("organization(login"))
        .and(body_partial_json(json!({"variables": {"cursor": null}})))
        .respond_with(ResponseTemplate::new(200).set_body_json(
            json!({"data": {"organization": {"repositories": {
                "pageInfo": {"hasNextPage": true, "endCursor": "c1"},
                "nodes": [{"databaseId": 1, "name": "api"}, null]
            }}}}),
        ))
        .mount(&server)
        .await;
    Mock::given(body_partial_json(json!({"variables": {"cursor": "c1"}})))
        .respond_with(ResponseTemplate::new(200).set_body_json(
            json!({"data": {"organization": {"repositories": {
                "pageInfo": {"hasNextPage": false, "endCursor": null},
                "nodes": [{"databaseId": 2, "name": "web"}]
            }}}}),
        ))
        .mount(&server)
        .await;

    let repos = client(&server, OwnerType::Org)
        .repositories()
        .await
        .unwrap();
    let got: Vec<_> = repos
        .iter()
        .map(|r| (r.id.as_str(), r.name.as_str()))
        .collect();
    assert_eq!(got, [("1", "api"), ("2", "web")]);
}

#[tokio::test]
async fn user_accounts_use_the_user_query() {
    let server = MockServer::start().await;
    Mock::given(body_string_contains("user(login"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"data": {"user": {"repositories": {
            "pageInfo": {"hasNextPage": false, "endCursor": null}, "nodes": [{"databaseId": 7, "name": "dotfiles"}]
        }}}})))
        .mount(&server)
        .await;
    let repos = client(&server, OwnerType::User)
        .repositories()
        .await
        .unwrap();
    assert_eq!(repos[0].name, "dotfiles");
}

#[tokio::test]
async fn unknown_owner_is_an_error() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(json!({"data": {"organization": null}})),
        )
        .mount(&server)
        .await;
    let err = client(&server, OwnerType::Org)
        .repositories()
        .await
        .unwrap_err();
    assert!(matches!(err, SourceError::Api(m) if m.contains("no account named acme")));
}

#[tokio::test]
async fn listing_stops_at_prs_older_than_since() {
    let server = MockServer::start().await;
    Mock::given(body_partial_json(json!({"variables": {"cursor": null}})))
        .respond_with(pulls_page(
            &[
                pr(3, "2026-09-05T00:00:00Z"),
                pr(2, "2026-09-02T00:00:00Z"),
                pr(1, "2026-08-01T00:00:00Z"),
            ],
            Some("c1"),
        ))
        .mount(&server)
        .await;
    Mock::given(body_partial_json(json!({"variables": {"cursor": "c1"}})))
        .respond_with(pulls_page(&[pr(0, "2026-07-01T00:00:00Z")], None))
        .expect(0)
        .mount(&server)
        .await;

    let since = Utc.with_ymd_and_hms(2026, 9, 1, 0, 0, 0).unwrap();
    let items = client(&server, OwnerType::Org)
        .pull_requests(&repo(), Some(since))
        .await
        .unwrap();
    assert_eq!(
        items.iter().map(|i| i.node.number).collect::<Vec<_>>(),
        [3, 2]
    );
}

#[tokio::test]
async fn full_listing_reads_every_page() {
    let server = MockServer::start().await;
    Mock::given(body_partial_json(json!({"variables": {"cursor": null}})))
        .respond_with(pulls_page(&[pr(2, "2026-09-02T00:00:00Z")], Some("c1")))
        .mount(&server)
        .await;
    Mock::given(body_partial_json(json!({"variables": {"cursor": "c1"}})))
        .respond_with(pulls_page(&[pr(1, "2020-01-01T00:00:00Z")], None))
        .mount(&server)
        .await;
    let gh = client(&server, OwnerType::Org);
    let items = gh.pull_requests(&repo(), None).await.unwrap();
    assert_eq!(items.len(), 2);
    assert_eq!(gh.requests(), 2);
}

fn truncated_pr() -> Value {
    let mut node = pr(9, "2026-09-02T00:00:00Z");
    node["comments"] = json!({"totalCount": 2, "nodes": [{"createdAt": "2026-09-01T10:00:00Z", "author": {"__typename": "User", "login": "bob"}}]});
    node
}

#[tokio::test]
async fn truncated_lists_are_completed_with_a_follow_up_query() {
    let server = MockServer::start().await;
    Mock::given(body_string_contains("pullRequests(first"))
        .respond_with(pulls_page(&[truncated_pr()], None))
        .mount(&server)
        .await;
    let mut full = truncated_pr();
    full["comments"]["nodes"]
        .as_array_mut()
        .unwrap()
        .push(json!({"createdAt": "2026-09-01T11:00:00Z", "author": {"__typename": "User", "login": "carol"}}));
    Mock::given(body_string_contains("pullRequest(number"))
        .and(body_partial_json(
            json!({"variables": {"number": 9, "nested": 100}}),
        ))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({"data": {"repository": {"pullRequest": full}}})),
        )
        .mount(&server)
        .await;

    let gh = client(&server, OwnerType::Org);
    let item = gh.pull_requests(&repo(), None).await.unwrap().remove(0);
    assert!(!item.complete);
    let item = gh.complete(&repo(), item).await.unwrap();
    assert!(item.complete);
    assert_eq!(item.node.comments.nodes.len(), 2);
}

#[tokio::test]
async fn failed_follow_up_leaves_the_pr_incomplete() {
    let server = MockServer::start().await;
    Mock::given(body_string_contains("pullRequests(first"))
        .respond_with(pulls_page(&[truncated_pr()], None))
        .mount(&server)
        .await;
    Mock::given(body_string_contains("pullRequest(number"))
        .respond_with(ResponseTemplate::new(500))
        .mount(&server)
        .await;
    let gh = client(&server, OwnerType::Org);
    let item = gh.pull_requests(&repo(), None).await.unwrap().remove(0);
    let item = gh.complete(&repo(), item).await.unwrap();
    assert!(!item.complete);
    // 1 listing + 5 attempts at the follow-up
    assert_eq!(gh.requests(), 6);
}

#[tokio::test]
async fn bad_token_is_an_auth_error() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(
            ResponseTemplate::new(401).set_body_json(json!({"message": "Bad credentials"})),
        )
        .mount(&server)
        .await;
    let err = client(&server, OwnerType::Org)
        .repositories()
        .await
        .unwrap_err();
    assert!(matches!(err, SourceError::Auth(_)));
}

#[tokio::test]
async fn graphql_errors_are_reported() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "data": null, "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a Repository"}]
        })))
        .mount(&server)
        .await;
    let err = client(&server, OwnerType::Org)
        .pull_requests(&repo(), None)
        .await
        .unwrap_err();
    assert!(matches!(err, SourceError::Api(m) if m.contains("Could not resolve")));
}

#[tokio::test]
async fn waits_out_a_rate_limit_then_retries() {
    let server = MockServer::start().await;
    let reset = (Utc::now().timestamp()).to_string();
    Mock::given(method("POST"))
        .respond_with(
            ResponseTemplate::new(403)
                .insert_header("x-ratelimit-remaining", "0")
                .insert_header("x-ratelimit-reset", reset.as_str()),
        )
        .up_to_n_times(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .respond_with(pulls_page(&[pr(1, "2026-09-02T00:00:00Z")], None))
        .mount(&server)
        .await;
    let gh = client(&server, OwnerType::Org);
    let items = gh.pull_requests(&repo(), None).await.unwrap();
    assert_eq!(items.len(), 1);
    assert_eq!(gh.requests(), 2);
}

#[tokio::test]
async fn transient_server_errors_are_retried() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(502))
        .up_to_n_times(2)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .respond_with(pulls_page(&[], None))
        .mount(&server)
        .await;
    let gh = client(&server, OwnerType::Org);
    assert!(gh.pull_requests(&repo(), None).await.unwrap().is_empty());
    assert_eq!(gh.requests(), 3);
}
