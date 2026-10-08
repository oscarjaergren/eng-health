//! Settings from environment variables. Same names and rules as
//! `eng_health/config.py`, so one `.env` serves both.

use std::collections::HashMap;
use std::path::PathBuf;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ConfigError {
    #[error("{missing} is not set (needed alongside {present})")]
    HalfConfigured {
        missing: &'static str,
        present: &'static str,
    },
    #[error("GITHUB_TYPE must be 'org' or 'user', got {0:?}")]
    OwnerType(String),
    #[error("MAX_PARALLEL_WORKERS must be an integer")]
    Workers,
    #[error("{name} is not a valid http(s) URL: {value:?}")]
    Url { name: &'static str, value: String },
    #[error("GITHUB_TOKEN contains characters an HTTP header can't carry")]
    Token,
}

fn url(name: &'static str, value: &str, default: &str) -> Result<String, ConfigError> {
    let value = if value.is_empty() { default } else { value };
    match reqwest::Url::parse(value) {
        Ok(u) if matches!(u.scheme(), "http" | "https") && u.has_host() => Ok(value.to_owned()),
        _ => Err(ConfigError::Url {
            name,
            value: value.to_owned(),
        }),
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AzureSettings {
    pub organization: String,
    pub token: String,
    /// `https://dev.azure.com`, or an Azure DevOps Server address.
    pub api_url: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OwnerType {
    Org,
    User,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GitHubSettings {
    pub owner: String,
    pub token: String,
    pub owner_type: OwnerType,
    /// GraphQL endpoint; differs on GitHub Enterprise Server.
    pub api_url: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Settings {
    pub azure: Option<AzureSettings>,
    pub github: Option<GitHubSettings>,
    pub data_dir: PathBuf,
    pub max_workers: usize,
}

impl Settings {
    pub fn from_process_env() -> Result<Self, ConfigError> {
        Self::from_env(&std::env::vars().collect())
    }

    pub fn from_env(env: &HashMap<String, String>) -> Result<Self, ConfigError> {
        let get = |k: &str| env.get(k).map(|v| v.trim().to_owned()).unwrap_or_default();

        // Half a config is almost always a typo; failing loudly beats silently
        // ignoring a platform the user meant to enable.
        let pair =
            |a: &'static str, b: &'static str| -> Result<Option<(String, String)>, ConfigError> {
                match (get(a), get(b)) {
                    (va, vb) if !va.is_empty() && !vb.is_empty() => Ok(Some((va, vb))),
                    (va, vb) if va.is_empty() && vb.is_empty() => Ok(None),
                    (va, _) if va.is_empty() => Err(ConfigError::HalfConfigured {
                        missing: a,
                        present: b,
                    }),
                    _ => Err(ConfigError::HalfConfigured {
                        missing: b,
                        present: a,
                    }),
                }
            };

        let azure_url = url(
            "AZURE_DEVOPS_URL",
            &get("AZURE_DEVOPS_URL"),
            crate::source::azure::API,
        )?;
        let azure =
            pair("AZURE_DEVOPS_ORGANIZATION", "AZURE_DEVOPS_PAT")?.map(|(organization, token)| {
                AzureSettings {
                    organization,
                    token,
                    api_url: azure_url,
                }
            });

        let owner_type = match get("GITHUB_TYPE").to_lowercase().as_str() {
            "" | "org" => OwnerType::Org,
            "user" => OwnerType::User,
            other => return Err(ConfigError::OwnerType(other.to_owned())),
        };
        let api_url = url(
            "GITHUB_API_URL",
            &get("GITHUB_API_URL"),
            crate::source::github::API,
        )?;
        let github = pair("GITHUB_OWNER", "GITHUB_TOKEN")?.map(|(owner, token)| GitHubSettings {
            owner,
            token,
            owner_type,
            api_url,
        });
        // The token goes into a header. Values are trimmed, but a character inside the token,
        // such as a line break from a bad paste, would otherwise panic when the client is built.
        if github.as_ref().is_some_and(|g| {
            reqwest::header::HeaderValue::from_str(&format!("Bearer {}", g.token)).is_err()
        }) {
            return Err(ConfigError::Token);
        }

        let workers = match get("MAX_PARALLEL_WORKERS").as_str() {
            "" => 8,
            v => v.parse::<i64>().map_err(|_| ConfigError::Workers)?,
        };
        let data_dir = match get("DATA_DIR").as_str() {
            "" => PathBuf::from("data"),
            v => PathBuf::from(v),
        };

        Ok(Self {
            azure,
            github,
            data_dir,
            max_workers: usize::try_from(workers.max(1)).unwrap_or(1),
        })
    }

    #[must_use]
    pub fn db_path(&self) -> PathBuf {
        self.data_dir.join("eng_health.db")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect()
    }

    #[test]
    fn defaults() {
        let s = Settings::from_env(&env(&[])).unwrap();
        assert!(s.azure.is_none() && s.github.is_none());
        assert_eq!(s.db_path(), PathBuf::from("data/eng_health.db"));
        assert_eq!(s.max_workers, 8);
    }

    #[test]
    fn both_platforms() {
        let s = Settings::from_env(&env(&[
            ("AZURE_DEVOPS_ORGANIZATION", "org"),
            ("AZURE_DEVOPS_PAT", "pat"),
            ("GITHUB_OWNER", "me"),
            ("GITHUB_TOKEN", "tok"),
            ("GITHUB_TYPE", "User"),
        ]))
        .unwrap();
        assert_eq!(s.azure.unwrap().organization, "org");
        assert_eq!(s.github.unwrap().owner_type, OwnerType::User);
    }

    #[test]
    fn invalid_config_fails_loudly() {
        for case in [
            env(&[("AZURE_DEVOPS_ORGANIZATION", "org")]),
            env(&[("GITHUB_TOKEN", "tok")]),
            env(&[("GITHUB_TYPE", "team")]),
            env(&[("MAX_PARALLEL_WORKERS", "many")]),
            env(&[("AZURE_DEVOPS_URL", "dev.azure.com")]),
            env(&[("GITHUB_API_URL", "ftp://example.com")]),
            env(&[("GITHUB_OWNER", "o"), ("GITHUB_TOKEN", "to\nken")]),
        ] {
            assert!(Settings::from_env(&case).is_err(), "{case:?}");
        }
        assert_eq!(
            Settings::from_env(&env(&[("GITHUB_TOKEN", "tok")]))
                .unwrap_err()
                .to_string(),
            "GITHUB_OWNER is not set (needed alongside GITHUB_TOKEN)"
        );
    }
}
