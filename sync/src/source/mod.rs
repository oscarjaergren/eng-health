//! A platform that pull requests are read from.

use std::collections::BTreeMap;
use std::future::Future;

use chrono::{DateTime, Utc};

use crate::model::{Platform, PullRequest, Repo, Timestamp};

pub mod azure;
pub mod github;

/// Identity -> display name, filled in while converting.
pub type People = BTreeMap<String, String>;

/// Each person's earliest response to a PR (comment, vote or review), plus the
/// order people first appeared in, which orders the reviewer list.
#[derive(Default)]
pub(crate) struct Responses {
    pub order: Vec<String>,
    pub times: BTreeMap<String, Timestamp>,
}

impl Responses {
    pub fn note(&mut self, who: &str, when: Option<Timestamp>) {
        let Some(when) = when else { return };
        if !self.times.contains_key(who) {
            self.order.push(who.to_owned());
        }
        let first = self.times.entry(who.to_owned()).or_insert(when);
        *first = (*first).min(when);
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum SourceError {
    /// Credentials were rejected. Never retried: another attempt will not help.
    #[error("{0}")]
    Auth(String),
    #[error("{0}")]
    Api(String),
}

/// The sync loop is generic over this, so each platform keeps its own raw types.
pub trait Source: Send + Sync {
    /// A pull request as listed, possibly still missing comments and reviews.
    type Item: Send;

    fn platform(&self) -> Platform;

    fn repositories(&self) -> impl Future<Output = Result<Vec<Repo>, SourceError>> + Send;

    /// PRs changed since `since` (all of them when `None`).
    fn pull_requests(
        &self,
        repo: &Repo,
        since: Option<DateTime<Utc>>,
    ) -> impl Future<Output = Result<Vec<Self::Item>, SourceError>> + Send;

    fn number(item: &Self::Item) -> i64;

    /// True when the stored copy is still accurate and needs no re-fetch.
    fn is_unchanged(&self, item: &Self::Item, cached: &PullRequest) -> bool;

    /// Fetch whatever the listing left out. Failures other than auth mark the
    /// item incomplete instead of failing, so the next sync retries it.
    fn complete(
        &self,
        repo: &Repo,
        item: Self::Item,
    ) -> impl Future<Output = Result<Self::Item, SourceError>> + Send;

    fn convert(&self, repo: &Repo, item: &Self::Item, people: &mut People) -> PullRequest;

    /// HTTP requests made so far, for the sync report.
    fn requests(&self) -> u64;
}
