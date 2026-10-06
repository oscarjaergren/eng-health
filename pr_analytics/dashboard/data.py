"""Loading data for the dashboard and running syncs from it."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from .. import metrics, prsync
from ..config import Settings
from ..mock import ALIASES as MOCK_ALIASES
from ..mock import mock_pull_requests
from ..models import PLATFORM_NAMES
from ..store import Store


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


def run_sync(settings: Settings, *, full: bool = False, reset: bool = False) -> None:
    binary = prsync.find_binary()
    if binary is None:
        st.error(
            "The `prsync` sync engine was not found. The Docker image includes it; "
            "otherwise build it with `cargo build --release` in `sync/`, or set PRSYNC_BIN."
        )
        return

    with st.status("Syncing pull requests…", expanded=True) as status:
        bar = st.progress(0.0)

        def progress(frac: float, msg: str) -> None:
            bar.progress(min(frac, 1.0), text=msg)

        result = prsync.run(binary, settings, full=full, reset=reset, on_progress=progress)
        bar.empty()
        for r in result.reports:
            name = PLATFORM_NAMES.get(r.platform, r.platform)
            what = "runs" if r.module == "pipelines" else "PRs"
            line = (
                f"**{name}{' pipelines' if r.module == 'pipelines' else ''}**: "
                f"{r.repositories} repositories, {r.listed} {what} checked, {r.saved} updated, "
                f"{r.requests} API requests"
            )
            if r.incomplete:
                line += f", {r.incomplete} incomplete (will retry)"
            st.markdown(line)
            for err in r.errors[:10]:
                st.error(err)
        if result.exit_code == prsync.EXIT_INTERRUPTED:
            label = "Sync stopped; what was fetched so far is saved"
        elif not result.ok and not any(r.errors for r in result.reports):
            # Nothing structured to show (bad configuration, crash): show its output.
            lines = result.stderr.strip().splitlines()
            st.error(lines[-1] if lines else "prsync failed")
            label = "Sync failed"
        else:
            label = "Sync finished" if result.ok else "Sync finished with errors"
        status.update(label=label, state="complete" if result.ok else "error")


def relative(t: datetime | None) -> str:
    if t is None:
        return "never"
    secs = (datetime.now(UTC) - t).total_seconds()
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if secs >= size:
            n = int(secs // size)
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"
