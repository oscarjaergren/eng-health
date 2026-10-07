from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ... import metrics
from ..charts import ACCENT, SECOND, heatmap, hours, show


def render(df: pd.DataFrame, tz: str) -> None:
    s = metrics.summary(df)
    c = st.columns(5)
    c[0].metric("PRs", s["prs"])
    c[1].metric("Merged", s["merged"])
    c[2].metric(
        "Time to merge",
        hours(s["median_cycle_hours"]),
        help="Median time from opening a PR to merging it, so a few slow PRs don't skew it.",
    )
    c[3].metric(
        "Time to review",
        hours(s["median_first_review_hours"]),
        help="Median time from opening a PR to the first comment, vote or review by anyone else.",
    )
    c[4].metric(
        "Unreviewed merges",
        s["merged_without_review"],
        help="Merged PRs with no approval and no comment or review from anyone but the author.",
    )

    flow = metrics.monthly_flow(df, tz)
    long = (
        flow[["Opened", "Merged"]].reset_index().melt("month", var_name="series", value_name="PRs")
    )
    fig = px.bar(
        long,
        x="month",
        y="PRs",
        color="series",
        barmode="group",
        title="Opened and merged per month",
        color_discrete_sequence=[ACCENT, SECOND],
        labels={"month": ""},
    )
    show(fig)

    st.subheader("Repositories")
    st.dataframe(
        metrics.repo_summary(df),
        width="stretch",
        column_config={
            "Median cycle (h)": st.column_config.NumberColumn(
                "Median time to merge (h)", format="%.1f"
            ),
            "Median first review (h)": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    top = df["repository"].value_counts().head(20).index
    month = df["created_at"].dt.tz_convert(tz).dt.tz_localize(None).dt.to_period("M").astype(str)
    grid = pd.crosstab(df["repository"], month).reindex(top)
    if not grid.empty:
        heatmap(grid, "PRs opened per repository and month (top 20)", "Month", "", "PRs")
