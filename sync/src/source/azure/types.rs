//! The parts of Azure DevOps REST responses we read. Fields are optional or
//! defaulted because the API omits empty ones.

use serde::Deserialize;
use serde_json::{Map, Value};

#[derive(Debug, Deserialize)]
pub(crate) struct List<T> {
    #[serde(default = "Vec::new")]
    pub value: Vec<T>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RepoInfo {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub is_disabled: bool,
    #[serde(default)]
    pub web_url: String,
    #[serde(default)]
    pub project: Option<ProjectRef>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ProjectRef {
    pub id: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IdentityRef {
    pub display_name: Option<String>,
    pub unique_name: Option<String>,
    #[serde(default)]
    pub is_container: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Reviewer {
    #[serde(flatten)]
    pub identity: IdentityRef,
    #[serde(default)]
    pub vote: i64,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PullRequestInfo {
    pub pull_request_id: i64,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub is_draft: bool,
    #[serde(default)]
    pub created_by: IdentityRef,
    pub creation_date: Option<String>,
    pub closed_date: Option<String>,
    #[serde(default)]
    pub reviewers: Vec<Reviewer>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Thread {
    pub published_date: Option<String>,
    #[serde(default)]
    pub properties: Map<String, Value>,
    #[serde(default)]
    pub identities: Map<String, Value>,
    #[serde(default)]
    pub comments: Vec<Comment>,
}

impl Thread {
    /// A property's `$value` as text; Azure DevOps sends some as numbers.
    #[must_use]
    pub fn property(&self, name: &str) -> String {
        match self.properties.get(name).and_then(|p| p.get("$value")) {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Number(n)) => n.to_string(),
            _ => String::new(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
#[expect(
    clippy::struct_field_names,
    reason = "named as in the Azure DevOps API"
)]
pub struct Comment {
    #[serde(default)]
    pub comment_type: String,
    #[serde(default)]
    pub is_deleted: bool,
    #[serde(default)]
    pub author: IdentityRef,
    pub published_date: Option<String>,
}
