//! Every expected record in testdata/ must survive a round trip through the
//! Rust model unchanged, which pins the JSON the dashboard reads.

use std::fs;
use std::path::PathBuf;

use eng_health::model::PullRequest;
use pretty_assertions::assert_eq;
use serde_json::Value;

fn expected_files() -> Vec<PathBuf> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../testdata/expected");
    let mut files: Vec<_> = ["azure", "github"]
        .iter()
        .flat_map(|dir| fs::read_dir(root.join(dir)).expect("testdata present"))
        .map(|e| e.unwrap().path())
        .collect();
    files.sort();
    files
}

#[test]
fn every_golden_round_trips_through_the_model() {
    let files = expected_files();
    assert!(files.len() >= 10, "found only {} goldens", files.len());
    for path in files {
        let golden: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        let original = golden["pull_request"].clone();
        let pr: PullRequest = serde_json::from_value(original.clone())
            .unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        assert_eq!(
            serde_json::to_value(&pr).unwrap(),
            original,
            "{}",
            path.display()
        );
    }
}

#[test]
fn key_matches_python() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../testdata/expected/azure/vote_history.json");
    let golden: Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    let pr: PullRequest = serde_json::from_value(golden["pull_request"].clone()).unwrap();
    assert_eq!(pr.key(), "azure_devops:repo-1:2");
}

#[test]
fn unknown_fields_are_rejected() {
    let mut v: Value =
        serde_json::from_str(&fs::read_to_string(&expected_files()[0]).unwrap()).unwrap();
    v["pull_request"]["surprise"] = Value::Bool(true);
    assert!(serde_json::from_value::<PullRequest>(v["pull_request"].clone()).is_err());
}
