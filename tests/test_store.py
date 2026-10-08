"""The dashboard's reads. Write rules belong to eng-health and are tested in sync/tests."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from eng_health.mock import mock_pipelines, mock_pull_requests
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
    # closing(): a connection's own context manager commits but never closes.
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        c.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(SchemaError):
        Store(path)


def test_sample_data_fits_the_schema(tmp_path: Path) -> None:
    """mock.py stands in for synced data, so it must fit the tables in schema.sql."""
    db = WritableStore(tmp_path / "db.sqlite")
    prs, people = mock_pull_requests()
    jobs, failures = mock_pipelines()
    db.upsert(prs, people)
    db.upsert_jobs(jobs)
    db.upsert_test_failures((f["repo_id"], f["run_id"], f["test_id"]) for f in failures)

    assert len(db.pull_requests()) == len(prs)
    stored = db.pipeline_jobs()
    assert len(stored) == len(jobs)  # keys are unique
    assert set(stored.columns) == set(jobs[0])  # no column missing or extra
    assert not db.test_failures().empty
