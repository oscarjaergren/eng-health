"""CI metrics from the `pipeline_jobs` table (one row per job per run attempt)."""

from __future__ import annotations

import numpy as np
import pandas as pd

FAILED = ("failure", "timed_out")
RUN = ["repository", "pipeline", "run_id"]


def _minutes(df: pd.DataFrame, start: str, end: str) -> pd.Series:
    return (df[end] - df[start]).dt.total_seconds() / 60


def prepare(jobs: pd.DataFrame) -> pd.DataFrame:
    jobs = jobs.copy()
    for col in ("started_at", "finished_at"):
        jobs[col] = pd.to_datetime(jobs[col], utc=True, format="ISO8601")
    jobs["is_default_branch"] = jobs["is_default_branch"].astype(bool)
    jobs["minutes"] = _minutes(jobs, "started_at", "finished_at")
    return jobs


def attempts(jobs: pd.DataFrame) -> pd.DataFrame:
    """One row per run attempt: its span, and failure if any job failed."""
    j = jobs.assign(
        failed=jobs["conclusion"].isin(FAILED), cancelled=jobs["conclusion"] == "cancelled"
    )
    a = j.groupby([*RUN, "attempt"], as_index=False).agg(
        branch=("branch", "first"),
        is_default_branch=("is_default_branch", "first"),
        commit_sha=("commit_sha", "first"),
        started=("started_at", "min"),
        finished=("finished_at", "max"),
        failed=("failed", "any"),
        cancelled=("cancelled", "any"),
    )
    a["conclusion"] = np.select([a["failed"], a["cancelled"]], ["failure", "cancelled"], "success")
    a["minutes"] = _minutes(a, "started", "finished")
    a["final"] = a["attempt"] == a.groupby(RUN)["attempt"].transform("max")
    a["week"] = a["started"].dt.tz_localize(None).dt.to_period("W").dt.start_time
    return a


def failure_rate(att: pd.DataFrame) -> pd.DataFrame:
    """Share of finished runs on the default branch that failed, per workflow and week."""
    done = att[att["final"] & att["is_default_branch"] & (att["conclusion"] != "cancelled")]
    return done.groupby(["week", "pipeline"], as_index=False).agg(failed=("failed", "mean"))


def durations(att: pd.DataFrame) -> pd.DataFrame:
    """Minutes per successful run, per workflow."""
    ok = att[att["final"] & (att["conclusion"] == "success")]
    g = ok.groupby("pipeline")["minutes"]
    out = pd.DataFrame(
        {"Runs": g.size(), "Median (min)": g.median(), "90th pct (min)": g.quantile(0.9)}
    )
    return out.sort_values("Median (min)", ascending=False)


def job_durations(jobs: pd.DataFrame) -> pd.DataFrame:
    ok = jobs[jobs["conclusion"] == "success"]
    g = ok.groupby(["pipeline", "name"])["minutes"]
    out = pd.DataFrame({"Median (min)": g.median(), "90th pct (min)": g.quantile(0.9)})
    return out.sort_values("Median (min)", ascending=False)


def rerun_cost(att: pd.DataFrame) -> pd.DataFrame:
    """Hours spent in attempts that were later re-run, per workflow and week."""
    redone = att[~att["final"]]
    out = redone.groupby(["week", "pipeline"], as_index=False)["minutes"].sum()
    return out.assign(hours=out["minutes"] / 60).drop(columns="minutes")


def flaky_jobs(jobs: pd.DataFrame) -> pd.DataFrame:
    """Jobs that failed and then succeeded in a later attempt of the same run."""
    keys = [*RUN, "name"]
    last_ok = jobs[jobs["conclusion"] == "success"].groupby(keys)["attempt"].max().rename("ok")
    fails = jobs[jobs["conclusion"].isin(FAILED)].join(last_ok, on=keys, how="inner")
    fails = fails[fails["attempt"] < fails["ok"]]
    out = fails.groupby(["repository", "pipeline", "name"]).agg(
        flaky_runs=("run_id", "nunique"),
        minutes_lost=("minutes", "sum"),
        last_seen=("started_at", "max"),
        example=("url", "last"),
    )
    return out.sort_values("flaky_runs", ascending=False).reset_index()
