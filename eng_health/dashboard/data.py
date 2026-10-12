"""Loading data for the dashboard and running syncs from it."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import NamedTuple

import pandas as pd
import streamlit as st

from .. import metrics, sync
from ..config import Settings
from ..mock import ALIASES as MOCK_ALIASES
from ..mock import ME, TEAMS, mock_pipelines, mock_pull_requests, mock_repositories
from ..models import PLATFORM_NAMES, Team
from ..store import Store

log = logging.getLogger(__name__)


class Data(NamedTuple):
    prs: pd.DataFrame
    names: dict[str, str]  # identity -> display name
    repos: pd.DataFrame  # the store's repositories table
    me: frozenset[str]  # the identities "Mine" is about, after aliases
    teams: tuple[Team, ...]  # members after aliases


def _aliased(teams: list[Team], aliases: Mapping[str, str]) -> tuple[Team, ...]:
    return tuple(replace(t, members=frozenset(aliases.get(m, m) for m in t.members)) for t in teams)


@st.cache_data(show_spinner=False)
def _load_store(db_path: str, version: int, aliases: tuple[tuple[str, str], ...]) -> Data:
    store = Store(db_path)
    prs, repos = store.pull_requests(), store.repositories()
    log.info("loaded %d PRs from %s (revision %d)", len(prs), db_path, version)
    a = dict(aliases)
    df = metrics.name_repositories(metrics.to_frame(prs, a), repos)
    me = frozenset(a.get(i, i) for i in store.me().values())
    return Data(df, store.people(), repos, me, _aliased(store.teams(), a))


@st.cache_data(show_spinner=False)
def _load_mock(day: str) -> Data:
    prs, people = mock_pull_requests()
    repos = pd.DataFrame(mock_repositories())
    log.info("generated %d sample PRs for %s", len(prs), day)
    df = metrics.name_repositories(metrics.to_frame(prs, MOCK_ALIASES), repos)
    me = frozenset(MOCK_ALIASES.get(i, i) for i in ME.values())
    return Data(df, people, repos, me, _aliased(TEAMS, MOCK_ALIASES))


def load(settings: Settings, store: Store | None) -> Data:
    if store is None:
        # Keyed by day so the sample data stays anchored to "now".
        return _load_mock(datetime.now(UTC).date().isoformat())
    # `version` is only there to change the cache key after a sync.
    return _load_store(str(store.path), store.version(), tuple(sorted(settings.aliases.items())))


@st.cache_data(show_spinner=False)
def _load_pipelines(db_path: str, version: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    # `version` changes the cache key after a sync.
    store = Store(db_path)
    jobs, failures = store.pipeline_jobs(), store.test_failures()
    log.info(
        "loaded %d pipeline jobs and %d test failures (revision %d)",
        len(jobs),
        len(failures),
        version,
    )
    return jobs, failures


@st.cache_data(show_spinner=False)
def _sample_pipelines(day: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    jobs, failures = mock_pipelines()
    log.info("generated %d sample pipeline jobs for %s", len(jobs), day)
    return pd.DataFrame(jobs), pd.DataFrame(failures)


def load_pipelines(store: Store | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Jobs and test failures: sample data without a store."""
    if store is None:
        return _sample_pipelines(datetime.now(UTC).date().isoformat())
    return _load_pipelines(str(store.path), store.version())


def run_sync(settings: Settings, *, full: bool = False, reset: bool = False) -> None:
    binary = sync.find_binary()
    if binary is None:
        st.error(
            "The `eng-health` sync engine was not found. The Docker image includes it; "
            "otherwise build it with `cargo build --release` in `sync/`, or set ENG_HEALTH_BIN."
        )
        return

    with st.status("Syncing pull requests…", expanded=True) as status:
        bar = st.progress(0.0)

        def progress(frac: float, msg: str) -> None:
            bar.progress(min(frac, 1.0), text=msg)

        result = sync.run(binary, settings, full=full, reset=reset, on_progress=progress)
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
        if result.exit_code == sync.EXIT_INTERRUPTED:
            label = "Sync stopped; what was fetched so far is saved"
        elif not result.ok and not any(r.errors for r in result.reports):
            # Nothing structured to show (bad configuration, crash): show its output.
            lines = result.stderr.strip().splitlines()
            st.error(lines[-1] if lines else "eng-health failed")
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
