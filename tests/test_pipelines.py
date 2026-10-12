"""Pipeline metrics and the CI view."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from eng_health import pipelines as pl
from eng_health.config import ConfigError, Settings
from eng_health.mock import FLAKY_TESTS, mock_pipelines, mock_pull_requests
from eng_health.period import PERIODS, Period

from .seed import WritableStore
from .test_app import numbers, run, text


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
    # Default branch, cancelled excluded: run 1 passed on 8 September, run 2 failed on the 9th.
    rates = pl.failure_rate(att, PERIODS["7d"], pd.Timestamp("2026-09-12T00:00Z"), "UTC")
    assert rates["CI"].dropna().tolist() == [0.0, 100.0]


def test_flaky_jobs(jobs: pd.DataFrame) -> None:
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


def live(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WritableStore:
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    return WritableStore(tmp_path / "eng_health.db")


def recent(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`rows` moved to end yesterday, so the view's 7 days include them whenever this runs."""
    shift = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1) - pd.Timestamp(rows[-1]["started_at"])
    return [
        {
            **r,
            **{k: (pd.Timestamp(r[k]) + shift).isoformat() for k in ("started_at", "finished_at")},
        }
        for r in rows
    ]


def test_ci_view_renders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live(monkeypatch, tmp_path).upsert_jobs(recent(ROWS))
    at = run("ci")
    shown = numbers(at)
    assert shown["Default-branch failures"] == "50.0%"
    assert shown["Flaky jobs"] == "1"
    assert "No test results found" in text(at)


def test_ci_view_shows_flaky_tests(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = live(monkeypatch, tmp_path)
    db.upsert_jobs(recent(ROWS))
    db.upsert_test_failures([("1", 1, "Api.Flaky")])
    at = run("ci")
    assert "↳ Api.Flaky" in text(at)  # under the job that flaked on the same run


def test_ci_view_without_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prs, people = mock_pull_requests(count=20)
    live(monkeypatch, tmp_path).upsert(prs, people)
    at = run("ci")
    assert any("No pipeline runs match" in i.value for i in at.info)


def test_sample_pipelines_cover_every_view() -> None:
    rows, failure_rows = mock_pipelines()
    jobs, failures = pl.prepare(pd.DataFrame(rows)), pd.DataFrame(failure_rows)
    att = pl.attempts(jobs)
    tests = pl.flaky_tests(failures, att)
    assert set(tests["test_id"]) == set(FLAKY_TESTS)  # broken tests never pass, so never flaky
    assert not att["final"].all()  # some runs were re-run
    assert not pl.flaky_jobs(jobs).empty
    final = att[att["final"] & att["is_default_branch"]]
    assert 0 < final["failed"].mean() < 0.5


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

    # Runs 3 and 4 fall in the last 2 days, 1 and 2 in the 2 before.
    now = pd.Timestamp(rows[3]["started_at"]) + pd.Timedelta(hours=23)
    table = pl.cost_by_repository(b, Period(2, "2 days", "D", 2), now, "UTC")
    assert table[["Minutes", "Share", "Change"]].values.tolist() == [[20, 1.0, 0.0]]


def test_ci_prices_can_be_overridden() -> None:
    prices = Settings.from_env({"CI_MINUTE_PRICES": "linux=0.004, Windows=0.02"}).ci_prices
    assert (prices["linux"], prices["windows"], prices["macos"]) == (0.004, 0.02, 0.062)
    with pytest.raises(ConfigError):
        Settings.from_env({"CI_MINUTE_PRICES": "linux=cheap"})
