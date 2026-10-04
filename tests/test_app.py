"""Render the real dashboard and CLI end to end, without network access."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from pr_analytics.cli import main as cli
from pr_analytics.mock import mock_pull_requests
from pr_analytics.store import Store

from .helpers import FakeClient

APP = str(Path(__file__).parent.parent / "dashboard_main.py")
CREDENTIAL_VARS = ["AZURE_DEVOPS_ORGANIZATION", "AZURE_DEVOPS_PAT", "GITHUB_OWNER", "GITHUB_TOKEN"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for var in [*CREDENTIAL_VARS, "MOCK_MODE", "IDENTITY_ALIASES"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # keep a developer's .env out of the test


def run() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def test_sample_data_renders_every_tab() -> None:
    at = run()
    assert "sample data" in at.sidebar.info[0].value
    assert [t.label for t in at.tabs] == ["Overview", "Flow", "People", "Timing", "Data"]
    assert at.metric[0].value != "0"


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


def test_sync_button_fills_an_empty_store(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    fake.add("web", 1)
    fake.add("api", 1, title="Bump Terraform provider")
    monkeypatch.setattr("pr_analytics.dashboard.data.make_clients", lambda settings: [fake])
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    at = run()
    at.sidebar.button[0].click().run()
    assert not at.exception, at.exception
    assert at.status[0].label == "Sync finished"
    assert len(at.tabs) == 5
    assert "1 of 2 PRs match" in " ".join(c.value for c in at.sidebar.caption)


def test_live_mode_reads_the_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prs, people = mock_pull_requests(count=60)
    Store(tmp_path / "pr_analytics.db").upsert(prs, people)
    monkeypatch.setenv("AZURE_DEVOPS_ORGANIZATION", "org")
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat")
    at = run()
    assert len(at.tabs) == 5


def test_bad_config_is_shown_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    at = run()
    assert "GITHUB_OWNER" in at.error[0].value


def test_cli_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prs, people = mock_pull_requests(count=20)
    Store(tmp_path / "pr_analytics.db").upsert(prs, people)
    out = tmp_path / "prs.csv"
    assert cli(["export", str(out)]) == 0
    assert len(pd.read_csv(out)) == 20


def test_cli_sync_without_credentials_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(["sync"]) == 2
    assert "No platform configured" in capsys.readouterr().err
