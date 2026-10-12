//! Azure DevOps over REST. There is no GraphQL here, so comment threads are
//! one request per PR; incremental sync keeps that to new and changed PRs.

mod convert;
pub(crate) mod types;

use std::time::Duration;

use chrono::{DateTime, Utc};
use futures::{StreamExt, stream};
use reqwest::{RequestBuilder, Url};
use serde::de::DeserializeOwned;
use serde_json::{Value, json};

use crate::config::AzureSettings;
use crate::http::Http;
use crate::model::{Platform, PullRequest, Repo, State, Team};
use crate::rules::identity;
use crate::source::{People, Source, SourceError};

pub use convert::convert;
use types::{List, PullRequestInfo, RepoInfo, Thread};

pub(crate) const API: &str = "https://dev.azure.com";
const API_VERSION: &str = "7.1";
const PAGE_SIZE: usize = 100;

/// A listed PR plus its comment threads once fetched.
#[derive(Debug, Clone)]
pub struct Item {
    pub pr: PullRequestInfo,
    pub threads: Threads,
}

#[derive(Debug, Clone)]
pub enum Threads {
    NotFetched,
    Fetched(Vec<Thread>),
    /// Fetching failed; the PR is saved as incomplete and retried next sync.
    Failed,
}

pub struct Azure {
    http: Http,
    /// `https://dev.azure.com/{organization}` or a server's collection URL.
    base: Url,
    token: String,
    bearer: bool,
}

impl Azure {
    /// # Panics
    /// If the configured URL is not a valid absolute URL.
    #[must_use]
    pub fn new(settings: &AzureSettings) -> Self {
        Self::with_backoff(settings, Duration::from_secs(1))
    }

    /// # Panics
    /// If the configured URL is not a valid absolute URL.
    #[must_use]
    pub fn with_backoff(settings: &AzureSettings, backoff: Duration) -> Self {
        let mut base = Url::parse(&settings.api_url).expect("AZURE_DEVOPS_URL is a valid URL");
        base.path_segments_mut()
            .expect("AZURE_DEVOPS_URL is an absolute URL")
            .pop_if_empty()
            .push(&settings.organization);
        Self {
            http: Http::new("azure_devops", reqwest::header::HeaderMap::new(), true)
                .with_backoff(backoff),
            base,
            token: settings.token.clone(),
            bearer: settings.bearer,
        }
    }

    fn url(&self, segments: &[&str]) -> Url {
        let mut url = self.base.clone();
        url.path_segments_mut()
            .expect("base is absolute")
            .extend(segments);
        url
    }

    fn get(
        &self,
        url: &Url,
        query: &[(&str, String)],
    ) -> impl Fn(&reqwest::Client) -> RequestBuilder {
        let (url, token, bearer) = (url.clone(), self.token.clone(), self.bearer);
        let mut query = query.to_vec();
        if !query.iter().any(|(k, _)| *k == "api-version") {
            query.push(("api-version", API_VERSION.to_owned()));
        }
        move |c| {
            let request = c.get(url.clone());
            let request = if bearer {
                request.bearer_auth(&token)
            } else {
                request.basic_auth("", Some(&token))
            };
            request.query(&query)
        }
    }

    async fn json<T: DeserializeOwned>(
        &self,
        url: &Url,
        query: &[(&str, String)],
    ) -> Result<T, SourceError> {
        self.http
            .send(self.get(url, query))
            .await?
            .json()
            .await
            .map_err(|e| {
                SourceError::Api(format!("azure_devops: unexpected response from {url}: {e}"))
            })
    }

    fn pr_url(&self, repo: &Repo, rest: &[&str]) -> Url {
        let project = repo
            .raw
            .pointer("/project/id")
            .and_then(|v| v.as_str())
            .unwrap_or_default();
        let mut segments = vec![project, "_apis", "git", "repositories", repo.id.as_str()];
        segments.extend(rest);
        self.url(&segments)
    }

    async fn paged(
        &self,
        repo: &Repo,
        criteria: &[(&str, String)],
    ) -> Result<Vec<PullRequestInfo>, SourceError> {
        let url = self.pr_url(repo, &["pullrequests"]);
        let mut out = Vec::new();
        loop {
            let mut query = criteria.to_vec();
            query.push(("$top", PAGE_SIZE.to_string()));
            query.push(("$skip", out.len().to_string()));
            let page: List<PullRequestInfo> = self.json(&url, &query).await?;
            let n = page.value.len();
            out.extend(page.value);
            if n < PAGE_SIZE {
                return Ok(out);
            }
        }
    }
}

impl Source for Azure {
    type Item = Item;

    fn platform(&self) -> Platform {
        Platform::AzureDevops
    }

    async fn repositories(&self) -> Result<Vec<Repo>, SourceError> {
        let list: List<RepoInfo> = self
            .json(&self.url(&["_apis", "git", "repositories"]), &[])
            .await?;
        Ok(list
            .value
            .into_iter()
            .filter(|r| !r.is_disabled)
            .map(|r| {
                let (project_id, project) = r.project.map(|p| (p.id, p.name)).unzip();
                Repo {
                    platform: Platform::AzureDevops,
                    raw: json!({ "webUrl": r.web_url, "project": { "id": project_id } }),
                    id: r.id,
                    name: r.name,
                    owner: project.unwrap_or_default(),
                    // Azure DevOps has no archiving; disabled repositories are skipped above.
                    archived: false,
                    fork: r.is_fork,
                }
            })
            .collect())
    }

