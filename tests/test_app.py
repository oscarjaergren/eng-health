"""Render the real dashboard and CLI end to end, without network access."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from eng_health.cli import main as cli
from eng_health.mock import mock_pull_requests

from .seed import WritableStore
from .test_sync import fake_binary

APP = str(Path(__file__).parent.parent / "dashboard_main.py")


def run() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def test_sample_data_renders_every_tab() -> None:
    at = run()
    assert "sample data" in at.sidebar.info[0].value
    tabs = [t.label for t in at.tabs]
    assert tabs == ["Overview", "Flow", "Size", "People", "Timing", "Data"]
    assert at.metric[0].value != "0"
    size = at.tabs[tabs.index("Size")]
    assert size.dataframe[0].value["PRs"].sum() > 0


def test_filters_survive_in_the_url() -> None:
    at = run()
    at.sidebar.toggle[0].set_value(True).run()
    assert not at.exception
    assert at.query_params["infra"] == "1"


def test_live_mode_with_empty_store_offers_first_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    at = run()
    assert any("No pull requests synced yet" in i.value for i in at.info)
    assert "never" in " ".join(c.value for c in at.sidebar.caption)


def live_github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scenario: str = "ok") -> None:
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("ENG_HEALTH_BIN", fake_binary(tmp_path))
    monkeypatch.setenv("FAKE_SYNC", scenario)


def test_sync_button_runs_the_sync_and_shows_the_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live_github(monkeypatch, tmp_path)
    at = run()
    at.sidebar.button[0].click().run()
    assert not at.exception, at.exception
    assert at.status[0].label == "Sync finished"
    assert "2 API requests" in " ".join(m.value for m in at.markdown)
    # The sidebar reflects the sync that just ran, not the state before it.
    assert "Last synced just now" in " ".join(c.value for c in at.sidebar.caption)
    assert len(at.tabs) == 6
    # The infrastructure PR is hidden by default.
    assert "1 of 2 PRs match" in " ".join(c.value for c in at.sidebar.caption)


def test_sync_errors_are_shown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live_github(monkeypatch, tmp_path, "errors")
    at = run()
    at.sidebar.button[0].click().run()
    assert at.status[0].label == "Sync finished with errors"
    assert any("502" in e.value for e in at.error)


def test_sync_config_problem_is_shown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live_github(monkeypatch, tmp_path, "config")
    at = run()
    at.sidebar.button[0].click().run()
    assert at.status[0].label == "Sync failed"
    assert any("GITHUB_OWNER" in e.value for e in at.error)


def test_missing_sync_engine_is_explained(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live_github(monkeypatch, tmp_path)
    monkeypatch.setenv("ENG_HEALTH_BIN", str(tmp_path / "nope"))
    at = run()
    at.sidebar.button[0].click().run()
    assert any("eng-health" in e.value and "cargo build" in e.value for e in at.error)


def test_live_mode_reads_the_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prs, people = mock_pull_requests(count=60)
    WritableStore(tmp_path / "eng_health.db").upsert(prs, people)
    monkeypatch.setenv("AZURE_DEVOPS_ORGANIZATION", "org")
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat")
    at = run()
    assert len(at.tabs) == 6


def test_bad_config_is_shown_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    at = run()
    assert "GITHUB_OWNER" in at.error[0].value


def test_cli_export(tmp_path: Path) -> None:
    prs, people = mock_pull_requests(count=20)
    WritableStore(tmp_path / "eng_health.db").upsert(prs, people)
    out = tmp_path / "prs.csv"
    assert cli(["export", str(out)]) == 0
    assert len(pd.read_csv(out)) == 20
