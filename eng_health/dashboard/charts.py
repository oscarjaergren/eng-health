"""Chart, card, table and formatting helpers, so every view looks the same. The classes they
use are styled in style.css."""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Sequence
from html import escape
from itertools import cycle
from typing import Literal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

INK = "#1C1B19"
LIGHT = "#C9C5BB"
MID = "#8F8B82"
HOT = "#C4493A"
AMBER = "#D09945"
SERIES = [INK, HOT, AMBER, MID, LIGHT]
_MUTED = "#8A877F"
_GRID = "#EFEDE8"
# Bars and lines are labelled by the bucket's local start: a day, a week or a month.
TICKS = {"D": "%b %-d", "W": "%b %-d", "M": "%b"}
# The units of a duration, as KPIs and charts name them, in hours.
DURATIONS = {" h": 1.0, " min": 1 / 60}


def _short(n: float) -> str:
    return f"{n:.1f}".removesuffix(".0") if n < 10 else f"{n:,.0f}"


def _time_unit(hours: float) -> tuple[float, str]:
    """The unit people say a length of time in, as (its hours, its name): 90 min, not 1.5 h."""
    if hours >= 72:
        return 24, " d"
    if hours >= 2:
        return 1, " h"
    if hours >= 1 / 60:
        return 1 / 60, " min"
    return 1 / 3600, " s"


def duration(hours: float) -> str:
    """A length of time as the page writes it: 40 s, 3.5 min, 90 min, 26 h, 4.2 d."""
    per, unit = _time_unit(hours)
    return f"{_short(hours / per)}{unit}"


def fmt(v: float | None, unit: str = "") -> str:
    """A value as the page writes it everywhere: KPIs, tables, sentences and chart hovers."""
    if v is None or pd.isna(v):
        return "–"
    if unit in DURATIONS:
        return duration(v * DURATIONS[unit])
    if unit == "$":
        return f"${v:,.2f}"
    if unit == "%":
        return f"{v:.1f}%"
    return f"{v:,.1f}{unit}" if v % 1 else f"{v:,.0f}{unit}"


def md(text: object) -> str:
    """`text` with markdown's special characters escaped, for names and titles from the data."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!$~|<>:])", r"\\\1", str(text))


def esc(text: object) -> str:
    return escape(str(text))


def html(markup: str, width: Literal["stretch", "content"] = "stretch") -> None:
    """Draw `markup`, which must start with a block tag such as <div> and hold no blank line, so
    markdown leaves it alone."""
    st.markdown(markup, unsafe_allow_html=True, width=width)


def slug(text: str) -> str:
    """`text` made safe for a key, which Streamlit turns into a CSS class."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def card(key: str) -> DeltaGenerator:
    """A white, bordered box. `key` must be unique on the page."""
    return st.container(border=True, key=f"card-{slug(key)}")


def head(
    title: str,
    caption: str = "",
    *,
    count: int | None = None,
    note: str = "",
    legend: Sequence[tuple[str, str]] = (),
) -> str:
    """A card's header: title, count and caption on the left; note and legend on the right."""
    keys = "".join(
        f'<span class="legend"><i style="background:{c}"></i>{esc(n)}</span>' for n, c in legend
    )
    number = f'<span class="count">{count}</span>' if count is not None else ""
    return (
        f'<div class="card-head"><b>{esc(title)}</b>{number}<span class="note">{esc(caption)}'
        f'</span><span class="fill"></span><span class="note">{esc(note)}</span>{keys}</div>'
    )


def spark(values: Sequence[float], color: str = INK, width: int = 140, height: int = 22) -> str:
    """A sparkline as inline SVG, ending in a dot."""
    if len(values) < 2:
        return f'<svg class="spark" width="{width}" height="{height}"></svg>'
    low, high = min(values), max(values)
    span = high - low or 1
    points = [
        (2 + (width - 4) * i / (len(values) - 1), 3 + (height - 6) * (1 - (v - low) / span))
        for i, v in enumerate(values)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    x, y = points[-1]
    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"/></svg>'
    )


def _values(frame: pd.DataFrame, unit: str) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """`frame` as the axis draws it, each value as its hover writes it, and the axis's suffix. A
    duration axis counts in its longest value's unit, so the longest hover and the axis agree."""
    text = frame.map(lambda v: fmt(v, unit))
    if unit not in DURATIONS:
        return frame, text, "" if unit == "$" else unit
    hours = frame * DURATIONS[unit]
    per, suffix = _time_unit(hours.max().max())
    return hours / per, text, suffix


