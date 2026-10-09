"""The weekly digest: this week's numbers against last week's, and the movers."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from eng_health import digest
from eng_health import pipelines as pl
from eng_health.config import CI_PRICES
from eng_health.models import State

from .test_metrics import T0, frame, pr
from .test_pipelines import job

NOW = pd.Timestamp(T0) + pd.Timedelta(days=14)


def by_label(changes: list[digest.Change]) -> dict[str, object]:
    return {c.label: (c.now, c.before) for c in changes}


def test_pr_changes_compare_the_last_7_days_with_the_7_before() -> None:
    def merged(n: int, day: int) -> Any:
        created = T0 + timedelta(days=day)
        return pr(n, created_at=created, closed_at=created + timedelta(hours=10))

    df = frame(
        merged(1, 2),  # last week
        merged(2, 9),  # this week
        merged(3, 10),
        # Open since day 11 with no response: waiting over 2 days now, not a week ago.
        pr(4, created_at=T0 + timedelta(days=11), closed_at=None, state=State.OPEN),
    )
    changes = by_label(digest.pr_changes(df, NOW))
    assert changes["PRs merged"] == (2, 1)
    assert changes["PRs opened"] == (3, 1)
    assert changes["Time to merge"] == (10, 10)
    assert changes["Waiting over 2 days"] == (1, 0)


def ci_jobs() -> pd.DataFrame:
    """CI runs 10 minutes last week and 20 this week; test t fails once this week, then passes."""
    rows = []
    for run_id in range(1, 15):
        minutes = 20 if run_id > 7 else 10
        row = job(run_id, 1, "success")
        start = pd.Timestamp(row["started_at"])
        rows.append({**row, "finished_at": (start + pd.Timedelta(minutes=minutes)).isoformat()})
    rows.append(job(13, 2, "success"))  # run 13 was re-run after attempt 1 failed
    rows[12] = {**rows[12], "conclusion": "failure"}
    return pl.prepare(pd.DataFrame(rows))


def test_ci_changes_and_movers() -> None:
    jobs = ci_jobs()
    failures = pd.DataFrame([{"repo_id": "1", "run_id": 13, "test_id": "t"}])
    now = pd.Timestamp("2026-09-07T10:00:00Z") + pd.Timedelta(days=14, hours=1)

    changes = by_label(digest.ci_changes(jobs, failures, CI_PRICES, now))
    assert changes["Runs"] == (7, 7)
    assert changes["Flaky tests"] == (1, 0)
    assert changes["CI minutes"] == (150, 70)  # 7 runs of 20, the failed attempt's 10; 7 of 10

    moved = digest.movers(jobs, failures, CI_PRICES, now)
    assert moved[0] == "New flaky test: t"
    assert "CI (web) runs 100% slower: median 10.0 → 20.0 min" in moved
    assert "CI (web) used 114% more CI minutes: 70 → 150" in moved
