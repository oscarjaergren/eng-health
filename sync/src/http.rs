//! HTTP with retries, rate-limit waits and a request counter, shared by both sources.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use reqwest::header::{HeaderMap, HeaderValue, USER_AGENT};
use reqwest::{Client, RequestBuilder, Response, StatusCode};

use crate::source::SourceError;

/// Longest we will sleep for a rate limit before giving up for this run.
pub const MAX_RATE_LIMIT_WAIT: Duration = Duration::from_secs(15 * 60);

#[derive(Clone)]
pub struct Http {
    client: Client,
    label: &'static str,
    requests: Arc<AtomicU64>,
    retries: u32,
    backoff: Duration,
    /// Azure DevOps answers 403 for a PAT without the right scope; on GitHub a
    /// 403 is usually one repository or a rate limit, not bad credentials.
    forbidden_is_auth: bool,
}

impl Http {
    /// # Panics
    /// Only if the TLS backend cannot initialise, which is a build problem.
    #[must_use]
    pub fn new(label: &'static str, mut headers: HeaderMap, forbidden_is_auth: bool) -> Self {
        headers.insert(USER_AGENT, HeaderValue::from_static("prsync"));
        let client = Client::builder()
            .default_headers(headers)
            .gzip(true)
            .timeout(Duration::from_secs(30))
            .build()
            .expect("HTTP client builds");
        Self {
            client,
            label,
            requests: Arc::new(AtomicU64::new(0)),
            retries: 4,
            backoff: Duration::from_secs(1),
            forbidden_is_auth,
        }
    }

    /// Shorter retry delays, for tests.
    #[must_use]
    pub fn with_backoff(mut self, backoff: Duration) -> Self {
        self.backoff = backoff;
        self
    }

    #[must_use]
    pub fn requests(&self) -> u64 {
        self.requests.load(Ordering::Relaxed)
    }

    /// Send a request built by `build`, retrying transient failures. Returns
    /// only successful responses; everything else becomes a `SourceError`.
    pub async fn send(
        &self,
        build: impl Fn(&Client) -> RequestBuilder,
    ) -> Result<Response, SourceError> {
        let mut attempt = 0;
        loop {
            self.requests.fetch_add(1, Ordering::Relaxed);
            let started = std::time::Instant::now();
            let resp = match build(&self.client).send().await {
                Ok(resp) => resp,
                Err(e) if attempt < self.retries && (e.is_timeout() || e.is_connect()) => {
                    let wait = self.backoff * 2u32.pow(attempt);
                    tracing::warn!("{}: {e}; retrying in {}s", self.label, wait.as_secs_f32());
                    tokio::time::sleep(wait).await;
                    attempt += 1;
                    continue;
                }
                Err(e) => {
                    return Err(SourceError::Api(format!(
                        "{}: request failed: {e}",
                        self.label
                    )));
                }
            };

            let status = resp.status();
            tracing::debug!(
                "{} {} -> {status} in {}ms",
                self.label,
                resp.url(),
                started.elapsed().as_millis()
            );
            if let Some(wait) = rate_limit_wait(status, resp.headers()) {
                self.wait_for_rate_limit(wait).await?;
                continue;
            }
            if status == StatusCode::UNAUTHORIZED
                // Azure DevOps answers a bad PAT with 203 and an HTML sign-in page.
                || status == StatusCode::NON_AUTHORITATIVE_INFORMATION
                || (status == StatusCode::FORBIDDEN && self.forbidden_is_auth)
            {
                return Err(SourceError::Auth(format!(
                    "{}: credentials rejected ({status})",
                    self.label
                )));
            }
            if is_transient(status) && attempt < self.retries {
                let wait = retry_after(resp.headers()).unwrap_or(self.backoff * 2u32.pow(attempt));
                tracing::warn!(
                    "{}: {status} from {}; retrying in {}s",
                    self.label,
                    resp.url(),
                    wait.as_secs_f32()
                );
                tokio::time::sleep(wait).await;
                attempt += 1;
                continue;
            }
            if !status.is_success() {
                return Err(SourceError::Api(format!(
                    "{}: {status} from {}",
                    self.label,
                    resp.url()
                )));
            }
            return Ok(resp);
        }
    }

    pub async fn wait_for_rate_limit(&self, wait: Duration) -> Result<(), SourceError> {
        if wait > MAX_RATE_LIMIT_WAIT {
            return Err(SourceError::Api(format!(
                "{}: rate limit resets in {} minutes; try later",
                self.label,
                wait.as_secs() / 60
            )));
        }
        tracing::warn!(
            "{} rate limit reached, waiting {}s",
            self.label,
            wait.as_secs()
        );
        tokio::time::sleep(wait).await;
        Ok(())
    }
}

fn is_transient(status: StatusCode) -> bool {
    matches!(status.as_u16(), 429 | 500 | 502 | 503 | 504)
}

fn retry_after(headers: &HeaderMap) -> Option<Duration> {
    let secs: u64 = headers
        .get("retry-after")?
        .to_str()
        .ok()?
        .trim()
        .parse()
        .ok()?;
    Some(Duration::from_secs(secs))
}

/// GitHub signals an exhausted rate limit with 403 or 429 and either
/// `x-ratelimit-remaining: 0` (primary) or `retry-after` (secondary).
fn rate_limit_wait(status: StatusCode, headers: &HeaderMap) -> Option<Duration> {
    if !matches!(status.as_u16(), 403 | 429) {
        return None;
    }
    if headers
        .get("x-ratelimit-remaining")
        .and_then(|v| v.to_str().ok())
        == Some("0")
    {
        let reset: i64 = headers
            .get("x-ratelimit-reset")?
            .to_str()
            .ok()?
            .parse()
            .ok()?;
        return Some(until(reset));
    }
    (status.as_u16() == 403)
        .then(|| retry_after(headers))
        .flatten()
}

/// Time from now until a Unix timestamp, plus a second of margin.
#[must_use]
pub fn until(unix_seconds: i64) -> Duration {
    let secs = unix_seconds - chrono::Utc::now().timestamp() + 1;
    Duration::from_secs(u64::try_from(secs).unwrap_or(1).max(1))
}
