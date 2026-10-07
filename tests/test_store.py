"""The dashboard's reads. Write rules belong to eng-health and are tested in sync/tests."""

import sqlite3
from pathlib import Path

import pytest

from eng_health.store import SCHEMA_VERSION, SchemaError, Store

from .helpers import NOW, make_pr
from .seed import WritableStore


def test_reads_pull_requests_people_and_sync_state(tmp_path: Path) -> None:
    db = WritableStore(tmp_path / "db.sqlite")
    db.upsert([make_pr(5, title="in web"), make_pr(5, repo_id="2", title="in api")], {"a": "A"})
    db.record_sync("github", NOW, succeeded=True)

    store = Store(tmp_path / "db.sqlite")
    assert sorted(pr.title for pr in store.pull_requests()) == ["in api", "in web"]
    assert store.pull_requests("azure_devops") == []
    assert store.people() == {"a": "A"}
    state = store.sync_state("github")
    assert (state.last_sync, state.last_error) == (NOW, None)
    assert store.sync_state("azure_devops").last_sync is None


def test_version_follows_writes(tmp_path: Path) -> None:
    db = WritableStore(tmp_path / "db.sqlite")
    before = Store(db.path).version()
    db.upsert([make_pr()])
    assert Store(db.path).version() > before


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    Store(path)
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        c.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(SchemaError):
        Store(path)
