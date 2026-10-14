//! GitHub over GraphQL: each page of PRs arrives with its reviews and comments,
//! so a sync costs dozens of requests where REST needed several per PR.

mod convert;
pub(crate) mod types;

use std::sync::Mutex;
use std::time::Duration;

use chrono::{DateTime, Utc};
use reqwest::header::{AUTHORIZATION, HeaderMap, HeaderValue};
use serde::de::DeserializeOwned;
use serde_json::{Value, json};

use crate::config::{GitHubSettings, OwnerType};
use crate::http::Http;
use crate::model::{Platform, PullRequest, Repo, Team};
use crate::rules::{identity, parse_time};
use crate::source::{Page, People, Source, SourceError};

pub use convert::convert;
use types::{PrNode, PullData, PullsData, RateLimit, ReposData, Response};

pub(crate) const API: &str = "https://api.github.com/graphql";

/// PRs per page and items per nested list. GitHub prices a query by how much it could return:
/// each list under a list costs one request per parent, so review threads (each with its own
/// comments) dominate. 10 threads a PR prices a page at 4 points where 30 cost 9. A PR with more
/// gets a follow-up query, at 1 point.
const PAGE_SIZE: i64 = 25;
const NESTED: i64 = 30;
const THREADS: i64 = 10;
const NESTED_MAX: i64 = 100;

const PR_FIELDS: &str = "
fragment PrFields on PullRequest {
  number title url isDraft state createdAt updatedAt closedAt mergedAt
  additions deletions changedFiles files(first: 100) { totalCount nodes { path additions deletions } }
  author { __typename login }
  reviewRequests(first: 25) { nodes { requestedReviewer { ... on User { login } } } }
  reviews(first: $nested) { totalCount nodes { state submittedAt author { __typename login } } }
  comments(first: $nested) { totalCount nodes { createdAt author { __typename login } } }
  reviewThreads(first: $threads) {
    totalCount
    nodes { comments(first: $nested) { totalCount nodes { createdAt author { __typename login } } } }
  }
}";

const ORG_REPOS: &str = "
query($login: String!, $cursor: String) {
  organization(login: $login) {
    repositories(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor } nodes { databaseId name isPrivate isArchived isFork defaultBranchRef { name } }
    }
  }
}";

const USER_REPOS: &str = "
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
      pageInfo { hasNextPage endCursor } nodes { databaseId name isPrivate isArchived isFork defaultBranchRef { name } }
    }
  }
}";

const VIEWER: &str = "query { viewer { login } }";

// membership: ALL counts child teams' members too, as GitHub's team page does.
const TEAMS: &str = "
query($login: String!, $cursor: String) {
  organization(login: $login) {
    teams(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        slug name
        members(first: 100, membership: ALL) { pageInfo { hasNextPage endCursor } nodes { login } }
        repositories(first: 100) { pageInfo { hasNextPage endCursor } nodes { databaseId } }
      }
    }
  }
}";

/// The next page of one team's members or repositories: one list at a time, because a cursor
/// belongs to one list.
fn team_more(field: &str) -> String {
    let (args, nodes) = if field == "members" {
        (", membership: ALL", "login")
    } else {
        ("", "databaseId")
    };
    format!(
        "query($login: String!, $slug: String!, $cursor: String) {{
  organization(login: $login) {{ team(slug: $slug) {{
    {field}(first: 100, after: $cursor{args}) {{ pageInfo {{ hasNextPage endCursor }} nodes {{ {nodes} }} }}
  }} }}
}}"
    )
}

const PULLS: &str = "
query($owner: String!, $name: String!, $cursor: String, $pageSize: Int!, $nested: Int!, $threads: Int!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequests(first: $pageSize, after: $cursor, orderBy: { field: UPDATED_AT, direction: DESC }) {
      pageInfo { hasNextPage endCursor } nodes { ...PrFields }
    }
  }
}";

const PULL: &str = "
query($owner: String!, $name: String!, $number: Int!, $nested: Int!, $threads: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) { ...PrFields } }
}";

