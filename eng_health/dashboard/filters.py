"""The filter bar: the period, and which PRs count. Every choice is kept in the URL, so a
filtered view can be shared."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st

from ..metrics import Filters
from ..models import PLATFORM_NAMES
from ..period import PERIODS, Period
from .charts import esc, html, md

STATES = {"open": "Open", "merged": "Merged", "abandoned": "Abandoned"}
# Each chip opens a checklist. A checkbox's key is "<chip>|<option>", so its state is the filter.
CHIPS = {"platform": "Platform", "repo": "Repository", "author": "Author", "state": "State"}
CHIP_DEFAULTS = {"state": ["open", "merged"]}
TOGGLES = {"drafts": True, "bots": False, "infra": False}


def _clear() -> None:
    for key in list(st.session_state):
        chip, sep, option = str(key).partition("|")
        if sep and chip in CHIPS:
            st.session_state[key] = option in CHIP_DEFAULTS.get(chip, [])
    for key, value in TOGGLES.items():
        st.session_state[key] = value


def _chip(name: str, options: list[str], label: Callable[[str], str] = str) -> list[str]:
    """A chip whose checklist picks some of `options`; none picked means all of them."""
    keys = {o: f"{name}|{o}" for o in options}
    default = CHIP_DEFAULTS.get(name, [])
    if not any(k in st.session_state for k in keys.values()):
        # First run: from the URL, where "all" stands for an empty choice that isn't the default.
        wanted = st.query_params.get_all(name) or default
        for option, key in keys.items():
            st.session_state[key] = option in wanted
    chosen = [o for o, k in keys.items() if st.session_state[k]]

    if not chosen or len(chosen) == len(options):
        summary = "All"
    elif len(chosen) <= 2:
        summary = ", ".join(label(o) for o in chosen)
    else:
        summary = f"{len(chosen)} selected"
    changed = chosen != [o for o in options if o in default]
    with st.popover(
        f":gray[{CHIPS[name]}] {md(summary)}",
        type="primary" if changed else "secondary",
        key=f"chip-{name}",
    ):
        for option, key in keys.items():
            st.checkbox(md(label(option)), key=key)

    if changed:
        st.query_params[name] = chosen or ["all"]
    elif name in st.query_params:
        del st.query_params[name]
    return chosen


def _span(period: Period, now: pd.Timestamp, tz: str) -> str:
    end = now.tz_convert(tz)
    start = end - pd.Timedelta(days=period.days - 1)
    year = ", %Y" if start.year != end.year else ""
    days = f"{start.strftime('%b %-d' + year)} – {end.strftime('%b %-d')}"
    return f'<div class="span-range">{days}<span>vs prior {esc(period.name)}</span></div>'


def bar(
    df: pd.DataFrame, names: dict[str, str], now: pd.Timestamp, tz: str
) -> tuple[Period, Filters]:
    period = PERIODS[
        st.segmented_control(
            "Period",
            list(PERIODS),
            format_func=str.upper,
            default="7d",
            required=True,
            key="period",
            bind="query-params",
            label_visibility="collapsed",
        )
    ]
    html(_span(period, now, tz))
    html('<div><span class="vrule"></span></div>')

    platforms = sorted(df["platform"].unique())
    chosen_platforms = (
        _chip("platform", platforms, PLATFORM_NAMES.__getitem__) if len(platforms) > 1 else []
    )
    repos = _chip("repo", sorted(df["repository"].unique()))
    authors = _chip(
        "author",
        sorted(df["author"].unique(), key=lambda p: str(names.get(p, p)).lower()),
        lambda p: names.get(p, p),
    )
    states = _chip("state", list(STATES), STATES.__getitem__)
    html('<div><span class="vrule"></span></div>')

    drafts = st.toggle("Drafts", value=True, key="drafts", bind="query-params")
    bots = st.toggle("Dependabot & Renovate PRs", value=False, key="bots", bind="query-params")
    infra = st.toggle(
        "Infrastructure PRs",
        value=False,
        key="infra",
        bind="query-params",
        help="Titles mentioning Terraform, Helm, Bicep, Kubernetes and similar. Left out by "
        "default because they usually follow a different review process.",
    )
    chips_set = any(k in st.query_params for k in CHIPS)
    if chips_set or any(st.session_state[k] != v for k, v in TOGGLES.items()):
        st.space("stretch")
        st.button("Clear filters", type="tertiary", on_click=_clear, key="clear")

    return period, Filters(
        platforms=tuple(chosen_platforms),
        repositories=tuple(repos),
        authors=tuple(authors),
        states=tuple(states),
        include_drafts=drafts,
        include_bots=bots,
        include_infrastructure=infra,
    )
