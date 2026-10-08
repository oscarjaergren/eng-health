//! Shared by the parity tests.

#![expect(
    clippy::unwrap_used,
    reason = "test helpers panic, like the tests that call them"
)]

use std::fs;
use std::path::Path;

use serde_json::{Value, json};

/// Compare a conversion with its golden file, or rewrite the golden when
/// `UPDATE_GOLDENS=1` (after an intended rule change; review the diff).
pub(crate) fn check_golden(path: &Path, pull_request: &Value, people: &Value) {
    let got = json!({ "pull_request": pull_request, "people": people });
    if std::env::var_os("UPDATE_GOLDENS").is_some() {
        // Sorted keys and two-space indent, matching the files Python first wrote.
        fs::write(path, serde_json::to_string_pretty(&got).unwrap() + "\n").unwrap();
        return;
    }
    let expected: Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    pretty_assertions::assert_eq!(got, expected, "{}", path.display());
}
