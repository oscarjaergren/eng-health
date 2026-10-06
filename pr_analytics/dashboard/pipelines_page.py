"""Pipelines view: failure rate, slow pipelines, rerun cost and flaky jobs."""

from __future__ import annotations

import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from .. import pipelines as pl
from ..store import Store
from .charts import show

log = logging.getLogger(__name__)


@st.cache_data(show_spinner=False)
def _load(db_path: str, version: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    # `version` is only there to change the cache key after a sync.
    store = Store(db_path)
    jobs, failures = store.pipeline_jobs(), store.test_failures()
    log.info("loaded %d pipeline jobs and %d test failures", len(jobs), len(failures))
    return jobs, failures


def _filter(jobs: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filters")
    repos = st.sidebar.multiselect(
        "Repository", sorted(jobs["repository"].unique()), placeholder="All repositories"
    )
    if repos:
        jobs = jobs[jobs["repository"].isin(repos)]
    workflows = st.sidebar.multiselect(
        "Workflow", sorted(jobs["pipeline"].unique()), placeholder="All workflows"
    )
    if workflows:
        jobs = jobs[jobs["pipeline"].isin(workflows)]
    if st.sidebar.toggle("Default branch only", value=False):
        jobs = jobs[jobs["is_default_branch"]]
    return jobs


def render(store: Store | None, github: bool) -> None:
    st.title("Pipelines")
    if store is None or not github:
        st.info("Pipelines come from GitHub Actions. Connect GitHub to see them.")
        return
    raw, failures = _load(str(store.path), store.version())
    if raw.empty:
        st.info("No pipeline data yet. Sync to fetch the last 90 days of GitHub Actions runs.")
        return
    jobs = _filter(pl.prepare(raw))
    if jobs.empty:
        st.info("No runs match these filters.")
        return
    att = pl.attempts(jobs)
    rates = pl.failure_rate(att)
    reruns = pl.rerun_cost(att)
    flaky = pl.flaky_jobs(jobs)
    tests = pl.flaky_tests(failures, att) if not failures.empty else pd.DataFrame()

    overview, slow, rerun_tab, flaky_tab = st.tabs(["Overview", "Slow", "Reruns", "Flaky"])
    with overview:
        final = att[att["final"]]
        default = final[final["is_default_branch"] & (final["conclusion"] != "cancelled")]
        c = st.columns(4)
        c[0].metric("Runs", len(final))
        c[1].metric(
            "Failure rate (default branch)",
            f"{default['failed'].mean():.0%}" if len(default) else "–",
            help="Share of finished runs on the default branch whose final attempt failed.",
        )
        lost = reruns["hours"].sum()
        c[2].metric("Lost to reruns", f"{lost:.1f} h" if lost >= 1 else f"{lost * 60:.0f} min")
        c[3].metric("Flaky jobs / tests", f"{len(flaky)} / {len(tests)}")
        if not rates.empty:
            fig = px.line(
                rates,
                x="week",
                y="failed",
                color="pipeline",
                markers=True,
                title="Failure rate on the default branch, by week",
                labels={"failed": "Failure rate", "week": ""},
            )
            fig.update_yaxes(tickformat=".0%")
            show(fig)

    with slow:
        st.dataframe(pl.durations(att), width="stretch", column_config=_minutes_cols())
        ok = att[att["final"] & (att["conclusion"] == "success")]
        trend = ok.groupby(["week", "pipeline"], as_index=False)["minutes"].median()
        if not trend.empty:
            show(
                px.line(
                    trend,
                    x="week",
                    y="minutes",
                    color="pipeline",
                    markers=True,
                    title="Median run time, by week",
                    labels={"minutes": "Minutes", "week": ""},
                )
            )
        st.subheader("Slowest jobs")
        st.dataframe(
            pl.job_durations(jobs).head(20), width="stretch", column_config=_minutes_cols()
        )

    with rerun_tab:
        if reruns.empty:
            st.success("No reruns in this selection.")
        else:
            show(
                px.bar(
                    reruns,
                    x="week",
                    y="hours",
                    color="pipeline",
                    title="Hours spent in attempts that were re-run",
                    labels={"week": ""},
                )
            )

    with flaky_tab:
        st.subheader("Flaky tests")
        st.caption("Tests that failed in a run that then passed on the same commit.")
        if failures.empty:
            st.info(
                "No test results found. prsync reads JUnit or TRX files from artifacts whose "
                "name contains test, junit, trx or result. For example, after `dotnet test "
                "--logger trx`: `uses: actions/upload-artifact@v4` with `name: test-results`, "
                "`path: '**/*.trx'` and `if: always()`."
            )
        elif tests.empty:
            st.success("No flaky tests in this selection.")
        else:
            st.dataframe(
                tests,
                width="stretch",
                hide_index=True,
                column_config={
                    "test_id": "Test",
                    "flaky_runs": "Flaky runs",
                    "last_seen": st.column_config.DatetimeColumn("Last seen", format="YYYY-MM-DD"),
                },
            )
        st.subheader("Flaky jobs")
        st.caption("Jobs that failed, then passed when the same run was re-run.")
        if flaky.empty:
            st.success("No flaky jobs in this selection.")
        else:
            st.dataframe(
                flaky,
                width="stretch",
                hide_index=True,
                column_config={
                    "flaky_runs": "Flaky runs",
                    "minutes_lost": st.column_config.NumberColumn("Minutes lost", format="%.0f"),
                    "last_seen": st.column_config.DatetimeColumn("Last seen", format="YYYY-MM-DD"),
                    "example": st.column_config.LinkColumn("Example", display_text="Open"),
                },
            )


def _minutes_cols() -> dict:
    fmt = st.column_config.NumberColumn(format="%.1f")
    return {"Median (min)": fmt, "90th pct (min)": fmt}
