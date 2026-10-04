//! Azure DevOps payloads must convert to exactly what the Python code produced
//! (testdata/expected/azure).

use std::fs;
use std::path::PathBuf;

use pretty_assertions::assert_eq;
use prsync::model::{Platform, Repo};
use prsync::source::People;
use prsync::source::azure::convert;
use prsync::source::azure::types::{PullRequestInfo, Thread};
use serde_json::Value;

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

        let expected: Value = serde_json::from_str(
            &fs::read_to_string(root.join(format!("expected/azure/{case}.json"))).unwrap(),
        )
        .unwrap();
        assert_eq!(
            serde_json::to_value(&got).unwrap(),
            expected["pull_request"],
            "{case}"
        );
        assert_eq!(
            serde_json::to_value(&people).unwrap(),
            expected["people"],
            "{case} people"
        );
        checked += 1;
    }
    assert!(checked >= 7, "only {checked} fixtures");
}