/// A listed PR and whether all of its reviews and comments are present.
#[derive(Debug, Clone)]
pub struct Item {
    pub node: PrNode,
    pub complete: bool,
}

impl Item {
    fn new(node: PrNode) -> Self {
        let complete = !truncated(&node);
        Self { node, complete }
    }
}

fn truncated(node: &PrNode) -> bool {
    node.reviews.truncated()
        || node.comments.truncated()
        || node.review_threads.truncated()
        || node
            .review_threads
            .nodes
            .iter()
            .any(|t| t.comments.truncated())
}

pub struct GitHub {
    pub(crate) http: Http,
    endpoint: String,
    pub(crate) settings: GitHubSettings,
    /// The points budget as the last page of PRs left it, shared by every repository's reads.
    budget: Mutex<Option<RateLimit>>,
}

impl GitHub {
    /// # Panics
    /// If the token contains characters that cannot go in an HTTP header.
    #[must_use]
    pub fn new(settings: GitHubSettings) -> Self {
        let endpoint = settings.api_url.clone();
        Self::with_endpoint(settings, &endpoint, Duration::from_secs(1))
    }

    /// # Panics
    /// If the token contains characters that cannot go in an HTTP header.
    #[must_use]
    pub fn with_endpoint(settings: GitHubSettings, endpoint: &str, backoff: Duration) -> Self {
        let mut headers = HeaderMap::new();
        let mut auth = HeaderValue::from_str(&format!("Bearer {}", settings.token))
            .expect("config rejects tokens a header can't carry");
        auth.set_sensitive(true);
        headers.insert(AUTHORIZATION, auth);
        Self {
            http: Http::new("github", headers, false).with_backoff(backoff),
            endpoint: endpoint.to_owned(),
            settings,
            budget: Mutex::new(None),
        }
    }

    async fn query<T: DeserializeOwned>(
        &self,
        query: &str,
        variables: Value,
    ) -> Result<T, SourceError> {
        let body = json!({ "query": query, "variables": variables });
        let mut rate_limited_once = false;
        loop {
            let resp = self
                .http
                .send(|c| c.post(&self.endpoint).json(&body))
                .await?;
            let reset = resp
                .headers()
                .get("x-ratelimit-reset")
                .and_then(|v| v.to_str().ok()?.parse::<i64>().ok());
            let parsed: Response<T> = resp
                .json()
                .await
                .map_err(|e| SourceError::Api(format!("github: unexpected response: {e}")))?;
            if parsed
                .errors
                .iter()
                .any(|e| e.kind.as_deref() == Some("RATE_LIMITED"))
                && !rate_limited_once
            {
                rate_limited_once = true;
                self.http
                    .wait_for_rate_limit(crate::http::until(reset.unwrap_or(0)))
                    .await?;
                continue;
            }
            if !parsed.errors.is_empty() {
                let msgs: Vec<_> = parsed.errors.iter().map(|e| e.message.as_str()).collect();
                return Err(SourceError::Api(format!("github: {}", msgs.join("; "))));
            }
            return parsed
                .data
                .ok_or_else(|| SourceError::Api("github: response had no data".to_owned()));
        }
    }

    /// Pause before a page of PRs if the last one left too little budget for it.
    async fn pace(&self) -> Result<(), SourceError> {
        let reset = {
            let budget = self.budget.lock().expect("no thread panics holding it");
            let Some(limit) = budget.as_ref() else {
                return Ok(());
            };
            if limit.remaining > limit.cost * 2 {
                return Ok(());
            }
            DateTime::parse_from_rfc3339(&limit.reset_at).map_or(0, |t| t.timestamp())
        };
        self.http
            .wait_for_rate_limit(crate::http::until(reset))
            .await
    }

