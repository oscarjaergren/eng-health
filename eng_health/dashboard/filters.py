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
# Each chip opens a checklist. A checkbox's key is "<chip>|<option>|<round>", so its state is
# the filter; Clear filters starts a new round (see _clear).
CHIPS = {"platform": "Platform", "repo": "Repository", "author": "Author", "state": "State"}
CHIP_DEFAULTS = {"state": ["open", "merged"]}
TOGGLES = {"drafts": True, "bots": False, "infra": False}


def _clear() -> None:
    # New checkbox keys rather than resetting the old ones: a closed popover's checkboxes aren't
    # in the browser to receive a reset, and send their old values back on the next rerun.
    st.session_state["round"] = st.session_state.get("round", 0) + 1
    for name in CHIPS:
        if name in st.query_params:
            del st.query_params[name]
    for key, value in TOGGLES.items():
        st.session_state[key] = value


def _chip(name: str, options: list[str], label: Callable[[str], str] = str) -> list[str]:
    """A chip whose checklist picks some of `options`; none picked means all of them."""
    keys = {o: f"{name}|{o}|{st.session_state.get('round', 0)}" for o in options}
    default = CHIP_DEFAULTS.get(name, [])
    # Until a checkbox has been drawn, its value comes from the URL, where "all" stands for an
    # empty choice that isn't the default.
    wanted = st.query_params.get_all(name) or default
    ticked = {o: st.session_state.get(k, o in wanted) for o, k in keys.items()}
    chosen = [o for o, on in ticked.items() if on]

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
            # The current value as the default too: a checkbox in a popover that hasn't been
            # opened yet starts from its default when it first appears, then reports it back.
            st.checkbox(md(label(option)), value=ticked[option], key=key)

    if changed:
        st.query_params[name] = chosen or ["all"]
    elif name in st.query_params:
        del st.query_params[name]
    return chosen


def _span(period: Period, now: pd.Timestamp, tz: str) -> str:
    """The period's dates, in fixed-width slots so the chips after them don't move."""
    end = now.tz_convert(tz)
    start = end - pd.Timedelta(days=period.days - 1)
    days = f"{start:%b %-d} – {end:%b %-d}"
    return (
        f'<div class="span-range"><span>{days}</span>'
        f'<span class="vs">vs prior {esc(period.name)}</span></div>'
    )


def bar(
    df: pd.DataFrame, names: dict[str, str], now: pd.Timestamp, tz: str
) -> tuple[Period, Filters]:
    # Two rows, so a chip growing or Clear filters appearing never rewraps the bar.
    chips_row = st.container(horizontal=True, vertical_alignment="center", gap="xsmall")
    toggles_row = st.container(horizontal=True, vertical_alignment="center")
    with chips_row:
        period, chosen = _chips(df, names, now, tz)
    with toggles_row:
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
        st.space("stretch")
        changed = any(k in st.query_params for k in CHIPS) or any(
            st.session_state[k] != v for k, v in TOGGLES.items()
        )
        # Always drawn, and hidden while there is nothing to clear, so it takes the same room.
        st.button(
            "Clear filters", type="tertiary", on_click=_clear, key="clear", disabled=not changed
        )
    platforms, repos, authors, states = chosen
    return period, Filters(
        platforms=tuple(platforms),
        repositories=tuple(repos),
        authors=tuple(authors),
        states=tuple(states),
        include_drafts=drafts,
        include_bots=bots,
        include_infrastructure=infra,
    )


def _chips(
    df: pd.DataFrame, names: dict[str, str], now: pd.Timestamp, tz: str
) -> tuple[Period, tuple[list[str], list[str], list[str], list[str]]]:
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
    html(_span(period, now, tz), "content")
    html('<div><span class="vrule"></span></div>', "content")

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
    return period, (chosen_platforms, repos, authors, states)
