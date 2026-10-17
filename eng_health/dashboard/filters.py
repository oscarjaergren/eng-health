"""The filter bar: the period, and which PRs count. Every choice is kept in the URL, so a
filtered view can be shared."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pandas as pd
import streamlit as st

from .. import metrics, prefs
from ..metrics import Filters
from ..models import PLATFORM_NAMES
from ..period import PERIODS, Period
from .charts import esc, html, md

STATES = {"open": "Open", "merged": "Merged", "abandoned": "Abandoned"}
# Each chip opens a checklist (`_chip`), or a search list for the long ones (`_pick`). A widget's
# key is "<chip>|...|<round>", so its state is the filter; Clear filters starts a new round.
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


def picked(name: str) -> bool:
    """Whether a chip has a choice of its own, as opposed to following the scope."""
    return name in st.query_params


def forget(name: str) -> None:
    """Drop one chip's choice, for the ✕ on a repository page. A new round, as Clear filters
    starts, gives every chip new widgets; the others take their choice back from the URL."""
    st.session_state["round"] = st.session_state.get("round", 0) + 1
    if name in st.query_params:
        del st.query_params[name]


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


def _pick(
    name: str,
    options: list[str],
    label: Callable[[str], str],
    notes: Mapping[str, str],
    everything: str = "All",
) -> list[str]:
    """A chip whose popover is a search list of `options`, in the order given, each with its
    note ("12 PRs"). None picked means all of them, which the chip calls `everything`."""
    key = f"{name}|{st.session_state.get('round', 0)}"
    picked = st.session_state.get(key)
    if picked is None:  # not drawn yet: from the URL
        picked = st.query_params.get_all(name)
    chosen = [o for o in picked if o in options]
    summary = (
        everything
        if not chosen
        else ", ".join(label(o) for o in chosen)
        if len(chosen) <= 2
        else f"{len(chosen)} selected"
    )
    with st.popover(
        f":gray[{CHIPS[name]}] {md(summary)}",
        type="primary" if chosen else "secondary",
        key=f"chip-{name}",
        help=", ".join(label(o) for o in chosen) if len(chosen) > 2 else None,
    ):
        # The current choice as the default too, for the same reason as `_chip`'s checkboxes.
        st.multiselect(
            CHIPS[name],
            options,
            default=chosen,
            key=key,
            format_func=lambda o: f"{label(o)} · {notes[o]}",
            placeholder=f"Search {CHIPS[name].lower()}…",
            label_visibility="collapsed",
        )
    if chosen:
        st.query_params[name] = chosen
    elif name in st.query_params:
        del st.query_params[name]
    return chosen


def _prs(n: int) -> str:
    return f"{n} PR{'s' if n != 1 else ''}" if n else "no PRs"


def _span(period: Period, now: pd.Timestamp, tz: str) -> str:
    """The period's dates, in fixed-width slots so the chips after them don't move."""
    end = now.tz_convert(tz)
    start = end - pd.Timedelta(days=period.days - 1)
    days = f"{start:%b %-d} – {end:%b %-d}"
    return (
        f'<div class="span-range"><span>{days}</span>'
        f'<span class="vs">vs prior {esc(period.name)}</span></div>'
    )


def _remember_period(data_dir: Path) -> None:
    prefs.save(data_dir, period=st.session_state["period"])


def bar(
    df: pd.DataFrame,
    names: dict[str, str],
    repos: pd.DataFrame,
    now: pd.Timestamp,
    tz: str,
    data_dir: Path,
    scope: tuple[str, ...] = (),
    scope_name: str = "All",
) -> tuple[Period, Filters]:
    """`repos` is the store's repositories table. `scope` are the repository keys to cover while
    none are picked (none: all of them); `scope_name` is what the Repository chip calls them."""
    # Two rows, so a chip growing or Clear filters appearing never rewraps the bar.
    chips_row = st.container(horizontal=True, vertical_alignment="center", gap="xsmall")
    toggles_row = st.container(horizontal=True, vertical_alignment="center")
    with chips_row:
        period, chosen, hidden = _chips(
            df, names, repos, now, tz, data_dir, scope_name if scope else "All"
        )
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
    platforms, chosen_repos, authors, states = chosen
    return period, Filters(
        platforms=tuple(platforms),
        # Picked repositories win over the scope; archived ones and forks stay out of it.
        repositories=tuple(chosen_repos) or tuple(k for k in scope if k not in hidden),
        hidden=hidden,
        authors=tuple(authors),
        states=tuple(states),
        include_drafts=drafts,
        include_bots=bots,
        include_infrastructure=infra,
    )


def _chips(
    df: pd.DataFrame,
    names: dict[str, str],
    repos: pd.DataFrame,
    now: pd.Timestamp,
    tz: str,
    data_dir: Path,
    everywhere: str,
) -> tuple[Period, tuple[list[str], list[str], list[str], list[str]], tuple[str, ...]]:
    # 30 days unless another was picked last time: 7 leaves most charts a few sparse points.
    remembered = prefs.load(data_dir).get("period", "30d")
    period = PERIODS[
        st.segmented_control(
            "Period",
            list(PERIODS),
            format_func=str.upper,
            default=remembered if remembered in PERIODS else "30d",
            required=True,
            key="period",
            bind="query-params",
            on_change=_remember_period,
            args=(data_dir,),
            label_visibility="collapsed",
        )
    ]
    html(_span(period, now, tz), "content")
    html('<div><span class="vrule"></span></div>', "content")

    platforms = sorted(df["platform"].unique())
    chosen_platforms = (
        _chip("platform", platforms, PLATFORM_NAMES.__getitem__) if len(platforms) > 1 else []
    )
    start, end = period.window(now)
    options = metrics.repo_options(df, repos, start, end)
    repo_notes = {
        k: status or _prs(n)
        for k, n, status in zip(options.index, options["prs"], options["status"], strict=True)
    }
    repo_names = dict(zip(options.index.astype(str), options["name"].astype(str), strict=True))
    chosen_repos = _pick(
        "repo", list(options.index), repo_names.__getitem__, repo_notes, everywhere
    )

    def person(p: str) -> str:
        return names.get(p, p)

    prs = metrics.activity(df, start, end, "author")
    authors = sorted(df["author"].unique(), key=lambda p: (-prs.get(p, 0), person(p).lower()))
    chosen_authors = _pick("author", authors, person, {p: _prs(prs.get(p, 0)) for p in authors})
    states = _chip("state", list(STATES), STATES.__getitem__)
    hidden = tuple(options.index[options["status"] != ""])
    return period, (chosen_platforms, chosen_repos, chosen_authors, states), hidden
