"""The period's numbers against the period before, the chart buckets, and the movers."""

from __future__ import annotations

from datetime import timedelta
from functools import partial
from typing import Any

import pandas as pd
import pytest

from eng_health import digest
from eng_health import pipelines as pl
from eng_health.config import CI_PRICES
from eng_health.models import State
from eng_health.period import PERIODS

from .test_metrics import T0, frame, pr
from .test_pipelines import job

NOW = pd.Timestamp(T0) + pd.Timedelta(days=14)
WEEK = PERIODS["7d"]


def test_pr_numbers_compare_the_last_7_days_with_the_7_before() -> None:
    def merged(n: int, day: int) -> Any:
        created = T0 + timedelta(days=day)
        return pr(n, created_at=created, closed_at=created + timedelta(hours=10))

    df = frame(
        merged(1, 2),  # last week
        merged(2, 9),  # this week
        merged(3, 10),
        # Open since day 11: open now, not a week ago.
        pr(4, created_at=T0 + timedelta(days=11), closed_at=None, state=State.OPEN),
    )
    n = digest.numbers(partial(digest.pr_stats, df), WEEK, NOW, "UTC")
    assert (n.now["merged"], n.before["merged"]) == (2, 1)
    assert (n.now["opened"], n.before["opened"]) == (3, 1)
    assert (n.now["ttm"], n.before["ttm"]) == (10, 10)
    assert (n.now["open"], n.before["open"]) == (1, 0)
    assert n.now["unreviewed"] == 2
    merges = n.change("merged")
    assert merges.ratio == 1.0
    assert merges.trend == (0, 1, 1, 0, 0, 0, 0)  # 9 to 15 September, merged on the 10th and 11th


def test_buckets_are_local_calendar_periods_ending_now() -> None:
    now = pd.Timestamp("2026-10-25T12:00Z")
    labels, edges = WEEK.edges(now, "Europe/London")
    assert (labels[0], labels[-1]) == (pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-25"))
    assert edges[0] == pd.Timestamp("2026-10-18T23:00Z")  # midnight in summer time
    assert edges[-1] == now
    months, _ = PERIODS["12m"].edges(now, "UTC")
    assert (months[0], months[-1]) == (pd.Timestamp("2025-11-01"), pd.Timestamp("2026-10-01"))


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


def test_ci_numbers_movers_and_new_flaky_tests() -> None:
    jobs = ci_jobs()
    att, billed = pl.attempts(jobs), pl.billed(jobs, CI_PRICES)
    failures = pd.DataFrame([{"repo_id": "1", "run_id": 13, "test_id": "t"}])
    now = pd.Timestamp("2026-09-07T10:00:00Z") + pd.Timedelta(days=14, hours=1)

    n = digest.numbers(partial(digest.ci_stats, att, billed), WEEK, now, "UTC")
    # 7 runs of 20 minutes and run 13's 10-minute rerun, against 7 runs of 10.
    assert (n.now["minutes"], n.before["minutes"]) == (150, 70)
    assert (n.now["passed"], n.now["passed_on_rerun"], n.now["flaky"]) == (6, 1, 1)
    assert n.now["rerun_hours"] == pytest.approx(20 / 60)  # run 13's failed first attempt

    moved = digest.movers(att, billed, WEEK, now)
    assert [(m.title, m.detail, m.worse) for m in moved] == [
        ("CI minutes", "web · 70 → 150", True),
        ("CI run time", "web · median 10.0 → 20.0 min", True),
    ]
    new = digest.new_flaky_tests(failures, att, *WEEK.window(now))
    assert new["test_id"].tolist() == ["t"]
    # Flaky in run 3 too, the week before: not new.
    seen_before = pd.concat([failures, failures.assign(run_id=3)])
    assert digest.new_flaky_tests(seen_before, att, *WEEK.window(now)).empty
