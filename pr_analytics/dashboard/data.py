"""Loading data for the dashboard and running syncs from it."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from .. import metrics
from ..clients import make_clients
from ..config import Settings
from ..mock import ALIASES as MOCK_ALIASES
from ..mock import mock_pull_requests
from ..models import PLATFORM_NAMES
from ..store import Store
from ..sync import sync


@st.cache_data(show_spinner=False)
def _load_store(
    db_path: str, version: int, aliases: tuple[tuple[str, str], ...]
) -> tuple[pd.DataFrame, dict[str, str]]:
    store = Store(db_path)
    return metrics.to_frame(store.pull_requests(), dict(aliases)), store.people()


@st.cache_data(show_spinner=False)
def _load_mock(day: str) -> tuple[pd.DataFrame, dict[str, str]]:
    prs, people = mock_pull_requests()
    return metrics.to_frame(prs, MOCK_ALIASES), people


def load(settings: Settings, store: Store | None) -> tuple[pd.DataFrame, dict[str, str]]:
    if store is None:
        # Keyed by day so the sample data stays anchored to "now".
        return _load_mock(datetime.now(UTC).date().isoformat())
    # `version` is only there to change the cache key after a sync.
    return _load_store(str(store.path), store.version(), tuple(sorted(settings.aliases.items())))


def run_sync(settings: Settings, store: Store, *, full: bool = False) -> None:
    with st.status("Syncing pull requests…", expanded=True) as status:
        bar = st.progress(0.0)

        def progress(frac: float, msg: str) -> None:
            bar.progress(min(frac, 1.0), text=msg)

        reports = sync(
            make_clients(settings),
            store,
            full=full,
            max_workers=settings.max_workers,
            progress=progress,
        )
        bar.empty()
        for r in reports:
            line = (
                f"**{PLATFORM_NAMES[r.platform]}**: {r.repositories} repositories, "
                f"{r.listed} PRs checked, {r.saved} updated"
            )
            if r.incomplete:
                line += f", {r.incomplete} missing review data (will retry)"
            st.markdown(line)
            for err in r.errors[:10]:
                st.error(err)
        ok = all(r.ok for r in reports)
        status.update(
            label="Sync finished" if ok else "Sync finished with errors",
            state="complete" if ok else "error",
        )
    st.session_state["sync_done"] = ok


def relative(t: datetime | None) -> str:
    if t is None:
        return "never"
    secs = (datetime.now(UTC) - t).total_seconds()
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if secs >= size:
            n = int(secs // size)
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"
