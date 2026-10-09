"""This week: the headline numbers against last week, and what moved most."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

import pandas as pd
import streamlit as st

from .. import digest
from .. import pipelines as pl
from ..store import Store
from . import pipelines_page


def _metric(slot: st.delta_generator.DeltaGenerator, c: digest.Change) -> None:
    def fmt(v: float | None) -> str:
        if v is None:
            return "–"
        if c.unit == "$":
            return f"${v:,.2f}"
        return f"{v:,.1f}{c.unit}" if v % 1 else f"{v:,.0f}{c.unit}"

    color: Literal["off", "inverse", "normal"] = (
        "off" if c.lower_is_better is None else ("inverse" if c.lower_is_better else "normal")
    )
    if c.ratio is None:
        delta = None
    elif round(c.ratio, 2) == 0:
        delta, color = "no change", "off"
    else:
        delta = f"{c.ratio:+.0%} (was {fmt(c.before)})"
    slot.metric(c.label, fmt(c.now), delta, delta_color=color)


def _row(changes: list[digest.Change]) -> None:
    for i in range(0, len(changes), 4):
        cols = st.columns(4)
        for slot, change in zip(cols, changes[i : i + 4], strict=False):
            _metric(slot, change)


def render(
    prs: pd.DataFrame, store: Store | None, github: bool, prices: Mapping[str, float]
) -> None:
    now = pd.Timestamp.now(tz="UTC")
    st.title("This week")
    st.caption("The last 7 days against the 7 before. Green is better, red is worse.")

    moved: list[str] = []
    if not prs.empty:
        st.subheader("Pull requests")
        _row(digest.pr_changes(prs, now))

    raw, failures = (
        pipelines_page.load(store) if store is None or github else (pd.DataFrame(), pd.DataFrame())
    )
    if not raw.empty:
        jobs = pl.prepare(raw)
        st.subheader("CI")
        _row(digest.ci_changes(jobs, failures, prices, now))
        moved = digest.movers(jobs, failures, prices, now)

    if prs.empty and raw.empty:
        st.info("Nothing synced yet. Press **Sync now** in the sidebar.")
        return

    st.subheader("What moved")
    if moved:
        st.markdown("\n".join(f"- {line}" for line in moved[:10]))
    else:
        st.write(f"No workflow changed by {digest.MOVE:.0%} or more, and no new flaky tests.")
