"""Shared chart and formatting helpers so every tab looks the same."""

from __future__ import annotations

import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ACCENT = "#4C78A8"
SECOND = "#F58518"


def show(fig: go.Figure) -> None:
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 40, "b": 0}, title_font_size=15, legend_title_text=""
    )
    st.plotly_chart(fig, width="stretch")


def heatmap(df: pd.DataFrame, title: str, x_label: str, y_label: str, value_label: str) -> None:
    fig = px.imshow(
        df,
        title=title,
        aspect="auto",
        color_continuous_scale="Blues",
        labels={"x": x_label, "y": y_label, "color": value_label},
    )
    fig.update_layout(height=max(320, 24 * len(df)))
    show(fig)


def hours(h: float | None) -> str:
    if h is None or (isinstance(h, float) and math.isnan(h)):
        return "–"
    if h < 48:
        return f"{h:.1f} h"
    return f"{h / 24:.1f} days"
