# Security policy

## Reporting a vulnerability

Report it privately through this repository's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability),
not a public issue.

## What the repository does

Secrets are scanned on commit, across the full history in CI, and by GitHub's push protection.
CodeQL analyses the Python, the Rust and the workflows; dependencies are audited against their
locks, and actions are pinned to commit SHAs. Artifacts downloaded for test results are size
capped before and after decompression. Details: [build-gates.md](../docs/build-gates.md).

## What you must do

- **Don't expose the dashboard.** It has no authentication, and it shows PR titles and people's
  names. Run it locally or behind something that authenticates.
- **Give the tokens read access only**: an Azure DevOps PAT with Code (Read), and a GitHub token
  that can read the repositories and their Actions runs.
