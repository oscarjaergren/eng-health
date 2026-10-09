#![expect(
    clippy::unwrap_used,
    reason = "test helpers panic, like the tests that call them"
)]
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use chrono::{Duration, TimeZone, Utc};
use eng_health::{Platform, PullRequest};
use eng_health::{SCHEMA_VERSION, Store, StoreError, SyncState};
use rusqlite::Connection;
use tempfile::TempDir;

fn golden(name: &str) -> PullRequest {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../testdata/expected")
        .join(name);
    let v: serde_json::Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    serde_json::from_value(v["pull_request"].clone()).unwrap()
}

/// The dashboard reads these tables directly, so tests check them the same way.
fn db(dir: &TempDir) -> Connection {
    Connection::open(dir.path().join("db.sqlite")).unwrap()
}

fn store() -> (TempDir, Store) {
    let dir = TempDir::new().unwrap();
    let s = Store::open(&dir.path().join("db.sqlite")).unwrap();
    (dir, s)
}

#[test]
fn same_number_in_two_repositories_is_two_rows() {
    let (_d, mut s) = store();
    let a = golden("github/abandoned.json");
    let mut b = a.clone();
    b.repo_id = "202".into();
    s.upsert(&[a, b], &BTreeMap::new()).unwrap();
    assert_eq!(s.pull_requests(None).unwrap().len(), 2);
}

#[test]
fn upsert_replaces_and_keeps_people() {
    let (dir, mut s) = store();
    let mut pr = golden("github/abandoned.json");
    s.upsert(
        &[pr.clone()],
        &BTreeMap::from([("alice".into(), "Alice".into())]),
    )
    .unwrap();
    pr.title = "new".into();
    s.upsert(&[pr], &BTreeMap::new()).unwrap();
    let all = s.pull_requests(Some(Platform::Github)).unwrap();
    assert_eq!(
        all.iter().map(|p| p.title.as_str()).collect::<Vec<_>>(),
        ["new"]
    );
    let name: String = db(&dir)
        .query_row("SELECT name FROM people WHERE id = 'alice'", [], |r| {
            r.get(0)
        })
        .unwrap();
    assert_eq!(name, "Alice");
    assert_eq!(
        s.pull_requests(Some(Platform::AzureDevops)).unwrap().len(),
        0
    );
}

#[test]
fn stored_json_is_the_golden_json() {
    let (dir, mut s) = store();
    let pr = golden("azure/vote_history.json");
    s.upsert(std::slice::from_ref(&pr), &BTreeMap::new())
        .unwrap();
    let conn = Connection::open(dir.path().join("db.sqlite")).unwrap();
    let data: String = conn
        .query_row("SELECT data FROM pull_requests", [], |r| r.get(0))
        .unwrap();
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&data).unwrap(),
        serde_json::to_value(&pr).unwrap()
    );
}

#[test]
fn failed_sync_keeps_previous_window() {
    let (_d, mut s) = store();
    let now = Utc.with_ymd_and_hms(2026, 10, 1, 12, 0, 0).unwrap();
    s.record_sync("github", now, true, None).unwrap();
    s.record_sync("github", now + Duration::hours(1), false, Some("boom"))
        .unwrap();
    let state = s.sync_state("github").unwrap();
    assert_eq!(state.last_sync, Some(now));
    assert_eq!(state.last_attempt, Some(now + Duration::hours(1)));
    assert_eq!(state.last_error.as_deref(), Some("boom"));
    assert_eq!(s.sync_state("azure_devops").unwrap(), SyncState::default());
}

#[test]
fn every_write_bumps_the_revision() {
    let (dir, mut s) = store();
    let revision = || -> i64 {
        db(&dir)
            .query_row("SELECT revision FROM meta", [], |r| r.get(0))
            .unwrap()
    };
    let v0 = revision();
    s.upsert(&[golden("github/abandoned.json")], &BTreeMap::new())
        .unwrap();
    s.record_sync("github", Utc::now(), true, None).unwrap();
    s.clear().unwrap();
    assert_eq!(revision(), v0 + 3);
    assert_eq!(s.pull_requests(None).unwrap().len(), 0);
}

#[test]
fn newer_schema_is_refused() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("db.sqlite");
    drop(Store::open(&path).unwrap());
    let conn = Connection::open(&path).unwrap();
    let v: i64 = conn
        .pragma_query_value(None, "user_version", |r| r.get(0))
        .unwrap();
    assert_eq!(v, SCHEMA_VERSION);
    conn.pragma_update(None, "user_version", SCHEMA_VERSION + 1)
        .unwrap();
    drop(conn);
    assert!(matches!(
        Store::open(&path),
        Err(StoreError::NewerSchema { .. })
    ));
}

#[test]
fn an_older_schema_forgets_sync_windows_so_everything_is_synced_again() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("db.sqlite");
    let mut s = Store::open(&path).unwrap();
    s.record_sync("github", Utc::now(), true, None).unwrap();
    drop(s);
    let conn = Connection::open(&path).unwrap();
    conn.pragma_update(None, "user_version", SCHEMA_VERSION - 1)
        .unwrap();
    drop(conn);

    let s = Store::open(&path).unwrap();
    assert!(s.sync_state("github").unwrap().last_sync.is_none());
    drop(s);
    // Stamped with the current version, so the next open keeps the windows.
    let mut s = Store::open(&path).unwrap();
    s.record_sync("github", Utc::now(), true, None).unwrap();
    drop(s);
    assert!(
        Store::open(&path)
            .unwrap()
            .sync_state("github")
            .unwrap()
            .last_sync
            .is_some()
    );
}
