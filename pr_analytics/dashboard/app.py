"""Streamlit entry point."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st
from dotenv import load_dotenv

from .. import metrics
from ..config import ConfigError, Settings
from ..models import PLATFORM_NAMES
from ..store import Store
from .data import load, relative, run_sync
from .filters import sidebar_filters
from .tabs import flow, overview, people, table, timing


def _browser_timezone() -> str:
    tz = st.context.timezone or "UTC"
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return tz


def _data_source(settings: Settings, store: Store | None) -> None:
    st.sidebar.header("Data")
    if store is None:
        why = "MOCK_MODE is on" if settings.mock else "no credentials are configured"
        st.sidebar.info(
            f"Showing generated sample data because {why}. "
            "See the README to connect Azure DevOps or GitHub."
        )
        return

    owners = {
        "azure_devops": settings.azure.organization if settings.azure else "",
        "github": settings.github.owner if settings.github else "",
    }
    for platform in settings.platforms:
        state = store.sync_state(platform)
        owner = owners[platform]
        st.sidebar.markdown(f"**{PLATFORM_NAMES[platform]}** · {owner}")
        st.sidebar.caption(f"Last synced {relative(state.last_sync)}")
        if state.last_error:
            st.sidebar.error(f"Last sync failed: {state.last_error}", icon=None)

    if st.sidebar.button("Sync now", type="primary", width="stretch"):
        st.session_state["sync_request"] = "incremental"
    with st.sidebar.expander("More sync options"):
        st.caption("Sync fetches only what changed. These re-read everything and can take a while.")
        if st.button("Re-read all PRs", width="stretch"):
            st.session_state["sync_request"] = "full"
        confirm = st.checkbox("I want to delete the local data")
        if st.button("Delete local data and resync", disabled=not confirm, width="stretch"):
            st.session_state["sync_request"] = "reset"


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="PR Analytics", page_icon="📊", layout="wide")
    st.title("Pull request analytics")

    try:
        settings = Settings.from_env()
    except ConfigError as e:
        st.error(f"Configuration problem: {e}")
        st.stop()

    live = bool(settings.platforms) and not settings.mock
    store = Store(settings.db_path) if live else None
    _data_source(settings, store)

    request = st.session_state.pop("sync_request", None)
    if store is not None and request:
        if request == "reset":
            store.clear()
        st.caption(
            "Each batch of PRs is saved as it arrives, so stopping a sync keeps its progress."
        )
        run_sync(settings, store, full=request != "incremental")

    df, names = load(settings, store)
    if df.empty:
        st.info(
            "No pull requests synced yet. The first sync reads every PR and can take "
            "several minutes on a large organisation."
        )
        if st.button("Sync now", type="primary", key="first_sync"):
            st.session_state["sync_request"] = "full"
            st.rerun()
        return

    incomplete = int((~df["details_complete"]).sum())
    if incomplete:
        st.warning(
            f"{incomplete} PRs are missing comments or reviews because fetching them failed. "
            "The next sync retries them."
        )

    tz = _browser_timezone()
    filters = sidebar_filters(df, names, tz)
    filtered = metrics.apply_filters(df, filters)
    st.sidebar.caption(f"{len(filtered)} of {len(df)} PRs match")
    if filtered.empty:
        st.info("No pull requests match these filters.")
        return

    tabs = st.tabs(["Overview", "Flow", "People", "Timing", "Data"])
    with tabs[0]:
        overview.render(filtered, tz)
    with tabs[1]:
        flow.render(filtered, names, tz)
    with tabs[2]:
        people.render(filtered, names)
    with tabs[3]:
        timing.render(filtered, tz)
    with tabs[4]:
        table.render(filtered, names)
