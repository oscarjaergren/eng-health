//! Azure DevOps payloads must convert to exactly the expected records in
//! testdata/expected/azure (`UPDATE_GOLDENS=1` rewrites them).

use std::fs;
use std::path::PathBuf;

use eng_health::model::{Platform, Repo};
use eng_health::source::People;
use eng_health::source::azure::convert;
use eng_health::source::azure::types::{PullRequestInfo, Thread};
use serde_json::Value;

mod support;

#[test]
fn azure_fixtures_match_python_goldens() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../testdata");
    let mut checked = 0;
    for entry in fs::read_dir(root.join("azure")).unwrap() {
        let path = entry.unwrap().path();
        let case = path.file_stem().unwrap().to_str().unwrap().to_owned();
        let fixture: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();

        let pr: PullRequestInfo = serde_json::from_value(fixture["pr"].clone()).unwrap();
        // `threads: null` stands for a failed fetch, as in the Python fixtures.
        let threads: Option<Vec<Thread>> =
            serde_json::from_value(fixture["pr"]["threads"].clone()).unwrap();
        let repo = Repo {
            platform: Platform::AzureDevops,
            id: fixture["repo"]["id"].as_str().unwrap().to_owned(),
            name: fixture["repo"]["name"].as_str().unwrap().to_owned(),
            raw: fixture["repo"]["raw"].clone(),
        };
        let mut people = People::new();
        let got = convert(&pr, threads.as_deref(), &repo, &mut people);

        support::check_golden(
            &root.join(format!("expected/azure/{case}.json")),
            &serde_json::to_value(&got).unwrap(),
            &serde_json::to_value(&people).unwrap(),
        );
        checked += 1;
    }
    assert!(checked >= 7, "only {checked} fixtures");
}
