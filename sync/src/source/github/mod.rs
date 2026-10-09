//! GitHub over GraphQL: each page of PRs arrives with its reviews and comments,
//! so a sync costs dozens of requests where REST needed several per PR.

mod convert;
pub(crate) mod types;

use std::time::Duration;

use chrono::{DateTime, Utc};
use reqwest::header::{AUTHORIZATION, HeaderMap, HeaderValue};
use serde::de::DeserializeOwned;
use serde_json::{Value, json};

use crate::config::{GitHubSettings, OwnerType};
use crate::http::Http;
use crate::model::{Platform, PullRequest, Repo};
use crate::rules::parse_time;
use crate::source::{People, Source, SourceError};

pub use convert::convert;
use types::{PrNode, PullData, PullsData, RateLimit, ReposData, Response};

pub(crate) const API: &str = "https://api.github.com/graphql";

/// PRs per page and items per nested list. Kept modest so each query stays
/// cheap against GitHub's points budget; larger lists get a follow-up query.
const PAGE_SIZE: i64 = 25;
const NESTED: i64 = 30;
const NESTED_MAX: i64 = 100;

const PR_FIELDS: &str = "
fragment PrFields on PullRequest {
  number title url isDraft state createdAt updatedAt closedAt mergedAt
  additions deletions changedFiles files(first: 100) { totalCount nodes { path additions deletions } }
  author { __typename login }
  reviewRequests(first: 25) { nodes { requestedReviewer { ... on User { login } } } }
  reviews(first: $nested) { totalCount nodes { state submittedAt author { __typename login } } }
  comments(first: $nested) { totalCount nodes { createdAt author { __typename login } } }
  reviewThreads(first: $nested) {
    totalCount
    nodes { comments(first: $nested) { totalCount nodes { createdAt author { __typename login } } } }
  }
}";

const ORG_REPOS: &str = "
query($login: String!, $cursor: String) {
  organization(login: $login) {
    repositories(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor } nodes { databaseId name defaultBranchRef { name } }
    }
  }
}";

const USER_REPOS: &str = "
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
      pageInfo { hasNextPage endCursor } nodes { databaseId name defaultBranchRef { name } }
    }
  }
}";

const PULLS: &str = "
query($owner: String!, $name: String!, $cursor: String, $pageSize: Int!, $nested: Int!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequests(first: $pageSize, after: $cursor, orderBy: { field: UPDATED_AT, direction: DESC }) {
      pageInfo { hasNextPage endCursor } nodes { ...PrFields }
    }
  }
}";

const PULL: &str = "
query($owner: String!, $name: String!, $number: Int!, $nested: Int!) {
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

    /// Pause before the next query if it might not fit in what is left.
    async fn pace(&self, limit: Option<&RateLimit>) -> Result<(), SourceError> {
        let Some(limit) = limit else { return Ok(()) };
        if limit.remaining > limit.cost * 2 {
            return Ok(());
        }
        let reset = DateTime::parse_from_rfc3339(&limit.reset_at).map_or(0, |t| t.timestamp());
        self.http
            .wait_for_rate_limit(crate::http::until(reset))
            .await
    }

    async fn fetch_one(
        &self,
        repo: &Repo,
        number: i64,
        nested: i64,
    ) -> Result<Option<PrNode>, SourceError> {
        let vars = json!({
            "owner": self.settings.owner, "name": repo.name, "number": number, "nested": nested,
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
                raw: json!({ "default_branch": r.default_branch_ref.map(|b| b.name) }),
            }));
            if !page.page_info.has_next_page {
                return Ok(repos);
            }
            cursor = page.page_info.end_cursor;
        }
    }

    async fn pull_requests(
        &self,
        repo: &Repo,
        since: Option<DateTime<Utc>>,
    ) -> Result<Vec<Item>, SourceError> {
        let mut out = Vec::new();
        let mut cursor: Option<String> = None;
        loop {
            let vars = json!({
                "owner": self.settings.owner, "name": repo.name, "cursor": cursor,
                "pageSize": PAGE_SIZE, "nested": NESTED,
            });
            let data: PullsData = self.query(&format!("{PULLS}{PR_FIELDS}"), vars).await?;
            let page = data
                .repository
                .ok_or_else(|| {
                    SourceError::Api(format!("github: repository {} not found", repo.name))
                })?
                .pull_requests;
            for node in page.nodes {
                let updated = parse_time(Some(&node.updated_at)).map(crate::model::Timestamp::get);
                if let (Some(since), Some(updated)) = (since, updated)
                    && updated < since
                {
                    return Ok(out); // newest first, so nothing older is new
                }
                out.push(Item::new(node));
            }
            if !page.page_info.has_next_page {
                return Ok(out);
            }
            self.pace(data.rate_limit.as_ref()).await?;
            cursor = page.page_info.end_cursor;
        }
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
