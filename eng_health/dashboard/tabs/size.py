from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ... import metrics
from ..charts import ACCENT, SECOND, show


def render(df: pd.DataFrame, tz: str) -> None:
    st.caption(
        "Lines added and deleted, without lock files and generated code. "
        "Azure DevOps PRs have no size yet, so they are left out here."
    )
    table = metrics.by_size(df)
    if table.empty:
        st.info("No PRs with a size in the current selection.")
        return

    waits = table[["Median first review (h)", "Median to merge (h)"]].reset_index()
    long = waits.melt("size", var_name="series", value_name="hours")
    show(
        px.bar(
            long,
            x="size",
            y="hours",
            color="series",
            barmode="group",
            title="How long PRs wait, by size",
            color_discrete_sequence=[ACCENT, SECOND],
            labels={"size": "", "hours": "Median hours", "series": ""},
        )
    )
    st.dataframe(
        table,
        width="stretch",
        column_config={
            "Median first review (h)": st.column_config.NumberColumn(format="%.1f"),
            "Median to merge (h)": st.column_config.NumberColumn(format="%.1f"),
            "Comments per 100 lines": st.column_config.NumberColumn(
                format="%.1f",
                help="Comments by people other than the author, per 100 changed lines. "
                "A low number on big PRs means they are skimmed rather than read.",
            ),
        },
    )

    trend = metrics.size_trend(df, tz).reset_index()
    show(
        px.line(
            trend,
            x="month",
            y="Median lines",
            markers=True,
            title="Median PR size, by month opened",
            color_discrete_sequence=[ACCENT],
            labels={"month": ""},
            hover_data=["PRs"],
        )
    )
