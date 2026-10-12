"""Streamlit entry point: the top bar, the filter bar, then the chosen view."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from .. import metrics
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
    if any(s.last_error for s in states):
        return ":red[Last sync failed: see Settings]"
    synced = [s.last_sync for s in states if s.last_sync]
    # The platform synced longest ago is the one the numbers might be stale for.
    return f"Synced {relative(min(synced))}" if len(synced) == len(states) else "Not synced yet"


def _top_bar(settings: Settings, store: Store | None) -> str:
    with st.container(key="brand", width="content"):
        st.markdown("eng·health")
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
    st.space("stretch")
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
        st.button("Sync now", key="sync_now", on_click=connect.request_sync, args=("incremental",))
    st.button(":material/settings:", help="Settings", key="settings", on_click=connect.show)
    if st.session_state.get("settings_open"):
        connect.drawer(settings, store)
    return view


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
        bar = st.container(horizontal=True, vertical_alignment="center", gap="xsmall")
    # Set by the buttons' callbacks, so the sync runs before the data below is read.
    request = st.session_state.pop("sync_request", None)
    if store is not None and request:
        st.caption(
            "Each batch of PRs is saved as it arrives, so stopping a sync keeps its progress."
        )
        run_sync(settings, full=request == "full", reset=request == "reset")
    with top:
        view = _top_bar(settings, store)

    df, names = load(settings, store)
    github = store is None or bool(settings.github_owner)
    raw, failures = load_pipelines(store) if github else (pd.DataFrame(), pd.DataFrame())
    if df.empty and raw.empty:
        st.info(
            "Nothing synced yet. The first sync reads every PR and can take several minutes on "
            "a large organisation."
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

    now, tz = pd.Timestamp.now(tz="UTC"), _browser_timezone()
    with bar:
        period, chosen = filters.bar(df, names, now, tz)
    jobs = pl.prepare(raw) if not raw.empty else raw
    if chosen.repositories and not jobs.empty:
        jobs = jobs[jobs["repository"].isin(chosen.repositories)]
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
            now=now,
            tz=tz,
            no_ci=no_ci,
        )
    )
