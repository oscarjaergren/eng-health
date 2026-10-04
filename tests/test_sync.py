"""Sync behaviour against a fake platform, including the review-data regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from pr_analytics.store import Store
from pr_analytics.sync import OVERLAP, sync

from .helpers import FakeClient


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "db.sqlite")


def comments(store: Store) -> dict[int, dict[str, int]]:
    return {pr.number: pr.comment_counts for pr in store.pull_requests()}


def test_first_sync_saves_everything(store: Store) -> None:
    client = FakeClient()
    client.add(
        "web", 1, issue_comments=[{"user": {"login": "bob"}, "created_at": "2026-09-01T10:00:00Z"}]
    )
    client.add("api", 1)
    [report] = sync([client], store)
    assert report.ok and report.saved == 2
    assert client.since_seen == [None, None]
    assert len(store.pull_requests()) == 2  # same number, different repos


def test_resync_does_not_erase_review_data_of_unchanged_prs(store: Store) -> None:
    client = FakeClient()
    client.add(
        "web", 1, issue_comments=[{"user": {"login": "bob"}, "created_at": "2026-09-01T10:00:00Z"}]
    )
    sync([client], store)
    client.fetched.clear()

    sync([client], store)

    assert client.fetched == []
    assert comments(store) == {1: {"bob": 1}}


def test_changed_pr_is_refetched(store: Store) -> None:
    client = FakeClient()
    client.add("web", 1)
    sync([client], store)
    client.prs["web"][0].update(
        updated_at="2026-09-03T09:00:00Z",
        issue_comments=[{"user": {"login": "carol"}, "created_at": "2026-09-03T09:00:00Z"}],
    )
    sync([client], store)
    assert comments(store) == {1: {"carol": 1}}


def test_failed_details_are_saved_as_incomplete_and_retried(store: Store) -> None:
    client = FakeClient()
    client.add(
        "web", 1, issue_comments=[{"user": {"login": "bob"}, "created_at": "2026-09-01T10:00:00Z"}]
    )
    client.failing_details = {1}
    [report] = sync([client], store)
    assert report.incomplete == 1
    assert store.pull_requests()[0].details_complete is False

    client.failing_details = set()
    sync([client], store)
    [pr] = store.pull_requests()
    assert pr.details_complete and pr.comment_counts == {"bob": 1}


def test_incremental_sync_starts_before_last_success(store: Store) -> None:
    client = FakeClient()
    sync([client], store)
    last = store.sync_state("github").last_sync
    assert last is not None
    client.since_seen.clear()
    sync([client], store)
    assert client.since_seen == [last - OVERLAP] * 2

    client.since_seen.clear()
    sync([client], store, full=True)
    assert client.since_seen == [None, None]


def test_repo_failure_does_not_advance_sync_window(store: Store) -> None:
    client = FakeClient()
    sync([client], store)
    before = store.sync_state("github").last_sync
    client.failing_repos = {"api"}
    [report] = sync([client], store)
    state = store.sync_state("github")
    assert not report.ok
    assert state.last_sync == before
    assert "api" in (state.last_error or "")


def test_auth_failure_is_reported_not_raised(store: Store) -> None:
    client = FakeClient()
    client.auth_broken = True
    [report] = sync([client], store)
    assert not report.ok
    assert "credentials" in (store.sync_state("github").last_error or "")
