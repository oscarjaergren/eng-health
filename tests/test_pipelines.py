"""Pipeline metrics and the Pipelines view."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pr_analytics import pipelines as pl

from .seed import WritableStore
from .test_app import run


def job(run_id: int, attempt: int, conclusion: str, name: str = "test", **kw: object) -> dict:
    start = pd.Timestamp("2026-09-07T10:00:00Z") + pd.Timedelta(days=run_id, hours=attempt)
    row = {
        "key": f"github:1:{run_id}:{attempt}:{name}",
        "repo_id": "1",
        "repository": "web",
        "pipeline": "CI",
        "run_id": run_id,
        "attempt": attempt,
        "branch": "main",
        "is_default_branch": 1,
        "commit_sha": f"sha{run_id}",
        "name": name,
        "conclusion": conclusion,
        "started_at": start.isoformat(),
        "finished_at": (start + pd.Timedelta(minutes=10)).isoformat(),
        "url": f"https://github.com/o/web/actions/runs/{run_id}",
    }
    return {**row, **kw}


ROWS = [
    job(1, 1, "failure"),  # failed, then passed on rerun: flaky
    job(1, 2, "success"),
    job(2, 1, "failure"),  # failed and never re-run: a real failure
    job(3, 1, "cancelled"),  # cancelled: neither failure nor success
    job(4, 1, "success", branch="feature", is_default_branch=0),
]


@pytest.fixture
def jobs() -> pd.DataFrame:
    return pl.prepare(pd.DataFrame(ROWS))


def test_attempts_and_failure_rate(jobs: pd.DataFrame) -> None:
    att = pl.attempts(jobs)
    final = att[att["final"]].set_index("run_id")["conclusion"].to_dict()
    assert final == {1: "success", 2: "failure", 3: "cancelled", 4: "success"}
    # Default branch, cancelled excluded: run 1 passed, run 2 failed.
    assert pl.failure_rate(att)["failed"].tolist() == [0.5]


def test_rerun_cost_and_flaky_jobs(jobs: pd.DataFrame) -> None:
    att = pl.attempts(jobs)
    assert pl.rerun_cost(att)["hours"].sum() == pytest.approx(10 / 60)
    flaky = pl.flaky_jobs(jobs)
    assert flaky[["name", "flaky_runs", "minutes_lost"]].values.tolist() == [["test", 1, 10.0]]


def test_durations_use_successful_final_attempts(jobs: pd.DataFrame) -> None:
    d = pl.durations(pl.attempts(jobs))
    assert d.loc["CI", "Runs"] == 2
    assert d.loc["CI", "Median (min)"] == pytest.approx(10)


def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")


def test_pipelines_view_renders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live(monkeypatch)
    WritableStore(tmp_path / "pr_analytics.db").upsert_jobs(ROWS)
    at = run()
    at.sidebar.radio[0].set_value("Pipelines").run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["Overview", "Slow", "Reruns", "Flaky"]
    assert at.metric[0].value == "4"  # runs
    assert at.metric[1].value == "50%"


def test_pipelines_view_without_data(monkeypatch: pytest.MonkeyPatch) -> None:
    live(monkeypatch)
    at = run()
    at.sidebar.radio[0].set_value("Pipelines").run()
    assert any("No pipeline data yet" in i.value for i in at.info)


def test_pipelines_view_in_sample_mode() -> None:
    at = run()
    at.sidebar.radio[0].set_value("Pipelines").run()
    assert not at.exception
    assert any("GitHub Actions" in i.value for i in at.info)
