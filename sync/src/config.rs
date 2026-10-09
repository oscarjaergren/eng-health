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
    #[error("{path} is not valid: {reason}")]
    Connections { path: String, reason: String },
    #[error("{platform} is connected through `{command}`, which failed: {reason}. {fix}")]
    Cli {
        platform: &'static str,
        command: String,
        reason: String,
        fix: &'static str,
    },
}

/// What the dashboard's Connect panel saves: which accounts to sync, never a token. Tokens come
/// from the `gh` and `az` CLIs at the start of each sync, so they are always fresh.
#[derive(Debug, Default, serde::Deserialize)]
struct Connections {
    github: Option<GitHubConnection>,
    azure_devops: Option<AzureConnection>,
}

#[derive(Debug, serde::Deserialize)]
struct GitHubConnection {
    owner: String,
    #[serde(rename = "type")]
    owner_type: String,
}

#[derive(Debug, serde::Deserialize)]
struct AzureConnection {
    organization: String,
}

/// The Azure DevOps resource id, which Microsoft Entra tokens for it are issued against.
const AZURE_DEVOPS_RESOURCE: &str = "499b84ac-1321-427f-aa17-267ca6975798";

fn connections(data_dir: &std::path::Path) -> Result<Connections, ConfigError> {
    let path = data_dir.join("connections.json");
    match std::fs::read_to_string(&path) {
        Ok(text) => serde_json::from_str(&text).map_err(|e| ConfigError::Connections {
            path: path.display().to_string(),
            reason: e.to_string(),
        }),
        Err(_) => Ok(Connections::default()),
    }
}

