"""Streamlit entry point: the top bar, the filter bar, then the chosen view."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from .. import metrics, prefs, sync
from .. import pipelines as pl
from ..config import ConfigError, Settings
from ..store import SchemaError, Store
from . import connect, filters
from .data import load, load_pipelines, relative, run_sync
from .views import RENDER, VIEWS, Context

# Module level, so it runs once per process rather than on every rerun.
load_dotenv()
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Clear filters resets widgets through Session State, which this logger reports with a stack
# trace every time, although Streamlit then uses the reset value as intended.
logging.getLogger("streamlit.elements.lib.policies").setLevel(logging.ERROR)
log = logging.getLogger(__name__)

_STYLE = Path(__file__).parent / "style.css"


def _browser_timezone() -> str:
    tz = st.context.timezone or "UTC"
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError, ValueError:
        return "UTC"
    return tz


def _sync_status(settings: Settings, store: Store) -> str:
    states = [store.sync_state(p) for p in settings.platforms]
    if any(s.last_error and sync.BUDGET_SPENT not in s.last_error for s in states):
        return ":red[Last sync failed: see Settings]"
    read = [store.history(p) for p in settings.platforms]
    done, total = sum(d for d, _ in read), sum(t for _, t in read)
    if done < total:
        # A large organisation's first syncs, each stopping when the API budget runs out.
        return f"History {done / total:.0%} read"
    synced = [s.last_sync for s in states if s.last_sync]
    # The platform synced longest ago is the one the numbers might be stale for.
    return f"Synced {relative(min(synced))}" if len(synced) == len(states) else "Not synced yet"


def _remember_scope(settings: Settings) -> None:
    prefs.save(settings.data_dir, scope=st.session_state["scope"])


def _scope(settings: Settings, labels: dict[str, str]) -> str:
    """Whose repositories the dashboard is about. The choice is remembered between visits."""
    scopes = list(labels)
    if len(scopes) == 1:
        return scopes[0]
    remembered = prefs.load(settings.data_dir).get("scope", scopes[0])
    current = st.session_state.get("scope", remembered)
    return str(
        st.selectbox(
            "Scope",
            scopes,
            # The current value as the default too, so the box keeps it across reruns.
            index=scopes.index(current if current in scopes else scopes[0]),
            format_func=labels.__getitem__,
            key="scope",
            bind="query-params",
            on_change=_remember_scope,
            args=(settings,),
            label_visibility="collapsed",
            width=190,
        )
    )


def _repo_links(df: pd.DataFrame, jobs: pd.DataFrame) -> Callable[[str], str | None]:
    """Repository name -> a link to the same view about just that repository, keeping the
    rest of the URL. A link rather than a button so it opens in a new tab too."""
    keys = dict(zip(df["repository"], df["repo"], strict=True))
    if not jobs.empty:  # repositories with runs but no PRs
        keys = dict(zip(jobs["repository"], "github:" + jobs["repo_id"], strict=True)) | keys
    params = {k: st.query_params.get_all(k) for k in st.query_params}

    def link(name: str) -> str | None:
        key = keys.get(name)
        return f"?{urlencode(params | {'repo': [key]}, doseq=True)}" if key else None

    return link


def _top_bar(settings: Settings, store: Store | None, scopes: dict[str, str]) -> tuple[str, str]:
    with st.container(key="brand", width="content"):
        st.markdown("eng·health")
    scope = _scope(settings, scopes)
    # A segmented control rather than st.navigation: AppTest can only switch to file pages.
    view: str = st.segmented_control(
        "View",
        list(VIEWS),
        format_func=VIEWS.__getitem__,
        default="today",
        required=True,
        key="view",
        bind="query-params",
        label_visibility="collapsed",
    )
    with st.container(horizontal=True, vertical_alignment="center", width="content", key="actions"):
        if store is None:
            why = "MOCK_MODE is on" if settings.mock else "nothing is connected"
            st.button(
                "Sample data · Connect",
                help=f"Showing sample data because {why}.",
                key="sample",
                on_click=connect.show,
            )
        else:
            st.caption(_sync_status(settings, store), width="content")
            st.button(
                "Sync now", key="sync_now", on_click=connect.request_sync, args=("incremental",)
            )
        st.button(":material/settings:", help="Settings", key="settings", on_click=connect.show)
    if st.session_state.get("settings_open"):
        connect.drawer(settings, store)
    return view, scope


def main() -> None:
    st.set_page_config(page_title="Engineering health", page_icon="📊", layout="wide")
    # Read on every run, so an edit shows on the next rerun without restarting.
    st.markdown(f"<style>{_STYLE.read_text()}</style>", unsafe_allow_html=True)

    try:
        settings = Settings.from_env()
    except ConfigError as e:
        st.error(f"Configuration problem: {e}")
        st.stop()

    live = bool(settings.platforms) and not settings.mock
    if "logged_start" not in st.session_state:
        st.session_state["logged_start"] = True
        mode = f"live ({', '.join(settings.platforms)})" if live else "sample data"
        log.info("session started: %s, database %s", mode, settings.db_path.resolve())
    try:
        store = Store(settings.db_path) if live else None
    except SchemaError as e:
        st.error(str(e))
        st.stop()

    with st.container(key="header"):
        top = st.container(horizontal=True, vertical_alignment="center")
        bar = st.container(gap="xsmall")
    # Set by the buttons' callbacks, so the sync runs before the data below is read.
    request = st.session_state.pop("sync_request", None)
    if store is not None and request:
        st.caption(
            "Each batch of PRs is saved as it arrives, so stopping a sync keeps its progress."
        )
        run_sync(settings, full=request == "full", reset=request == "reset")
    df, names, repos, me, teams = load(settings, store)
    now, tz = pd.Timestamp.now(tz="UTC"), _browser_timezone()
    scopes = metrics.scopes(df, me, teams, now)
    with top:
        view, scope = _top_bar(settings, store, {k: label for k, (label, _) in scopes.items()})

    github = store is None or bool(settings.github_owner)
    raw, failures = load_pipelines(store) if github else (pd.DataFrame(), pd.DataFrame())
    if df.empty and raw.empty:
        st.info(
            "Nothing synced yet. The first sync reads two years of PRs and can take several "
            "minutes on a large organisation."
        )
        st.button(
            "Sync now",
            type="primary",
            key="first_sync",
            on_click=connect.request_sync,
            args=("full",),
        )
        return

    incomplete = int((~df["details_complete"]).sum())
    if incomplete:
        st.warning(
            f"{incomplete} PRs are missing comments or reviews because fetching them failed. "
            "The next sync retries them."
        )

    with bar:
        label, in_scope = scopes[scope]
        period, chosen = filters.bar(
            df, names, repos, now, tz, tuple(sorted(in_scope or ())), label
        )
    jobs = pl.prepare(raw) if not raw.empty else raw
    # Charts start at the oldest record synced, before any filter, so filtering doesn't move them.
    ci_period = replace(period, start=jobs["started_at"].min()) if not jobs.empty else period
    period = replace(period, start=df["created_at"].min())
    if not jobs.empty:
        # The same repository filter as the PRs': runs are all GitHub's.
        repo = "github:" + jobs["repo_id"]
        jobs = jobs[
            repo.isin(chosen.repositories) if chosen.repositories else ~repo.isin(chosen.hidden)
        ]
    no_ci = (
        "Pipelines come from GitHub Actions. Connect GitHub in Settings to see them."
        if not github
        else "No pipeline runs match. A sync fetches the last 90 days of GitHub Actions runs."
    )
    RENDER[view](
        Context(
            prs=metrics.apply_filters(df, chosen),
            names=names,
            jobs=jobs,
            failures=failures,
            prices=settings.ci_prices,
            period=period,
            ci_period=ci_period,
            now=now,
            tz=tz,
            no_ci=no_ci,
            has_ci=not raw.empty,
            repo_link=_repo_links(df, raw),
            picked=tuple(
                dict(zip(df["repo"], df["repository"], strict=True)).get(k, k)
                for k in chosen.repositories
            )
            if filters.picked("repo")
            else (),
        )
    )
