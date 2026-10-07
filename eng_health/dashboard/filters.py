"""Sidebar filters, mirrored into the URL so a filtered view can be shared."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from ..metrics import Filters
from ..models import PLATFORM_NAMES

STATES = ["open", "merged", "abandoned"]
DEFAULT_STATES = ["open", "merged"]


def _url_list(name: str, options: list[str], default: list[str] | None = None) -> list[str]:
    values = st.query_params.get_all(name)
    picked = [v for v in values if v in options]
    return picked if values else (default or [])


def _url_date(name: str, fallback: date) -> date:
    try:
        return date.fromisoformat(st.query_params.get(name, ""))
    except ValueError:
        return fallback


def sidebar_filters(df: pd.DataFrame, people: dict[str, str], tz: str) -> Filters:
    st.sidebar.header("Filters")

    def name(p: str) -> str:
        return people.get(p, p)

    platforms = sorted(df["platform"].unique())
    chosen_platforms: list[str] = []
    if len(platforms) > 1:
        chosen_platforms = st.sidebar.multiselect(
            "Platform",
            platforms,
            default=_url_list("platform", platforms),
            format_func=lambda p: PLATFORM_NAMES.get(p, p),
            placeholder="All platforms",
        )

    repos = sorted(df["repository"].unique())
    chosen_repos = st.sidebar.multiselect(
        "Repository", repos, default=_url_list("repo", repos), placeholder="All repositories"
    )

    authors = sorted(df["author"].unique(), key=lambda p: name(p).lower())
    chosen_authors = st.sidebar.multiselect(
        "Author",
        authors,
        default=_url_list("author", authors),
        format_func=name,
        placeholder="All authors",
    )

    chosen_states = st.sidebar.multiselect(
        "State",
        STATES,
        default=_url_list("state", STATES, DEFAULT_STATES),
        format_func=str.capitalize,
        placeholder="All states",
    )

    local = df["created_at"].dt.tz_convert(tz)
    lo, hi = local.min().date(), local.max().date()
    picked = st.sidebar.date_input(
        "Created between",
        value=(max(lo, _url_date("from", lo)), min(hi, _url_date("to", hi))),
        min_value=lo,
        max_value=max(hi, date.today()),
    )
    # While the user is mid-way through picking a range, only one date is set.
    start, end = picked if isinstance(picked, tuple) and len(picked) == 2 else (lo, hi)

    infra = st.sidebar.toggle(
        "Include infrastructure PRs",
        value=st.query_params.get("infra") == "1",
        help=f"{int(df['is_infrastructure'].sum())} PRs have titles mentioning Terraform, Helm, "
        "Bicep, Kubernetes and similar. They are left out by default because they usually "
        "follow a different review process.",
    )
    drafts = st.sidebar.toggle("Include drafts", value=st.query_params.get("drafts", "1") == "1")

    st.query_params.clear()
    params: dict[str, str | list[str]] = {
        "platform": chosen_platforms,
        "repo": chosen_repos,
        "author": chosen_authors,
        # "all" keeps an empty selection from reverting to the default on reload.
        "state": chosen_states or ["all"],
        **({"from": start.isoformat()} if start != lo else {}),
        **({"to": end.isoformat()} if end != hi else {}),
        **({"infra": "1"} if infra else {}),
        **({"drafts": "0"} if not drafts else {}),
    }
    st.query_params.update({k: v for k, v in params.items() if v})

    return Filters(
        platforms=tuple(chosen_platforms),
        repositories=tuple(chosen_repos),
        authors=tuple(chosen_authors),
        states=tuple(chosen_states),
        start=start,
        end=end,
        include_infrastructure=infra,
        include_drafts=drafts,
        tz=tz,
    )