/// A CLI's trimmed stdout. Found on the settings' own PATH, so tests can point it at a fake.
fn cli(
    env: &HashMap<String, String>,
    platform: &'static str,
    fix: &'static str,
    args: &[&str],
) -> Result<String, ConfigError> {
    let mut cmd = std::process::Command::new(args[0]);
    cmd.args(&args[1..]);
    if let Some(path) = env.get("PATH") {
        cmd.env("PATH", path);
    }
    let failed = |reason: String| ConfigError::Cli {
        platform,
        command: args.join(" "),
        reason,
        fix,
    };
    let out = cmd.output().map_err(|e| failed(e.to_string()))?;
    let text = String::from_utf8_lossy(&out.stdout).trim().to_owned();
    if !out.status.success() || text.is_empty() {
        let err = String::from_utf8_lossy(&out.stderr);
        // Its first line, without a final full stop: the message adds its own.
        let first = err.lines().next().unwrap_or("no output").trim();
        return Err(failed(first.trim_end_matches('.').to_owned()));
    }
    Ok(text)
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

fn azure_from_cli(
    env: &HashMap<String, String>,
    c: AzureConnection,
    api_url: String,
) -> Result<AzureSettings, ConfigError> {
    let args = [
        "az",
        "account",
        "get-access-token",
        "--resource",
        AZURE_DEVOPS_RESOURCE,
        "--query",
        "accessToken",
        "--output",
        "tsv",
    ];
    Ok(AzureSettings {
        organization: c.organization,
        token: cli(env, "Azure DevOps", "Sign in with `az login`.", &args)?,
        bearer: true,
        api_url,
    })
}

fn github_from_cli(
    env: &HashMap<String, String>,
    c: GitHubConnection,
    api_url: String,
) -> Result<GitHubSettings, ConfigError> {
    // gh names hosts by their web address: github.com, not api.github.com.
    let host = reqwest::Url::parse(&api_url)
        .ok()
        .and_then(|u| u.host_str().map(str::to_owned))
        .unwrap_or_default()
        .replace("api.github.com", "github.com");
    let args = ["gh", "auth", "token", "--hostname", &host];
    Ok(GitHubSettings {
        owner: c.owner,
        token: cli(env, "GitHub", "Sign in with `gh auth login`.", &args)?,
        owner_type: if c.owner_type == "user" {
            OwnerType::User
        } else {
            OwnerType::Org
        },
        api_url,
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AzureSettings {
    pub organization: String,
    pub token: String,
    /// The token is a Microsoft Entra access token from the Azure CLI, not a PAT.
    pub bearer: bool,
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

        let data_dir = match get("DATA_DIR").as_str() {
            "" => PathBuf::from("data"),
            v => PathBuf::from(v),
        };
        let saved = connections(&data_dir)?;

        let azure_url = url(
            "AZURE_DEVOPS_URL",
            &get("AZURE_DEVOPS_URL"),
            crate::source::azure::API,
        )?;
        let azure = match pair("AZURE_DEVOPS_ORGANIZATION", "AZURE_DEVOPS_PAT")? {
            Some((organization, token)) => Some(AzureSettings {
                organization,
                token,
                bearer: false,
                api_url: azure_url,
            }),
            None => saved
                .azure_devops
                .map(|c| azure_from_cli(env, c, azure_url))
                .transpose()?,
        };

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
        let github = match pair("GITHUB_OWNER", "GITHUB_TOKEN")? {
            Some((owner, token)) => Some(GitHubSettings {
                owner,
                token,
                owner_type,
                api_url,
            }),
            None => saved
                .github
                .map(|c| github_from_cli(env, c, api_url))
                .transpose()?,
        };
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

    /// A data dir with saved connections and fake `gh` and `az` CLIs beside them.
    #[cfg(unix)]
    fn connected(gh: &str, az: &str) -> tempfile::TempDir {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::TempDir::new().unwrap();
        std::fs::write(
            dir.path().join("connections.json"),
            r#"{"github": {"owner": "acme", "type": "user"}, "azure_devops": {"organization": "contoso"}}"#,
        )
        .unwrap();
        for (name, body) in [("gh", gh), ("az", az)] {
            let path = dir.path().join(name);
            std::fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
        dir
    }

    #[cfg(unix)]
    #[test]
    fn connected_platforms_take_a_fresh_token_from_their_cli() {
        // gh only answers for github.com, so asking about api.github.com would fail.
        let dir = connected(
            r#"[ "$*" = "auth token --hostname github.com" ] && echo gho_fake"#,
            r#"[ "$3" = "--resource" ] && echo entra.fake"#,
        );
        let d = dir.path().to_str().unwrap();
        let s = Settings::from_env(&env(&[("DATA_DIR", d), ("PATH", d)])).unwrap();
        let gh = s.github.unwrap();
        assert_eq!((gh.owner.as_str(), gh.token.as_str()), ("acme", "gho_fake"));
        assert_eq!(gh.owner_type, OwnerType::User);
        let az = s.azure.unwrap();
        assert_eq!(
            (az.organization.as_str(), az.token.as_str()),
            ("contoso", "entra.fake")
        );
        assert!(az.bearer);

        // .env still wins over a saved connection.
        let s = Settings::from_env(&env(&[
            ("DATA_DIR", d),
            ("PATH", d),
            ("GITHUB_OWNER", "other"),
            ("GITHUB_TOKEN", "tok"),
        ]))
        .unwrap();
        assert_eq!(s.github.unwrap().token, "tok");
    }

    #[cfg(unix)]
    #[test]
    fn a_cli_that_is_not_signed_in_is_a_configuration_problem() {
        let dir = connected("echo gho_fake", "echo 'Please run az login.' >&2; exit 1");
        let d = dir.path().to_str().unwrap();
        let msg = Settings::from_env(&env(&[("DATA_DIR", d), ("PATH", d)]))
            .unwrap_err()
            .to_string();
        assert!(
            msg.starts_with("Azure DevOps is connected through `az account"),
            "{msg}"
        );
        assert!(
            msg.ends_with("failed: Please run az login. Sign in with `az login`."),
            "{msg}"
        );

        // Success without a token is a failure too, not an empty token.
        let dir = connected("exit 0", "echo entra.fake");
        let d = dir.path().to_str().unwrap();
        let msg = Settings::from_env(&env(&[("DATA_DIR", d), ("PATH", d)]))
            .unwrap_err()
            .to_string();
        assert!(msg.contains("failed: no output"), "{msg}");
    }
}
