"""Render the real dashboard and CLI end to end, without network access."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from eng_health.cli import main as cli
from eng_health.dashboard.views import VIEWS
from eng_health.mock import mock_pull_requests
from eng_health.period import PERIODS

from .seed import WritableStore
from .test_sync import fake_binary

APP = str(Path(__file__).parent.parent / "dashboard_main.py")


def run(view: str = "today") -> AppTest:
    """The app as it first opens (Today), then switched to `view`."""
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    if view != "today":
        at.segmented_control(key="view").set_value(view).run()
        assert not at.exception, at.exception
    return at


def text(at: AppTest) -> str:
    return " ".join(e.value for e in [*at.markdown, *at.caption, *at.info, *at.title, *at.header])


def numbers(at: AppTest) -> dict[str, str]:
    """The strip of numbers at the top of a view: label to value."""
    cell = r'kpi-label">([^<]*)</div><div class="kpi-row"><span class="kpi-value">([^<]*)<'
    return dict(re.findall(cell, text(at)))


def test_sample_data_renders_every_view_in_every_period() -> None:
    at = run()
    assert at.button(key="sample").label == "Sample data · Connect"
    assert "need a look" in at.title[0].value
    for period in PERIODS:
        at.segmented_control(key="period").set_value(period).run()
        for view in VIEWS:
            at.segmented_control(key="view").set_value(view).run()
            assert not at.exception, (period, view, at.exception)
            assert view == "today" or at.header, (period, view)


def test_the_url_picks_the_view_and_period() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    # Bound widgets with a format_func read their label from the URL, not the value.
    at.query_params["view"] = "Review"
    at.query_params["period"] = "30D"
    at.run()
    assert at.header[0].value == "Is review the bottleneck?"
    assert "vs prior 30 days" in text(at)


def test_handled_items_move_to_cleared_and_back() -> None:
    at = run()
    count = int(at.title[0].value.split()[0])
    done = next(b for b in at.button if b.key and b.key.startswith("done "))
    done.click().run()
    assert at.title[0].value.startswith(f"{count - 1} ")
    restore = next(b for b in at.button if b.key and b.key.startswith("restore "))
    restore.click().run()
    assert at.title[0].value.startswith(f"{count} ")


def test_clear_filters_resets_them() -> None:
    at = run()
    at.toggle(key="bots").set_value(True).run()
    at.checkbox(key="state|abandoned|0").check().run()
    assert at.query_params["state"] == ["open", "merged", "abandoned"]
    at.button(key="clear").click().run()
    assert not at.toggle(key="bots").value
    states = [at.checkbox(key=f"state|{s}|1").value for s in ("open", "merged", "abandoned")]
    assert states == [True, True, False]
    assert "state" not in at.query_params
    # The checkboxes from before Clear filters are gone, so their old values can't come back.
    at.toggle(key="drafts").set_value(False).run()
    assert "state" not in at.query_params


def test_the_repository_search_filters_by_id() -> None:
    at = run("shipping")
    at.segmented_control(key="period").set_value("12m").run()
    at.multiselect(key="repo|0").set_value(["github:gi-docs-site"]).run()
    assert at.query_params["repo"] == "github:gi-docs-site"  # one value comes back unwrapped
    names = re.findall(r'<span class="c-t">([^<]*)</span>', text(at))
    assert names == ["docs-site"]  # the By repository table


def test_the_scope_starts_on_mine_and_remembers_a_change(tmp_path: Path) -> None:
    at = run()
    assert at.selectbox(key="scope").value == "mine"
    at.selectbox(key="scope").set_value("all").run()
    assert json.loads((tmp_path / "dashboard.json").read_text()) == {"scope": "all"}
    # A new visit opens where the last one left off.
    assert run().selectbox(key="scope").value == "all"


def test_without_knowing_who_you_are_there_is_no_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prs, people = mock_pull_requests(count=60)
    WritableStore(tmp_path / "eng_health.db").upsert(prs, people)
    monkeypatch.setenv("AZURE_DEVOPS_ORGANIZATION", "org")
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat")
    at = run()
    assert not [s for s in at.selectbox if s.key == "scope"]


def test_a_chip_starts_from_the_url() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["state"] = "all"  # nothing ticked, which is every state
    at.run()
    assert not any(at.checkbox(key=f"state|{s}|0").value for s in ("open", "merged", "abandoned"))


def test_live_mode_with_empty_store_offers_first_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    at = run()
    assert "Nothing synced yet" in text(at)
    assert "Not synced yet" in text(at)
    assert at.button(key="first_sync")


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
    at.button(key="first_sync").click().run()
    assert not at.exception, at.exception
    assert at.status[0].label == "Sync finished"
    assert "2 API requests" in text(at)
    # The top bar reflects the sync that just ran, not the state before it.
    assert "Synced just now" in text(at)
    assert at.title[0].value.endswith("a look")
    at.button(key="sync_now").click().run()
    assert at.status[0].label == "Sync finished"


def test_sync_errors_are_shown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live_github(monkeypatch, tmp_path, "errors")
    at = run()
    at.button(key="first_sync").click().run()
    assert at.status[0].label == "Sync finished with errors"
    assert any("502" in e.value for e in at.error)
    assert "Last sync failed" in text(at)


def test_sync_config_problem_is_shown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live_github(monkeypatch, tmp_path, "config")
    at = run()
    at.button(key="first_sync").click().run()
    assert at.status[0].label == "Sync failed"
    assert any("GITHUB_OWNER" in e.value for e in at.error)


def test_missing_sync_engine_is_explained(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live_github(monkeypatch, tmp_path)
    monkeypatch.setenv("ENG_HEALTH_BIN", str(tmp_path / "nope"))
    at = run()
    at.button(key="first_sync").click().run()
    assert any("eng-health" in e.value and "cargo build" in e.value for e in at.error)


def test_azure_devops_alone_has_no_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prs, people = mock_pull_requests(count=60)
    WritableStore(tmp_path / "eng_health.db").upsert(prs, people)
    monkeypatch.setenv("AZURE_DEVOPS_ORGANIZATION", "org")
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat")
    at = run()
    assert list(numbers(at)) == ["Wait for first review", "Time to merge", "PRs merged"]
    at.segmented_control(key="view").set_value("ci").run()
    assert "Connect GitHub" in text(at)


def test_bad_config_is_shown_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert "GITHUB_OWNER" in at.error[0].value


def test_cli_export(tmp_path: Path) -> None:
    prs, people = mock_pull_requests(count=20)
    WritableStore(tmp_path / "eng_health.db").upsert(prs, people)
    out = tmp_path / "prs.csv"
    assert cli(["export", str(out)]) == 0
    assert len(pd.read_csv(out)) == 20