    async fn viewer(&self) -> Result<Option<String>, SourceError> {
        // The location service answers any valid token; the profile API would need a scope the
        // README's PAT doesn't have. It is still a preview API.
        let url = self.url(&["_apis", "connectionData"]);
        let data: Value = self
            .json(&url, &[("api-version", "7.1-preview".to_owned())])
            .await?;
        let account = data.pointer("/authenticatedUser/properties/Account/$value");
        Ok(account.and_then(Value::as_str).map(|a| identity(Some(a))))
    }

    async fn teams(&self) -> Result<Vec<Team>, SourceError> {
        let top = [("$top", "1000".to_owned())];
        let projects: List<Value> = self.json(&self.url(&["_apis", "projects"]), &top).await?;
        let mut teams = Vec::new();
        for project in &projects.value {
            let pid = project["id"].as_str().unwrap_or_default();
            let url = self.url(&["_apis", "projects", pid, "teams"]);
            let list: List<Value> = self.json(&url, &top).await?;
            teams.extend(list.value.into_iter().map(|t| (pid.to_owned(), t)));
        }
        // One request per team for its members, so a few at a time.
        stream::iter(teams)
            .map(|(pid, team)| async move {
                let id = team["id"].as_str().unwrap_or_default().to_owned();
                let url = self.url(&["_apis", "projects", &pid, "teams", &id, "members"]);
                let members: List<Value> = self.json(&url, &[("$top", "1000".to_owned())]).await?;
                Ok(Team {
                    name: team["name"].as_str().unwrap_or(&id).to_owned(),
                    id,
                    members: members
                        .value
                        .iter()
                        .map(|m| &m["identity"])
                        .filter(|i| i["isContainer"] != true) // groups, not people
                        .filter_map(|i| i["uniqueName"].as_str())
                        .map(|u| identity(Some(u)))
                        .collect(),
                    repos: Vec::new(),
                })
            })
            .buffer_unordered(8)
            .collect::<Vec<Result<Team, SourceError>>>()
            .await
            .into_iter()
            .collect()
    }

    async fn pull_requests(
        &self,
        repo: &Repo,
        since: Option<DateTime<Utc>>,
    ) -> Result<Vec<Item>, SourceError> {
        let prs = match since {
            None => {
                self.paged(repo, &[("searchCriteria.status", "all".to_owned())])
                    .await?
            }
            Some(since) => {
                // minTime filters on creation date unless told otherwise, which would
                // miss older PRs that closed since the last sync. So: every open PR,
                // plus anything closed since then.
                let mut prs = self
                    .paged(repo, &[("searchCriteria.status", "active".to_owned())])
                    .await?;
                let closed = self
                    .paged(
                        repo,
                        &[
                            ("searchCriteria.status", "all".to_owned()),
                            ("searchCriteria.queryTimeRangeType", "closed".to_owned()),
                            (
                                "searchCriteria.minTime",
                                since.format("%Y-%m-%dT%H:%M:%SZ").to_string(),
                            ),
                        ],
                    )
                    .await?;
                for pr in closed {
                    match prs
                        .iter_mut()
                        .find(|p| p.pull_request_id == pr.pull_request_id)
                    {
                        Some(existing) => *existing = pr,
                        None => prs.push(pr),
                    }
                }
                prs
            }
        };
        Ok(prs
            .into_iter()
            .map(|pr| Item {
                pr,
                threads: Threads::NotFetched,
            })
            .collect())
    }

    fn number(item: &Item) -> i64 {
        item.pr.pull_request_id
    }

    fn is_unchanged(&self, item: &Item, cached: &PullRequest) -> bool {
        // There is no "last updated" field, so only closed PRs that stayed
        // closed are safe to skip. Open PRs are re-read on every sync.
        cached.details_complete
            && cached.state != State::Open
            && convert::state(&item.pr.status) == cached.state
    }

    async fn complete(&self, repo: &Repo, mut item: Item) -> Result<Item, SourceError> {
        if !matches!(item.threads, Threads::NotFetched) {
            return Ok(item);
        }
        let url = self.pr_url(
            repo,
            &[
                "pullRequests",
                &item.pr.pull_request_id.to_string(),
                "threads",
            ],
        );
        item.threads = match self.json::<List<Thread>>(&url, &[]).await {
            Ok(list) => Threads::Fetched(list.value),
            Err(e @ SourceError::Auth(_)) => return Err(e),
            Err(e) => {
                tracing::warn!(
                    "azure_devops: {} !{}: {e}",
                    repo.name,
                    item.pr.pull_request_id
                );
                Threads::Failed
            }
        };
        Ok(item)
    }

    fn convert(&self, repo: &Repo, item: &Item, people: &mut People) -> PullRequest {
        let threads = match &item.threads {
            Threads::Fetched(t) => Some(t.as_slice()),
            Threads::NotFetched | Threads::Failed => None,
        };
        convert(&item.pr, threads, repo, people)
    }

    fn requests(&self) -> u64 {
        self.http.requests()
    }
}