    /// A team's members (logins) or repositories (ids): the first page as listed, then the rest.
    async fn team_list(
        &self,
        slug: &str,
        field: &str,
        first: &Value,
    ) -> Result<Vec<String>, SourceError> {
        let mut out = Vec::new();
        let mut page = first.clone();
        loop {
            out.extend(page["nodes"].as_array().into_iter().flatten().filter_map(
                |n| match field {
                    "members" => n["login"].as_str().map(|l| identity(Some(l))),
                    _ => n["databaseId"].as_i64().map(|id| id.to_string()),
                },
            ));
            if page["pageInfo"]["hasNextPage"] != true {
                return Ok(out);
            }
            let vars = json!({
                "login": self.settings.owner, "slug": slug, "cursor": page["pageInfo"]["endCursor"],
            });
            let data: Value = self.query(&team_more(field), vars).await?;
            page = data["organization"]["team"][field].clone();
        }
    }

    async fn fetch_one(
        &self,
        repo: &Repo,
        number: i64,
        nested: i64,
    ) -> Result<Option<PrNode>, SourceError> {
        let vars = json!({
            "owner": self.settings.owner, "name": repo.name, "number": number,
            "nested": nested, "threads": nested,
        });
        let data: PullData = self.query(&format!("{PULL}{PR_FIELDS}"), vars).await?;
        Ok(data.repository.and_then(|r| r.pull_request))
    }
}

impl Source for GitHub {
    type Item = Item;

    fn platform(&self) -> Platform {
        Platform::Github
    }

    async fn repositories(&self) -> Result<Vec<Repo>, SourceError> {
        let query = match self.settings.owner_type {
            OwnerType::Org => ORG_REPOS,
            OwnerType::User => USER_REPOS,
        };
        let mut repos = Vec::new();
        let mut cursor: Option<String> = None;
        loop {
            let vars = json!({ "login": self.settings.owner, "cursor": cursor });
            let data: ReposData = self.query(query, vars).await?;
            let page = data
                .owner
                .ok_or_else(|| {
                    SourceError::Api(format!("github: no account named {}", self.settings.owner))
                })?
                .repositories;
            repos.extend(page.nodes.into_iter().map(|r| Repo {
                platform: Platform::Github,
                id: r.database_id.to_string(),
                name: r.name,
                owner: self.settings.owner.clone(),
                archived: r.is_archived,
                fork: r.is_fork,
                raw: json!({
                    "default_branch": r.default_branch_ref.map(|b| b.name),
                    "private": r.is_private,
                }),
            }));
            if !page.page_info.has_next_page {
                return Ok(repos);
            }
            cursor = page.page_info.end_cursor;
        }
    }

    async fn viewer(&self) -> Result<Option<String>, SourceError> {
        let data: Value = self.query(VIEWER, json!({})).await?;
        Ok(data["viewer"]["login"].as_str().map(|l| identity(Some(l))))
    }

    async fn teams(&self) -> Result<Vec<Team>, SourceError> {
        if self.settings.owner_type == OwnerType::User {
            return Ok(Vec::new()); // only organisations have teams
        }
        let mut teams = Vec::new();
        let mut cursor: Option<String> = None;
        loop {
            let vars = json!({ "login": self.settings.owner, "cursor": cursor });
            let data: Value = self.query(TEAMS, vars).await?;
            // Missing when the token can't see the organisation's teams: an error, not "none".
            let page = data.pointer("/organization/teams").ok_or_else(|| {
                SourceError::Api(format!(
                    "github: no teams visible for {}",
                    self.settings.owner
                ))
            })?;
            for node in page["nodes"].as_array().into_iter().flatten() {
                let slug = node["slug"].as_str().unwrap_or_default();
                teams.push(Team {
                    id: slug.to_owned(),
                    name: node["name"].as_str().unwrap_or(slug).to_owned(),
                    members: self.team_list(slug, "members", &node["members"]).await?,
                    repos: self
                        .team_list(slug, "repositories", &node["repositories"])
                        .await?,
                });
            }
            if page["pageInfo"]["hasNextPage"] != true {
                return Ok(teams);
            }
            cursor = page["pageInfo"]["endCursor"].as_str().map(str::to_owned);
        }
    }