def _style(fig: go.Figure, unit: str, suffix: str, ticks: str | None) -> go.Figure:
    fig.update_layout(
        height=230,
        margin={"l": 0, "r": 0, "t": 4, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Geist Mono, monospace", "size": 11, "color": _MUTED},
        showlegend=False,  # the card header carries it
        bargap=0.35,
        hovermode="x unified",
    )
    fig.update_traces(hovertemplate="%{customdata}")
    # automargin makes room for the tick labels: with theme=None nothing else does. Plotly hides a
    # label that overflows (a line's last bucket) before automargin sees it, unless allowed.
    fig.update_xaxes(
        showgrid=False,
        linecolor="#DDD9D0",
        tickformat=ticks,
        fixedrange=True,
        automargin=True,
        ticklabeloverflow="allow",
    )
    if ticks and fig.data:
        # Ticks on buckets only, counted back from the latest: left to plotly, a few months get one
        # mid-month too, "Jul Jul Aug".
        buckets = fig.data[0].x
        fig.update_xaxes(tickvals=buckets[:: -math.ceil(len(buckets) / 7)])
    fig.update_yaxes(
        gridcolor=_GRID,
        zeroline=False,
        ticksuffix=suffix,
        tickprefix="$" if unit == "$" else "",
        # An all-zero series otherwise gets an axis from -1.
        rangemode="nonnegative",
        nticks=4,
        fixedrange=True,
        automargin=True,
    )
    return fig


def bars(
    frame: pd.DataFrame,
    colors: Sequence[str] = SERIES,
    *,
    stack: bool = False,
    highlight: Sequence[object] = (),
    unit: str = "",
    ticks: str | None = None,
) -> go.Figure:
    """A bar per row of `frame` and column; `highlight` reddens those rows of a one-column chart.
    `unit` is a KPI's: "%", "$", or a duration's " h" or " min"."""
    y, text, suffix = _values(frame, unit)
    fig = go.Figure(
        [
            go.Bar(
                x=frame.index,
                y=y[col],
                customdata=text[col],
                name=str(col),
                marker_color=[HOT if x in highlight else color for x in frame.index],
                marker_cornerradius=2,
            )
            for col, color in zip(frame.columns, cycle(colors), strict=False)
        ]
    )
    fig.update_layout(barmode="stack" if stack else "group")
    return _style(fig, unit, suffix, ticks)


def lines(
    frame: pd.DataFrame,
    colors: Sequence[str] = SERIES,
    *,
    dashed: Sequence[str] = (),
    unit: str = "",
    ticks: str | None = None,
) -> go.Figure:
    """A line per column of `frame`; `dashed` columns are the secondary ones, like a percentile.
    `unit` as for `bars`."""
    y, text, suffix = _values(frame, unit)
    fig = go.Figure(
        [
            go.Scatter(
                x=frame.index,
                y=y[col],
                customdata=text[col],
                name=str(col),
                mode="lines",
                connectgaps=True,
                line={"color": color, "width": 1.5 if col in dashed else 2},
                line_dash="dash" if col in dashed else None,
            )
            for col, color in zip(frame.columns, cycle(colors), strict=False)
        ]
    )
    return _style(fig, unit, suffix, ticks)


def _legend(fig: go.Figure) -> list[tuple[str, str]]:
    if len(fig.data) < 2:
        return []
    colors = [t.line.color if t.type == "scatter" else t.marker.color[0] for t in fig.data]
    return [(t.name, c) for t, c in zip(fig.data, colors, strict=True)]


def chart(title: str, caption: str, fig: go.Figure) -> None:
    with card(title):
        html(head(title, caption, legend=_legend(fig)))
        st.plotly_chart(fig, theme=None, config={"displayModeBar": False}, key=f"chart {title}")


def grid(charts: Sequence[tuple[str, str, go.Figure]]) -> None:
    """Charts two to a row."""
    for i in range(0, len(charts), 2):
        for col, args in zip(st.columns(2), charts[i : i + 2], strict=False):
            with col:
                chart(*args)


_CELLS = {
    "t": "c-t",
    "m": "c-m",
    "sub": "c-st",
    "n": "c-n",
    "hot": "c-n tone-red",
    "good": "c-n tone-green",
    "na": "c-n na",
}


def cell(value: object, kind: str = "t") -> str:
    """A table cell. `kind`: t a name, m and sub quieter text (sub indented under the row
    above), n a number, hot and good a red or green number, na a missing one, tag and hot-tag a
    label, link an Open link to `value`."""
    if kind in ("tag", "hot-tag"):
        hot = " tag-hot" if kind == "hot-tag" else ""
        return f'<div><span class="tag{hot}">{esc(value)}</span></div>'
    if kind == "link":
        # Only web links: the URL comes from the synced data.
        url = str(value)
        ok = url.startswith(("https://", "http://"))
        return (
            f'<a class="c-m" href="{esc(url)}" target="_blank">Open</a>' if ok else "<span></span>"
        )
    prefix = "↳ " if kind == "sub" else ""
    return f'<span class="{_CELLS[kind]}">{prefix}{esc(value)}</span>'


def linked(text: str, href: str | None, kind: str = "t") -> str:
    """A table cell that opens `href` in this tab, such as a repository's page; plain without."""
    if not href:
        return cell(text, kind)
    return f'<a class="{_CELLS[kind]}" href="{esc(href)}" target="_self">{esc(text)}</a>'


def trend(values: Sequence[float], color: str = MID) -> str:
    return f'<div class="c-spark">{spark(values, color, width=80)}</div>'


def table_html(
    columns: Sequence[str], widths: str, rows: Sequence[Sequence[str]], right: Collection[int] = ()
) -> str:
    """A table. `rows` are lists of `cell` and `trend` results; `widths` is a CSS
    grid-template-columns value; `right` are the columns aligned right."""
    grid_style = f'style="grid-template-columns:{widths}"'
    labels = "".join(
        f'<span class="{"r" if i in right else ""}">{esc(c)}</span>' for i, c in enumerate(columns)
    )
    body = "".join(f'<div class="tbl-row" {grid_style}>{"".join(r)}</div>' for r in rows)
    if not rows:
        body = '<div class="tbl-row"><span class="c-m">Nothing in this period.</span></div>'
    return f'<div class="tbl"><div class="tbl-row tbl-head" {grid_style}>{labels}</div>{body}</div>'


def table(
    title: str,
    note: str,
    columns: Sequence[str],
    widths: str,
    rows: Sequence[Sequence[str]],
    right: Collection[int] = (),
) -> None:
    """A titled card holding a `table_html` table."""
    with card(title):
        html(head(title, count=len(rows), note=note) + table_html(columns, widths, rows, right))
