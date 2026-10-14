"""The period the dashboard covers, the one before it, and the buckets its charts draw."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Period:
    # Numbers cover the last `days` and compare them with the `days` before. Rolling, so a half
    # finished today doesn't make every count look like a drop.
    days: int
    name: str
    # Charts draw the last `buckets` calendar days ("D"), weeks ("W") or months ("M").
    freq: str
    buckets: int
    # The oldest record synced. Charts start at its bucket instead of drawing empty ones before it.
    start: pd.Timestamp | None = None

    def window(self, now: pd.Timestamp, back: int = 0) -> tuple[pd.Timestamp, pd.Timestamp]:
        """(start, end] of the period, or with back=1 of the one before it."""
        end = now - pd.Timedelta(days=self.days * back)
        return end - pd.Timedelta(days=self.days), end

    def edges(self, now: pd.Timestamp, tz: str) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
        """Each bucket's local start, to label it, and the UTC boundaries between them."""
        local = now.tz_convert(tz).tz_localize(None).to_period(self.freq)
        periods = pd.period_range(end=local, periods=self.buckets)
        if not pd.isna(self.start):
            first = self.start.tz_convert(tz).tz_localize(None).to_period(self.freq)
            periods = periods[periods >= min(first, local)]
        starts = [p.start_time for p in periods]
        bounds = [
            s.tz_localize(tz, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")
            for s in starts
        ]
        return starts, [*bounds, now]

    def each(
        self, now: pd.Timestamp, tz: str, fn: Callable[[pd.Timestamp, pd.Timestamp], Any]
    ) -> pd.DataFrame:
        """One row per bucket: `fn(start, end)`, a dict or Series whose keys become columns."""
        labels, edges = self.edges(now, tz)
        return pd.DataFrame([fn(a, b) for a, b in pairwise(edges)], index=labels)


PERIODS = {
    "7d": Period(7, "7 days", "D", 7),
    "30d": Period(30, "30 days", "D", 30),
    "90d": Period(90, "90 days", "W", 13),
    "12m": Period(365, "12 months", "M", 12),
}


def between(times: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Rows whose time falls in (start, end]."""
    return (times > start) & (times <= end)


def sparklines(trend: pd.DataFrame, keys: pd.Index) -> list[list[float]]:
    """Each key's column of a `Period.each` frame, as a list for a sparkline. Buckets without a
    value are left out; fill them first where a missing value means zero."""
    t = trend.reindex(columns=keys)
    return [t[k].dropna().astype(float).tolist() for k in keys]