    async fn pull_requests(
        &self,
        repo: &Repo,
        since: DateTime<Utc>,
        cursor: Option<&str>,
    ) -> Result<Page<Item>, SourceError> {
        self.pace().await?;
        let vars = json!({
            "owner": self.settings.owner, "name": repo.name, "cursor": cursor,
            "pageSize": PAGE_SIZE, "nested": NESTED, "threads": THREADS,
        });
        let data: PullsData = self.query(&format!("{PULLS}{PR_FIELDS}"), vars).await?;
        if let Some(limit) = data.rate_limit {
            tracing::debug!(
                "github: a page of {} cost {} points, {} left",
                repo.name,
                limit.cost,
                limit.remaining
            );
            *self.budget.lock().expect("no thread panics holding it") = Some(limit);
        }
        let page = data
            .repository
            .ok_or_else(|| SourceError::Api(format!("github: repository {} not found", repo.name)))?
            .pull_requests;
        // Newest change first: once one is older than `since`, every later page is too. The
        // older ones on this page stay in it, so a cursor from here skips nothing.
        let done = page
            .nodes
            .last()
            .is_none_or(|n| parse_time(Some(&n.updated_at)).is_some_and(|u| u.get() < since));
        Ok(Page {
            items: page.nodes.into_iter().map(Item::new).collect(),
            next: page
                .page_info
                .end_cursor
                .filter(|_| page.page_info.has_next_page),
            done,
        })
    }

    fn number(item: &Item) -> i64 {
        item.node.number
    }

    fn is_unchanged(&self, item: &Item, cached: &PullRequest) -> bool {
        // A record without a size predates sizes, so it is fetched again to get one.
        cached.details_complete
            && cached.additions.is_some()
            && cached.updated_at == parse_time(Some(&item.node.updated_at))
    }

    async fn complete(&self, repo: &Repo, item: Item) -> Result<Item, SourceError> {
        if item.complete {
            return Ok(item);
        }
        // Rare: a PR with more reviews or comments than one page carries.
        match self.fetch_one(repo, item.node.number, NESTED_MAX).await {
            Ok(Some(node)) => Ok(Item::new(node)),
            Ok(None) => Ok(item),
            Err(e @ SourceError::Auth(_)) => Err(e),
            Err(e) => {
                tracing::warn!("github: {} #{}: {e}", repo.name, item.node.number);
                Ok(item)
            }
        }
    }

    fn convert(&self, repo: &Repo, item: &Item, people: &mut People) -> PullRequest {
        convert(&item.node, repo, item.complete, people)
    }

    fn requests(&self) -> u64 {
        self.http.requests()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{GitHubSettings, OwnerType};

    fn fixture() -> (Repo, Item) {
        let raw: serde_json::Value = serde_json::from_str(include_str!(
            "../../../../testdata/github/reviews_and_comments.graphql.json"
        ))
        .unwrap();
        let repo = Repo {
            platform: Platform::Github,
            id: "101".into(),
            name: "web".into(),
            owner: "o".into(),
            archived: false,
            fork: false,
            raw: json!({}),
        };
        (
            repo,
            Item::new(serde_json::from_value(raw["node"].clone()).unwrap()),
        )
    }

    #[test]
    fn only_a_complete_sized_record_of_the_same_update_is_skipped() {
        let gh = GitHub::new(GitHubSettings {
            owner: "o".into(),
            token: "t".into(),
            owner_type: OwnerType::Org,
            api_url: API.into(),
        });
        let (repo, item) = fixture();
        let stored = gh.convert(&repo, &item, &mut People::new());
        assert!(gh.is_unchanged(&item, &stored));

        let mut older = stored.clone();
        older.updated_at = parse_time(Some("2020-01-01T00:00:00Z"));
        let mut partial = stored.clone();
        partial.details_complete = false;
        let mut no_size = stored;
        no_size.additions = None;
        for cached in [older, partial, no_size] {
            assert!(!gh.is_unchanged(&item, &cached), "{cached:?}");
        }
    }
}
