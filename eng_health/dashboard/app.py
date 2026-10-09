"""Streamlit entry point."""

from __future__ import annotations

import logging
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st
from dotenv import load_dotenv
from streamlit.delta_generator import DeltaGenerator

from .. import metrics
from ..config import ConfigError, Settings
from ..models import PLATFORM_NAMES
from ..store import SchemaError, Store
from . import pipelines_page
from .data import load, relative, run_sync
from .filters import sidebar_filters
from .tabs import flow, overview, people, size, table, timing

# Module level, so it runs once per process rather than on every rerun.
load_dotenv()
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def _browser_timezone() -> str:
    tz = st.context.timezone or "UTC"
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError, ValueError:
        return "UTC"
    return tz


def _data_source(settings: Settings, store: Store | None) -> DeltaGenerator | None:
    """Draw the sidebar's data section. Returns a slot for the sync status, which
    is filled after any sync this run so it is never stale."""
    st.sidebar.header("Data")
    if store is None:
        why = "MOCK_MODE is on" if settings.mock else "no credentials are configured"
        st.sidebar.info(
            f"Showing generated sample data because {why}. "
            "See the README to connect Azure DevOps or GitHub."
        )
        return None

    status = st.sidebar.container()
    if st.sidebar.button("Sync now", type="primary", width="stretch"):
        st.session_state["sync_request"] = "incremental"
    with st.sidebar.expander("More sync options"):
        st.caption("Sync fetches only what changed. These re-read everything and can take a while.")
        if st.button("Re-read all PRs", width="stretch"):
            st.session_state["sync_request"] = "full"
        confirm = st.checkbox("I want to delete the local data")
        if st.button("Delete local data and resync", disabled=not confirm, width="stretch"):
            st.session_state["sync_request"] = "reset"
    return status


def _sync_status(settings: Settings, store: Store, slot: DeltaGenerator) -> None:
    owners = {"azure_devops": settings.azure_organization, "github": settings.github_owner}
    for platform in settings.platforms:
        state = store.sync_state(platform)
        slot.markdown(f"**{PLATFORM_NAMES[platform]}** · {owners[platform]}")
        slot.caption(f"Last synced {relative(state.last_sync)}")
        if state.last_error:
            slot.error(f"Last sync failed: {state.last_error}", icon=None)
    if settings.github_owner:
        state = store.sync_state("github:pipelines")
        slot.caption(f"Pipelines synced {relative(state.last_sync)}")
        if state.last_error:
            slot.error(f"Last pipelines sync failed: {state.last_error}", icon=None)


def main() -> None:
    st.set_page_config(page_title="Engineering health", page_icon="📊", layout="wide")

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
    slot = _data_source(settings, store)

    request = st.session_state.pop("sync_request", None)
    if store is not None and request:
        st.caption(
            "Each batch of PRs is saved as it arrives, so stopping a sync keeps its progress."
        )
        run_sync(settings, full=request == "full", reset=request == "reset")
    if store is not None and slot is not None:
        _sync_status(settings, store, slot)

    if st.sidebar.radio("View", ["Pull requests", "Pipelines"], horizontal=True) == "Pipelines":
        pipelines_page.render(store, github=bool(settings.github_owner))
        return

    st.title("Pull request analytics")
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

    tabs = st.tabs(["Overview", "Flow", "Size", "People", "Timing", "Data"])
    with tabs[0]:
        overview.render(filtered, tz)
    with tabs[1]:
        flow.render(filtered, names, tz)
    with tabs[2]:
        size.render(filtered, tz)
    with tabs[3]:
        people.render(filtered, names)
    with tabs[4]:
        timing.render(filtered, tz)
    with tabs[5]:
        table.render(filtered, names)
