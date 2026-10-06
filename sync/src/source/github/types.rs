//! Shapes of the GraphQL responses to the queries in `mod.rs`.

use serde::{Deserialize, Deserializer};

#[derive(Debug, Deserialize)]
pub struct Response<T> {
    pub data: Option<T>,
    #[serde(default)]
    pub errors: Vec<GqlError>,
}

#[derive(Debug, Deserialize)]
pub struct GqlError {
    pub message: String,
    #[serde(rename = "type")]
    pub kind: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RateLimit {
    pub cost: i64,
    pub remaining: i64,
    pub reset_at: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PageInfo {
    pub has_next_page: bool,
    pub end_cursor: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", bound(deserialize = "T: Deserialize<'de>"))]
pub struct Page<T> {
    pub page_info: PageInfo,
    #[serde(deserialize_with = "nodes")]
    pub nodes: Vec<T>,
}

// --- repositories ---

#[derive(Debug, Deserialize)]
pub struct ReposData {
    #[serde(alias = "organization", alias = "user")]
    pub owner: Option<ReposOwner>,
}

#[derive(Debug, Deserialize)]
pub struct ReposOwner {
    pub repositories: Page<RepoNode>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RepoNode {
    pub database_id: i64,
    pub name: String,
    pub default_branch_ref: Option<BranchRef>,
}

#[derive(Debug, Deserialize)]
pub struct BranchRef {
    pub name: String,
}

// --- pull requests ---

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PullsData {
    pub rate_limit: Option<RateLimit>,
    pub repository: Option<PullsRepo>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PullsRepo {
    pub pull_requests: Page<PrNode>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PullData {
    pub repository: Option<PullRepo>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PullRepo {
    pub pull_request: Option<PrNode>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PrState {
    Open,
    Closed,
    Merged,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PrNode {
    pub number: i64,
    pub title: String,
    pub url: String,
    pub is_draft: bool,
    pub state: PrState,
    pub created_at: String,
    pub updated_at: String,
    pub closed_at: Option<String>,
    pub merged_at: Option<String>,
    pub author: Option<Actor>,
    pub review_requests: Connection<ReviewRequest>,
    pub reviews: Connection<Review>,
    pub comments: Connection<Comment>,
    pub review_threads: Connection<Thread>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Actor {
    #[serde(rename = "__typename")]
    pub typename: String,
    pub login: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", bound(deserialize = "T: Deserialize<'de>"))]
pub struct Connection<T> {
    #[serde(default)]
    pub total_count: Option<i64>,
    #[serde(deserialize_with = "nodes")]
    pub nodes: Vec<T>,
}

impl<T> Connection<T> {
    /// More items exist than this response carried.
    #[must_use]
    pub fn truncated(&self) -> bool {
        self.total_count
            .is_some_and(|n| usize::try_from(n).unwrap_or(0) > self.nodes.len())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReviewRequest {
    /// Only users are asked for; teams come back as an empty object.
    pub requested_reviewer: Option<RequestedReviewer>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct RequestedReviewer {
    pub login: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Review {
    pub state: String,
    pub submitted_at: Option<String>,
    pub author: Option<Actor>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Comment {
    pub created_at: String,
    pub author: Option<Actor>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Thread {
    pub comments: Connection<Comment>,
}

/// GitHub may return `null` entries in `nodes` (for example, items the token
/// cannot see); skip them.
fn nodes<'de, D, T>(d: D) -> Result<Vec<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    let items: Option<Vec<Option<T>>> = Option::deserialize(d)?;
    Ok(items.unwrap_or_default().into_iter().flatten().collect())
}
