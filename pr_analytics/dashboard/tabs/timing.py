from __future__ import annotations

import pandas as pd
import streamlit as st

from ... import metrics
from ..charts import heatmap


def render(df: pd.DataFrame, tz: str) -> None:
    st.caption(f"Times are in {tz}, taken from your browser.")
    grid = metrics.weekday_hour(df, tz)
    grid.columns = [f"{h:02d}:00" for h in grid.columns]
    heatmap(grid, "PRs opened by weekday and hour", "Hour", "", "PRs")
