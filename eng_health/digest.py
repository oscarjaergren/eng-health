"""The period's headline numbers against the period before, and what moved most."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from . import metrics
from . import pipelines as pl
from .period import Period, between

# A mover has to change by this much, over at least MIN_RUNS runs in each period, to get a line.
MOVE = 0.2
MIN_RUNS = 3
MIN_MINUTES = 30

# key: (label, unit, lower_is_better). None when neither direction is good news.
METRICS: dict[str, tuple[str, str, bool | None]] = {
    "opened": ("PRs opened", "", None),
    "merged": ("PRs merged", "", False),
    "open": ("Open now", "", True),
    "size": ("Median PR size", " lines", True),
    "wait": ("Wait for first review", " h", True),
    "ttm": ("Time to merge", " h", True),
    "depth": ("Comments per 100 lines", "", False),
    "unreviewed": ("Merged without review", "", True),
    "authors": ("Active contributors", "", None),
    "per_person": ("PRs merged per person", "", None),
    "added": ("Lines added", "", None),
    "deleted": ("Lines deleted", "", None),
    "failure": ("Default-branch failures", "%", True),
    "rerun_hours": ("Lost to reruns", " h", True),
    "flaky": ("Flaky jobs", "", True),
    "minutes": ("CI minutes", "", True),
    "cost": ("Est. CI cost", "$", True),
    "rerun_cost": ("Spent on reruns", "$", True),
}

Stats = dict[str, float | None]
# Numbers only GitHub reports (Azure DevOps has no line counts).
GITHUB_ONLY = frozenset({"size", "depth", "added", "deleted"})


@dataclass(frozen=True)
class Change:
    label: str
    now: float | None
    before: float | None
    unit: str = ""
    lower_is_better: bool | None = True
    # One value per chart bucket, for a sparkline.
    trend: tuple[float, ...] = ()
    # Said in place of a change when there is no value, e.g. why there is none.
    empty: str = ""

    @property
    def ratio(self) -> float | None:
        if self.now is None or not self.before:
            return None
        return (self.now - self.before) / self.before


@dataclass(frozen=True)
class Numbers:
    """Stats for the period, the period before, and each chart bucket."""

    now: Stats
    before: Stats
    trend: pd.DataFrame

    def change(self, key: str) -> Change:
        label, unit, lower_is_better = METRICS[key]
        trend = tuple(self.trend[key].dropna().astype(float)) if key in self.trend else ()
        return Change(label, self.now[key], self.before[key], unit, lower_is_better, trend)


def numbers(
    stats: Callable[[pd.Timestamp, pd.Timestamp], Stats], period: Period, now: pd.Timestamp, tz: str
) -> Numbers:
    return Numbers(
        stats(*period.window(now)), stats(*period.window(now, back=1)), period.each(now, tz, stats)
    )


def _num(x: Any) -> float | None:
    """A pandas reduction as a float, or None for NaN and NA."""
    return None if pd.isna(x) else float(x)


def pr_stats(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> Stats:
    """PR numbers for (start, end]. `open` counts what was still open at `end`."""
    opened = metrics.opened_in(df, start, end)
    merged = metrics.merged_in(df, start, end)
    sized = merged[merged["lines"].notna()]
    lines = sized["lines"].sum()
    reviewed = metrics.reviewed(merged)
    still_open = (df["created_at"] <= end) & ~(df["closed_at"] <= end)
    return {
        "opened": float(len(opened)),
        "merged": float(len(merged)),
        "open": float(still_open.sum()),
        "wait": _num(opened["first_review_hours"].median()),
        "wait_p75": _num(opened["first_review_hours"].quantile(0.75)),
        "ttm": _num(merged["cycle_hours"].median()),
        "ttm_p75": _num(merged["cycle_hours"].quantile(0.75)),
        "size": _num(sized["lines"].median()),
        "depth": _num(100 * sized["comments"].sum() / lines) if lines else None,
        "unreviewed": float((~reviewed).sum()),
        "authors": float(pd.concat([opened["author"], merged["author"]]).nunique()),
        "per_person": _num(merged["author"].value_counts().median()),
        "added": float(sized["additions"].sum()) if len(sized) else None,
        "deleted": float(sized["deletions"].sum()) if len(sized) else None,
    }


def ci_stats(
    att: pd.DataFrame, billed: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> Stats:
    """CI numbers for runs started in (start, end]. `billed` as `pipelines.billed` returns it."""
    a = att[between(att["started"], start, end)]
    final = a[a["final"]]
    done = final[final["is_default_branch"] & (final["conclusion"] != "cancelled")]
    passed = final["conclusion"] == "success"
    b = billed[between(billed["started_at"], start, end)]
    return {
        "passed": float((passed & (final["attempt"] == 1)).sum()),
        "passed_on_rerun": float((passed & (final["attempt"] > 1)).sum()),
        "failed": float((final["conclusion"] == "failure").sum()),
        "failure": _num(done["failed"].mean() * 100),
        "rerun_hours": float(a.loc[~a["final"], "minutes"].sum() / 60),
        "flaky": float(len(pl.flaky_jobs(b))),
        "minutes": float(b["billed"].sum()),
        "cost": float(b["cost"].sum()),
        "rerun_cost": float(b.loc[b["rerun"], "cost"].sum()),
    }


@dataclass(frozen=True)
class Move:
    title: str
    detail: str
    change: float  # relative: 1.0 is double
    tag: str
    worse: bool


def movers(
    att: pd.DataFrame, billed: pd.DataFrame, period: Period, now: pd.Timestamp
) -> list[Move]:
    """Workflows whose run time or CI minutes changed by MOVE or more, biggest change first."""
    this, last = period.window(now), period.window(now, back=1)
    found: list[Move] = []
    ok = att[att["final"] & (att["conclusion"] == "success")]
    for (repo, pipeline), runs in ok.groupby(["repository", "pipeline"]):
        now_min, before_min = (
            runs.loc[between(runs["started"], *w), "minutes"] for w in (this, last)
        )
        if len(now_min) >= MIN_RUNS and len(before_min) >= MIN_RUNS:
            a, b = float(before_min.median()), float(now_min.median())
            if abs(b / a - 1) >= MOVE:
                detail = f"{repo} · median {a:.1f} → {b:.1f} min"
                tag = "Slower" if b > a else "Faster"
                found.append(Move(f"{pipeline} run time", detail, b / a - 1, tag, b > a))
    for (repo, pipeline), jobs in billed.groupby(["repository", "pipeline"]):
        now_used, used = (
            float(jobs.loc[between(jobs["started_at"], *w), "billed"].sum()) for w in (this, last)
        )
        if not now_used and used >= MIN_MINUTES:
            detail = f"{repo} · used {used:,.0f} minutes the {period.name} before"
            found.append(Move(f"{pipeline} didn't run", detail, -1.0, "Stopped", True))
        elif max(now_used, used) >= MIN_MINUTES and used:
            change = now_used / used - 1
            if abs(change) >= MOVE:
                detail = f"{repo} · {used:,.0f} → {now_used:,.0f}"
                tag = "More minutes" if change > 0 else "Fewer minutes"
                found.append(Move(f"{pipeline} minutes", detail, change, tag, change > 0))
    return sorted(found, key=lambda m: -abs(m.change))


def new_flaky_tests(
    failures: pd.DataFrame, att: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    """Tests flaky in runs started in (start, end] that had never been flaky before."""
    final = att[att["final"]]

    def flaky(runs: pd.Series) -> pd.DataFrame:
        f = failures[failures["run_id"].isin(runs)] if len(failures) else failures
        return pl.flaky_tests(f, att) if len(f) else pd.DataFrame(columns=pl.FLAKY_TEST_COLUMNS)

    now = flaky(final.loc[between(final["started"], start, end), "run_id"])
    before = flaky(final.loc[final["started"] <= start, "run_id"])
    return now[~now["test_id"].isin(before["test_id"])]
