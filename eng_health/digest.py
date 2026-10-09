"""The last 7 days against the 7 before: the headline numbers, and what moved most."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import pandas as pd

from . import metrics
from . import pipelines as pl
from .models import State

WEEK = pd.Timedelta(days=7)
# A mover has to change by this much, over at least MIN_RUNS runs in each week, to get a line.
MOVE = 0.2
MIN_RUNS = 3
MIN_MINUTES = 30


@dataclass(frozen=True)
class Change:
    label: str
    now: float | None
    before: float | None
    unit: str = ""
    # None when neither direction is good news, such as PRs opened.
    lower_is_better: bool | None = True

    @property
    def ratio(self) -> float | None:
        if self.now is None or not self.before:
            return None
        return (self.now - self.before) / self.before


def _num(x: float) -> float | None:
    return None if pd.isna(x) else float(x)


def _two(values: Iterable[float | None]) -> tuple[float | None, float | None]:
    """This week's value and last week's, from an iterable over the two weeks."""
    now, before = values
    return now, before


def _weeks(times: pd.Series, now: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    """Masks for the last 7 days and the 7 before."""
    this = (times > now - WEEK) & (times <= now)
    last = (times > now - 2 * WEEK) & (times <= now - WEEK)
    return this, last


def _waiting(df: pd.DataFrame, at: pd.Timestamp) -> float:
    """Open, non-draft PRs at `at` that had waited over two days without a response."""
    open_then = (df["created_at"] < at - pd.Timedelta(days=2)) & (
        df["closed_at"].isna() | (df["closed_at"] > at)
    )
    unanswered = df["first_review_at"].isna() | (df["first_review_at"] > at)
    return float((open_then & unanswered & ~df["is_draft"]).sum())


def pr_changes(df: pd.DataFrame, now: pd.Timestamp) -> list[Change]:
    others = metrics.comment_rows(df).groupby("key")["comments"].sum()
    merged = df[df["state"] == State.MERGED.value]
    merged = merged.assign(comments=merged["key"].map(others).fillna(0))
    opened_weeks = _weeks(df["created_at"], now)
    merged_weeks = _weeks(merged["closed_at"], now)

    def median(
        frame: pd.DataFrame, masks: tuple[pd.Series, pd.Series], col: str
    ) -> list[float | None]:
        return [_num(frame.loc[m, col].median()) for m in masks]

    def depth(m: pd.Series) -> float | None:
        week = merged[m & merged["lines"].notna()]
        lines = week["lines"].sum()
        return _num(100 * week["comments"].sum() / lines) if lines else None

    return [
        Change("PRs opened", *_two(float(m.sum()) for m in opened_weeks), lower_is_better=None),
        Change("PRs merged", *_two(float(m.sum()) for m in merged_weeks), lower_is_better=False),
        Change(
            "Wait for first review", *_two(median(df, opened_weeks, "first_review_hours")), " h"
        ),
        Change("Time to merge", *_two(median(merged, merged_weeks, "cycle_hours")), " h"),
        Change("Waiting over 2 days", _waiting(df, now), _waiting(df, now - WEEK)),
        Change("Median PR size", *_two(median(merged, merged_weeks, "lines")), " lines"),
        Change(
            "Comments per 100 lines", *_two(depth(m) for m in merged_weeks), lower_is_better=False
        ),
    ]


def _flaky_tests(failures: pd.DataFrame, att: pd.DataFrame, runs: pd.Series) -> set[str]:
    f = failures[failures["run_id"].isin(runs)]
    return set() if f.empty else set(pl.flaky_tests(f, att)["test_id"])


def ci_changes(
    jobs: pd.DataFrame, failures: pd.DataFrame, prices: Mapping[str, float], now: pd.Timestamp
) -> list[Change]:
    """`jobs` as `pipelines.prepare` returns them."""
    att = pl.attempts(jobs)
    final = att[att["final"]]
    run_weeks = _weeks(final["started"], now)
    done = final[final["is_default_branch"] & (final["conclusion"] != "cancelled")]
    billed = pl.billed(jobs, prices)
    billed_weeks = _weeks(billed["started_at"], now)
    redone = att[~att["final"]]
    return [
        Change("Runs", *_two(float(m.sum()) for m in run_weeks), lower_is_better=None),
        Change(
            "Failure rate (default branch)",
            *_two(_num(done.loc[m, "failed"].mean() * 100) for m in _weeks(done["started"], now)),
            "%",
        ),
        Change("CI minutes", *_two(float(billed.loc[m, "billed"].sum()) for m in billed_weeks)),
        Change(
            "Estimated cost", *_two(float(billed.loc[m, "cost"].sum()) for m in billed_weeks), "$"
        ),
        Change(
            "Lost to reruns",
            *_two(
                float(redone.loc[m, "minutes"].sum() / 60) for m in _weeks(redone["started"], now)
            ),
            " h",
        ),
        Change(
            "Flaky tests",
            *_two(
                float(len(_flaky_tests(failures, att, final.loc[m, "run_id"]))) for m in run_weeks
            ),
        ),
    ]


def movers(
    jobs: pd.DataFrame, failures: pd.DataFrame, prices: Mapping[str, float], now: pd.Timestamp
) -> list[str]:
    """Plain sentences for what changed most, biggest first."""
    found: list[tuple[float, str]] = []
    att = pl.attempts(jobs)
    ok = att[att["final"] & (att["conclusion"] == "success")]
    billed = pl.billed(jobs, prices)
    for (repo, pipeline), runs in ok.groupby(["repository", "pipeline"]):
        name = f"{pipeline} ({repo})"
        this, last = (runs.loc[m, "minutes"] for m in _weeks(runs["started"], now))
        if len(this) >= MIN_RUNS and len(last) >= MIN_RUNS:
            change = this.median() / last.median() - 1
            if abs(change) >= MOVE:
                found.append(
                    (
                        abs(change),
                        f"{name} runs {abs(change):.0%} {'slower' if change > 0 else 'faster'}: "
                        f"median {last.median():.1f} → {this.median():.1f} min",
                    )
                )
        b = billed[(billed["repository"] == repo) & (billed["pipeline"] == pipeline)]
        now_min, before_min = (b.loc[m, "billed"].sum() for m in _weeks(b["started_at"], now))
        if not now_min and before_min >= MIN_MINUTES:
            found.append(
                (1.0, f"{name} didn't run (it used {before_min:,.0f} minutes the week before)")
            )
        elif max(now_min, before_min) >= MIN_MINUTES and before_min:
            change = now_min / before_min - 1
            if abs(change) >= MOVE:
                found.append(
                    (
                        abs(change),
                        f"{name} used {abs(change):.0%} {'more' if change > 0 else 'fewer'} CI "
                        f"minutes: {before_min:,.0f} → {now_min:,.0f}",
                    )
                )

    final = att[att["final"]]
    this, _ = _weeks(final["started"], now)
    earlier = final.loc[final["started"] <= now - WEEK, "run_id"]
    new = _flaky_tests(failures, att, final.loc[this, "run_id"]) - _flaky_tests(
        failures, att, earlier
    )
    # New flakiness outranks any percentage: it is a fresh problem, not a drift.
    found += [(float("inf"), f"New flaky test: {t}") for t in sorted(new)]
    return [text for _, text in sorted(found, key=lambda f: -f[0])]
