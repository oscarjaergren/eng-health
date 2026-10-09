//! Identity, bot and infrastructure rules.

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

// Files that change by the thousand without anyone writing them: lock files, generated and
// minified code, snapshots, vendored folders. Left out of PR size, which should mean lines a
// person wrote and a reviewer read.
static NOISE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?ix)
        (^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?
             |Cargo\.lock|uv\.lock|poetry\.lock|Pipfile\.lock|composer\.lock|Gemfile\.lock
             |go\.sum|packages\.lock\.json|flake\.lock|pubspec\.lock|Podfile\.lock|mix\.lock
             |mise\.lock|\.terraform\.lock\.hcl)$
        | \.(min\.js|min\.css|map|snap|pb\.go|designer\.cs|g\.cs|g\.i\.cs)$
        | _pb2(_grpc)?\.pyi?$ | ModelSnapshot\.cs$
        | (^|/)(vendor|node_modules|third_party|__snapshots__|generated)/",
    )
    .expect("valid regex")
});

const KNOWN_BOTS: [&str; 4] = ["github-actions", "dependabot", "renovate", "copilot"];

#[must_use]
pub(crate) fn is_infrastructure(title: &str) -> bool {
    INFRA.is_match(title)
}

#[must_use]
pub(crate) fn is_noise(path: &str) -> bool {
    NOISE.is_match(path)
}

#[must_use]
pub(crate) fn identity(value: Option<&str>) -> String {
    value.unwrap_or_default().trim().to_lowercase()
}

#[must_use]
pub(crate) fn is_bot(ident: &str, is_group: bool) -> bool {
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
    fn noise_is_generated_or_locked_not_written() {
        for path in [
            "package-lock.json",
            "web/yarn.lock",
            "sync/Cargo.lock",
            "go.sum",
            ".config/mise.lock",
            "infra/.terraform.lock.hcl",
            "app/static/app.min.js",
            "src/__snapshots__/view.test.ts.snap",
            "Data/Migrations/20260101_Init.Designer.cs",
            "Data/Migrations/AppDbContextModelSnapshot.cs",
            "api/orders_pb2.py",
            "vendor/github.com/x/y.go",
        ] {
            assert!(is_noise(path), "{path}");
        }
        for path in [
            "src/lock.rs",
            "docs/lockfiles.md",
            "Services/OrderDesigner.cs",
            "src/generator.py",
            "README.md",
        ] {
            assert!(!is_noise(path), "{path}");
        }
    }

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
