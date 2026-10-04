import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from pr_analytics.store import SCHEMA_VERSION, SchemaError, Store

from .helpers import NOW, make_pr


def test_same_number_in_two_repositories_is_two_rows(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.upsert([make_pr(5, title="in web"), make_pr(5, repo_id="2", title="in api")])
    assert sorted(pr.title for pr in store.pull_requests()) == ["in api", "in web"]


def test_upsert_replaces_and_keeps_people(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.upsert([make_pr(1, title="old")], {"alice": "Alice"})
    store.upsert([make_pr(1, title="new")])
    assert [pr.title for pr in store.pull_requests()] == ["new"]
    assert store.people() == {"alice": "Alice"}


def test_failed_sync_keeps_previous_window(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.record_sync("github", NOW, succeeded=True)
    store.record_sync("github", NOW + timedelta(hours=1), succeeded=False, error="boom")
    state = store.sync_state("github")
    assert state.last_sync == NOW
    assert state.last_attempt == NOW + timedelta(hours=1)
    assert state.last_error == "boom"


def test_version_changes_after_every_write(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    v0 = store.version()
    store.upsert([make_pr()])
    store.record_sync("github", NOW, succeeded=True)
    v1 = store.version()
    store.clear()
    assert len({v0, v1, store.version()}) == 3
    assert store.pull_requests() == []


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    Store(path)
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        c.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(SchemaError):
        Store(path)
