//! GraphQL payloads must convert to exactly the expected records in
//! testdata/expected/github (`UPDATE_GOLDENS=1` rewrites them).

use std::fs;
use std::path::PathBuf;

use eng_health::model::{Platform, Repo};
use eng_health::source::People;
use eng_health::source::github::convert;
use eng_health::source::github::types::PrNode;
use serde_json::Value;

mod support;

#[test]
fn graphql_fixtures_match_python_goldens() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../testdata");
    let mut checked = 0;
    for entry in fs::read_dir(root.join("github")).unwrap() {
        let path = entry.unwrap().path();
        let name = path.file_name().unwrap().to_str().unwrap();
        let Some(case) = name.strip_suffix(".graphql.json") else {
            continue;
        };

        let fixture: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        let node: PrNode = serde_json::from_value(fixture["node"].clone()).unwrap();
        let repo = Repo {
            platform: Platform::Github,
            id: fixture["repo"]["id"].as_str().unwrap().to_owned(),
            name: fixture["repo"]["name"].as_str().unwrap().to_owned(),
            raw: Value::Null,
        };
        let mut people = People::new();
        let pr = convert(
            &node,
            &repo,
            fixture["complete"].as_bool().unwrap(),
            &mut people,
        );

        support::check_golden(
            &root.join(format!("expected/github/{case}.json")),
            &serde_json::to_value(&pr).unwrap(),
            &serde_json::to_value(&people).unwrap(),
        );
        checked += 1;
    }
    assert!(checked >= 5, "only {checked} fixtures");
}
