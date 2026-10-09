"""Pipeline metrics and the Pipelines view."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from eng_health import pipelines as pl
from eng_health.config import ConfigError, Settings
from eng_health.mock import FLAKY_TESTS, mock_pipelines

from .seed import WritableStore
from .test_app import run


def job(
    run_id: int, attempt: int, conclusion: str, name: str = "test", **kw: object
) -> dict[str, Any]:
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
        "runner": "linux",
        "is_private": 1,
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


def test_a_selection_without_failures_has_no_flaky_jobs() -> None:
    # Used to crash: the join on an empty frame left "repository" as an index level too.
    assert pl.flaky_jobs(pl.prepare(pd.DataFrame([job(1, 1, "success")]))).empty


def test_flaky_tests(jobs: pd.DataFrame) -> None:
    failures = pd.DataFrame(
        [("1", 1, "Api.Retried"), ("1", 2, "Api.SameCommit")],
        columns=["repo_id", "run_id", "test_id"],
    )
    # Run 1 passed on a rerun; run 2 failed and nothing else ran on its commit.
    assert pl.flaky_tests(failures, pl.attempts(jobs))["test_id"].tolist() == ["Api.Retried"]

    # Another run of the workflow passing on run 2's commit makes its failure flaky too.
    later = pl.prepare(pd.DataFrame([job(5, 1, "success", commit_sha="sha2")]))
    att = pl.attempts(pd.concat([jobs, later]))
    assert sorted(pl.flaky_tests(failures, att)["test_id"]) == ["Api.Retried", "Api.SameCommit"]


def test_durations_use_successful_final_attempts(jobs: pd.DataFrame) -> None:
    d = pl.durations(pl.attempts(jobs))
    assert d.loc["CI", "Runs"] == 2
    assert d.loc["CI", "Median (min)"] == pytest.approx(10)


def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")


def test_pipelines_view_renders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live(monkeypatch)
    WritableStore(tmp_path / "eng_health.db").upsert_jobs(ROWS)
    at = run()
    at.sidebar.radio[0].set_value("Pipelines").run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["Overview", "Slow", "Minutes", "Reruns", "Flaky"]
    assert at.metric[0].value == "4"  # runs
    assert at.metric[1].value == "50%"
    assert any("No test results found" in i.value for i in at.info)


def test_flaky_tests_view(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live(monkeypatch)
    db = WritableStore(tmp_path / "eng_health.db")
    db.upsert_jobs(ROWS)
    db.upsert_test_failures([("1", 1, "Api.Flaky")])
    at = run()
    at.sidebar.radio[0].set_value("Pipelines").run()
    assert not at.exception, at.exception
    assert at.metric[3].value == "1 / 1"


def test_pipelines_view_without_data(monkeypatch: pytest.MonkeyPatch) -> None:
    live(monkeypatch)
    at = run()
    at.sidebar.radio[0].set_value("Pipelines").run()
    assert any("No pipeline data yet" in i.value for i in at.info)


def test_pipelines_view_in_sample_mode() -> None:
    at = run()
    at.sidebar.radio[0].set_value("Pipelines").run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["Overview", "Slow", "Minutes", "Reruns", "Flaky"]
    flaky_jobs, flaky_tests = at.metric[3].value.split(" / ")
    assert int(flaky_jobs) > 0
    assert int(flaky_tests) > 0


def test_sample_pipelines_cover_every_view() -> None:
    rows, failure_rows = mock_pipelines()
    jobs, failures = pl.prepare(pd.DataFrame(rows)), pd.DataFrame(failure_rows)
    att = pl.attempts(jobs)
    tests = pl.flaky_tests(failures, att)
    assert set(tests["test_id"]) == set(FLAKY_TESTS)  # broken tests never pass, so never flaky
    assert not pl.rerun_cost(att).empty
    assert not pl.flaky_jobs(jobs).empty
    assert 0 < pl.failure_rate(att)["failed"].mean() < 0.5


def test_billed_minutes_round_up_and_public_repos_run_free() -> None:
    rows = [
        job(1, 1, "success", runner="linux", is_private=1),  # 10 minutes
        job(2, 1, "success", runner="macos", is_private=1),
        job(3, 1, "success", runner="linux", is_private=0),  # public: free
        job(4, 1, "cancelled", runner="self-hosted", is_private=1),  # self-hosted: free
    ]
    rows[0]["finished_at"] = (
        pd.Timestamp(rows[0]["started_at"]) + pd.Timedelta(seconds=541)
    ).isoformat()
    b = pl.billed(pl.prepare(pd.DataFrame(rows)), Settings.from_env({}).ci_prices)
    assert b["billed"].tolist() == [10, 10, 10, 10]  # 9:01 bills as 10 minutes
    assert b["cost"].round(3).tolist() == [0.06, 0.62, 0.0, 0.0]

    later = pd.Timestamp(rows[3]["started_at"]) + pd.Timedelta(days=1)
    table = pl.minutes_by_workflow(b, later, days=2)  # runs 3 and 4 recent, 1 and 2 before
    assert table[["Minutes", "Before"]].values.tolist() == [[20, 20]]
    assert table["Change"].tolist() == [0.0]


def test_ci_prices_can_be_overridden() -> None:
    prices = Settings.from_env({"CI_MINUTE_PRICES": "linux=0.004, Windows=0.02"}).ci_prices
    assert (prices["linux"], prices["windows"], prices["macos"]) == (0.004, 0.02, 0.062)
    with pytest.raises(ConfigError):
        Settings.from_env({"CI_MINUTE_PRICES": "linux=cheap"})
