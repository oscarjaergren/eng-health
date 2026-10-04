//! GraphQL payloads must convert to exactly what the Python code produced from
//! the equivalent REST payloads (testdata/expected/github).

use std::fs;
use std::path::PathBuf;

use pretty_assertions::assert_eq;
use prsync::model::{Platform, Repo};
use prsync::source::People;
use prsync::source::github::convert;
use prsync::source::github::types::PrNode;
use serde_json::Value;

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

        let expected: Value = serde_json::from_str(
            &fs::read_to_string(root.join(format!("expected/github/{case}.json"))).unwrap(),
        )
        .unwrap();
        assert_eq!(
            serde_json::to_value(&pr).unwrap(),
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
    assert!(checked >= 5, "only {checked} fixtures");
}
