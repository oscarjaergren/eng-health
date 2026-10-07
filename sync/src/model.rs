//! The pull request record shared with the Python dashboard.
//!
//! Serialises to exactly the JSON that `PullRequest.to_dict()` in
//! `eng_health/models.py` produces; `testdata/expected` holds the reference.

use std::collections::BTreeMap;
use std::fmt;

use chrono::{DateTime, SubsecRound, Utc};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Platform {
    AzureDevops,
    Github,
}

impl Platform {
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::AzureDevops => "azure_devops",
            Self::Github => "github",
        }
    }
}

impl fmt::Display for Platform {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum State {
    Open,
    Merged,
    Abandoned,
}

/// A UTC instant stored at microsecond precision, written the way Python's
/// `datetime.isoformat()` writes it: `2026-09-01T09:00:00+00:00`, with
/// `.ffffff` only when there are microseconds.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Timestamp(DateTime<Utc>);

impl Timestamp {
    #[must_use]
    pub fn new(t: DateTime<Utc>) -> Self {
        // Python keeps microseconds and drops anything finer (Azure sends 7 digits).
        Self(t.trunc_subsecs(6))
    }

    #[must_use]
    pub fn get(self) -> DateTime<Utc> {
        self.0
    }
}

impl fmt::Display for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let micros = self.0.timestamp_subsec_micros();
        if micros == 0 {
            write!(f, "{}+00:00", self.0.format("%Y-%m-%dT%H:%M:%S"))
        } else {
            write!(
                f,
                "{}.{micros:06}+00:00",
                self.0.format("%Y-%m-%dT%H:%M:%S")
            )
        }
    }
}

impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for Timestamp {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let s = String::deserialize(d)?;
        DateTime::parse_from_rfc3339(&s)
            .map(|t| Self::new(t.with_timezone(&Utc)))
            .map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Repo {
    pub platform: Platform,
    pub id: String,
    pub name: String,
    /// Fields only one platform needs, such as Azure DevOps `webUrl` and project id.
    pub raw: serde_json::Value,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PullRequest {
    pub platform: Platform,
    pub repo_id: String,
    pub repository: String,
    pub number: i64,
    pub title: String,
    pub author: String,
    pub state: State,
    pub is_draft: bool,
    pub created_at: Timestamp,
    pub closed_at: Option<Timestamp>,
    pub url: String,
    pub is_infrastructure: bool,
    /// GitHub exposes this and we use it to skip unchanged PRs; Azure DevOps does not.
    pub updated_at: Option<Timestamp>,
    pub reviewers: Vec<String>,
    pub approvers: Vec<String>,
    pub rejecters: Vec<String>,
    pub comment_counts: BTreeMap<String, i64>,
    /// Earliest comment, vote or review from each person other than the author.
    pub first_responses: BTreeMap<String, Timestamp>,
    /// False when fetching comments or reviews failed, so the next sync retries it.
    pub details_complete: bool,
}

impl PullRequest {
    /// PR numbers are only unique within a repository on GitHub, and the two
    /// platforms' numbering overlaps, so all three parts are needed.
    #[must_use]
    pub fn key(&self) -> String {
        format!("{}:{}:{}", self.platform, self.repo_id, self.number)
    }
}
