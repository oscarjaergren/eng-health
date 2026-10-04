//! Identity, bot and infrastructure rules. Mirrors `pr_analytics/processing.py`.

use std::sync::LazyLock;

use chrono::{DateTime, Datelike, NaiveDateTime, Utc};
use regex::Regex;

use crate::model::Timestamp;

// Whole words in the title only. Substring matching used to drop ordinary PRs
// ("platform" contains "tf", "alarm" contains "arm").
static INFRA: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?i)\b(terraform|tf|tfvars|bicep|helm|kubernetes|k8s|ansible|pulumi|cloudformation|arm templates?|iac|infra|infrastructure)\b",
    )
    .expect("valid regex")
});

const KNOWN_BOTS: [&str; 4] = ["github-actions", "dependabot", "renovate", "copilot"];

#[must_use]
pub fn is_infrastructure(title: &str) -> bool {
    INFRA.is_match(title)
}

#[must_use]
pub fn identity(value: Option<&str>) -> String {
    value.unwrap_or_default().trim().to_lowercase()
}

#[must_use]
pub fn is_bot(ident: &str, is_group: bool) -> bool {
    is_group
        || ident.is_empty()
        || ident.starts_with("vstfs:")
        || ident.ends_with("[bot]")
        // Azure DevOps groups and build services look like "domain\name" with no email.
        || (ident.contains('\\') && !ident.contains('@'))
        || KNOWN_BOTS.contains(&ident)
}

/// Parse an API timestamp. Missing offsets mean UTC, and anything before 1970
/// means "not set" (Azure DevOps uses 0001-01-01).
#[must_use]
pub fn parse_time(value: Option<&str>) -> Option<Timestamp> {
    let s = value.filter(|s| !s.is_empty())?;
    let t = DateTime::parse_from_rfc3339(s)
        .map(|t| t.with_timezone(&Utc))
        .or_else(|_| NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f").map(|n| n.and_utc()))
        .ok()?;
    (t.year() >= 1970).then(|| Timestamp::new(t))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn infrastructure_matches_whole_words_only() {
        for (title, expected) in [
            ("Add platform settings page", false),
            ("Fix login alarm threshold", false),
            ("Fix harmful null check", false),
            ("Add pharmacy lookup endpoint", false),
            ("Bump package.json versions", false),
            ("Fix deploy script typo", false),
            ("Bump Terraform AWS provider", true),
            ("Update Helm chart values", true),
            ("infra: rotate storage keys", true),
            ("Add ARM template for queue", true),
            ("k8s: raise memory limit", true),
        ] {
            assert_eq!(is_infrastructure(title), expected, "{title}");
        }
    }

    #[test]
    fn bots() {
        for (ident, expected) in [
            ("jane@example.com", false),
            ("talbot", false),
            ("dependabot[bot]", true),
            ("github-actions", true),
            ("build\\0f1e2d3c", true),
            ("vstfs:///classification/teamproject/x", true),
            ("", true),
        ] {
            assert_eq!(is_bot(ident, false), expected, "{ident}");
        }
        assert!(is_bot("jane@example.com", true));
    }

    #[test]
    fn identity_is_trimmed_lowercase() {
        assert_eq!(identity(Some("  Jane@Example.COM ")), "jane@example.com");
        assert_eq!(identity(None), "");
    }

    #[test]
    fn parse_time_formats() {
        let t = |s| parse_time(Some(s)).map(|t| t.to_string());
        assert_eq!(
            t("2016-11-01T16:28:08.8900118Z").as_deref(),
            Some("2016-11-01T16:28:08.890011+00:00")
        );
        assert_eq!(
            t("2026-09-01T09:00:00Z").as_deref(),
            Some("2026-09-01T09:00:00+00:00")
        );
        assert_eq!(
            t("2026-09-01T10:00:00+01:00").as_deref(),
            Some("2026-09-01T09:00:00+00:00")
        );
        assert_eq!(
            t("2026-09-01T09:00:00").as_deref(),
            Some("2026-09-01T09:00:00+00:00")
        );
        assert_eq!(t("0001-01-01T00:00:00"), None);
        assert_eq!(parse_time(Some("")), None);
        assert_eq!(parse_time(None), None);
    }
}
