from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from ... import metrics
from ..charts import ACCENT, SECOND, show


def render(df: pd.DataFrame, people: dict[str, str], tz: str) -> None:
    flow = metrics.monthly_flow(df, tz)

    cycle = flow[["Median cycle (h)", "75th pct cycle (h)"]].reset_index()
    cycle = cycle.melt("month", var_name="series", value_name="Hours")
    fig = px.line(
        cycle,
        x="month",
        y="Hours",
        color="series",
        markers=True,
        title="Time to merge, by month merged",
        color_discrete_sequence=[ACCENT, SECOND],
        labels={"month": ""},
    )
    show(fig)
    st.caption("Three in four PRs merge faster than the 75th percentile line.")

    fig = px.line(
        flow.reset_index(),
        x="month",
        y="Median first review (h)",
        markers=True,
        title="Median time to first review, by month opened",
        color_discrete_sequence=[ACCENT],
        labels={"month": "", "Median first review (h)": "Hours"},
    )
    show(fig)

    st.subheader("Open PRs waiting")
    days = st.slider("Open for at least (days)", 1, 60, 7)
    stale = metrics.stale_open(df, datetime.now(UTC), days)
    if stale.empty:
        st.success(f"No non-draft PRs have been open for {days} days or more.")
        return
    stale = stale.assign(author=stale["author"].map(lambda p: people.get(p, p)))
    unreviewed = int((~stale["Reviewed"]).sum())
    st.caption(f"{len(stale)} PRs, {unreviewed} of them with no review activity yet.")
    st.dataframe(
        stale,
        width="stretch",
        hide_index=True,
        column_config={
            "title": "Title",
            "repository": "Repository",
            "author": "Author",
            "url": st.column_config.LinkColumn("Link", display_text="Open"),
        },
    )
