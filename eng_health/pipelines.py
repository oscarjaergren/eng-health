"""CI metrics from the `pipeline_jobs` table (one row per job per run attempt)."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .period import Period, between, sparklines

FAILED = ("failure", "timed_out")
FLAKY_TEST_COLUMNS = ["repository", "pipeline", "test_id", "flaky_runs", "first_seen", "last_seen"]
RUN = ["repository", "pipeline", "run_id"]


def _minutes(df: pd.DataFrame, start: str, end: str) -> pd.Series:
    return (df[end] - df[start]).dt.total_seconds() / 60


def prepare(jobs: pd.DataFrame) -> pd.DataFrame:
    jobs = jobs.copy()
    for col in ("started_at", "finished_at"):
        jobs[col] = pd.to_datetime(jobs[col], utc=True, format="ISO8601")
    jobs["is_default_branch"] = jobs["is_default_branch"].astype(bool)
    # A database from before runner and is_private, until the next sync refetches its jobs.
    jobs["runner"] = jobs.get("runner", "linux")
    jobs["is_private"] = jobs.get("is_private", 1)
    jobs["is_private"] = jobs["is_private"].astype(bool)
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
    return a


def failure_rate(att: pd.DataFrame, period: Period, now: pd.Timestamp, tz: str) -> pd.DataFrame:
    """Percent of finished runs on the default branch that failed: a row per bucket, a column
    per workflow."""
    done = att[att["final"] & att["is_default_branch"] & (att["conclusion"] != "cancelled")]
    return period.each(
        now,
        tz,
        lambda a, b: (
            done[between(done["started"], a, b)].groupby("pipeline")["failed"].mean() * 100
        ),
    )


def _verdicts(att: pd.DataFrame) -> pd.DataFrame:
    """The default-branch runs that say whether the code works, oldest first: final attempts,
    not cancelled, and not GitHub's own workflows (Dependabot, default CodeQL), whose failing
    doesn't mean the code is broken."""
    runs = att[
        att["final"]
        & att["is_default_branch"]
        & (att["conclusion"] != "cancelled")
        & ~att["pipeline"].str.startswith("dynamic/")
    ]
    return runs.dropna(subset=["finished"]).sort_values("finished")


def failing(att: pd.DataFrame) -> pd.DataFrame:
    """The workflows whose latest default-branch run failed: what broke each broken main."""
    latest = _verdicts(att).groupby(["repository", "pipeline"]).tail(1)
    return latest.loc[latest["failed"], ["repository", "pipeline"]]


def broken(att: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Each stretch a repository's default branch was broken: from a workflow failing there to it
    passing again, with its workflows' overlapping stretches merged. `end` is NaT while it still
    is."""
    runs = _verdicts(att)
    keys = [runs["repository"], runs["pipeline"]]
    # A failure after a pass starts a stretch, which ends when that workflow next passes.
    starts = runs["failed"] & ~runs.groupby(keys)["failed"].shift(fill_value=False)
    passes = runs["finished"].where(~runs["failed"]).groupby(keys).bfill()
    s = pd.DataFrame({"repository": runs["repository"], "start": runs["finished"], "end": passes})
    s = s[starts].assign(end=lambda d: d["end"].fillna(now)).sort_values(["repository", "start"])
    if s.empty:
        return pd.DataFrame({"repository": [], "start": [], "end": []}).astype(
            {"start": "datetime64[ns, UTC]", "end": "datetime64[ns, UTC]"}
        )
    # A stretch that starts after every earlier one in its repository has ended starts a block.
    reach = s.groupby("repository")["end"].cummax().groupby(s["repository"]).shift()
    block = (s["start"] > reach) | reach.isna()
    merged = s.groupby(["repository", block.cumsum()]).agg(
        start=("start", "min"), end=("end", "max")
    )
    merged["end"] = merged["end"].mask(merged["end"] >= now)
    return merged.reset_index(level="repository").reset_index(drop=True)


def broken_hours(
    stretches: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, now: pd.Timestamp
) -> pd.Series:
    """Hours each repository's default branch was broken in (start, end]."""
    until = stretches["end"].fillna(now)
    until = until.mask(until > end, end)
    since = stretches["start"].mask(stretches["start"] < start, start)
    hours = ((until - since).dt.total_seconds() / 3600).clip(lower=0)
    per_repository: pd.Series = hours.groupby(stretches["repository"]).sum()
    return per_repository


def repositories(
    att: pd.DataFrame,
    jobs: pd.DataFrame,
    stretches: pd.DataFrame,
    period: Period,
    now: pd.Timestamp,
    tz: str,
) -> pd.DataFrame:
    """Per repository, in the period: runs, the default branch's failure rate and hours broken,
    since when it has been broken if it still is, time lost to reruns and flaky jobs; and hours
    broken per bucket. Broken ones first."""
    start, end = period.window(now)
    a = att[between(att["started"], start, end)]
    final = a[a["final"]]
    done = final[final["is_default_branch"] & (final["conclusion"] != "cancelled")]
    flaky = flaky_jobs(jobs[between(jobs["started_at"], start, end)])
    out = pd.DataFrame(
        {
            "Runs": final.groupby("repository").size(),
            "Failure rate": done.groupby("repository")["failed"].mean() * 100,
            "Broken (h)": broken_hours(stretches, start, end, now),
            "Lost to reruns (h)": a[~a["final"]].groupby("repository")["minutes"].sum() / 60,
            "Flaky jobs": flaky.groupby("repository").size(),
        }
    ).rename_axis("repository")
    counts = ["Runs", "Broken (h)", "Lost to reruns (h)", "Flaky jobs"]
    out[counts] = out[counts].fillna(0)
    still = stretches[stretches["end"].isna()].set_index("repository")["start"]
    out["Broken since"] = still.reindex(out.index)
    per_bucket = period.each(now, tz, lambda a, b: broken_hours(stretches, a, b, now))
    out["Trend"] = sparklines(per_bucket.fillna(0), out.index)
    return out.sort_values(
        ["Broken since", "Broken (h)", "Failure rate"],
        ascending=[True, False, False],
        na_position="last",
    )


def run_times(
    att: pd.DataFrame, pipeline: str, period: Period, now: pd.Timestamp, tz: str
) -> pd.DataFrame:
    """Median and 90th percentile minutes of one workflow's successful runs, per bucket."""
    ok = att[att["final"] & (att["conclusion"] == "success") & (att["pipeline"] == pipeline)]

    def stats(a: pd.Timestamp, b: pd.Timestamp) -> dict[str, float]:
        m = ok.loc[between(ok["started"], a, b), "minutes"]
        return {"Median": m.median(), "p90": m.quantile(0.9)}

    return period.each(now, tz, stats)


def durations(att: pd.DataFrame) -> pd.DataFrame:
    """Minutes per successful run, per workflow."""
    ok = att[att["final"] & (att["conclusion"] == "success")]
    g = ok.groupby("pipeline")["minutes"]
    out = pd.DataFrame(
        {"Runs": g.size(), "Median (min)": g.median(), "90th pct (min)": g.quantile(0.9)}
    )
    return out.sort_values("Median (min)", ascending=False)


def slowest_jobs(jobs: pd.DataFrame, period: Period, now: pd.Timestamp, tz: str) -> pd.DataFrame:
    """Per job, from its successful runs: median and 90th percentile minutes in the period, the
    median's change on the period before, and the median per bucket."""
    ok = jobs[jobs["conclusion"] == "success"]
    keys = ["pipeline", "name"]

    def median(a: pd.Timestamp, b: pd.Timestamp) -> pd.Series:
        return ok[between(ok["started_at"], a, b)].groupby(keys)["minutes"].median()

    g = ok[between(ok["started_at"], *period.window(now))].groupby(keys)["minutes"]
    out = pd.DataFrame({"Median (min)": g.median(), "90th pct (min)": g.quantile(0.9)})
    out["Change"] = out["Median (min)"] / median(*period.window(now, back=1)).reindex(out.index) - 1
    out["Trend"] = sparklines(period.each(now, tz, median), out.index)
    return out.sort_values("Median (min)", ascending=False)


def flaky_jobs(jobs: pd.DataFrame) -> pd.DataFrame:
    """Jobs that failed and then succeeded in a later attempt of the same run."""
    keys = [*RUN, "name"]
    ok = jobs[jobs["conclusion"] == "success"]
    last_ok = ok.groupby(keys, as_index=False).agg(ok=("attempt", "max"))
    # merge, not join: an inner join on an empty frame takes the other side's index, and the
    # groupby below then finds "repository" as both a column and an index level.
    fails = jobs[jobs["conclusion"].isin(FAILED)].merge(last_ok, on=keys)
    fails = fails[fails["attempt"] < fails["ok"]]
    out = fails.groupby(["repository", "pipeline", "name"]).agg(
        flaky_runs=("run_id", "nunique"),
        minutes_lost=("minutes", "sum"),
        first_seen=("started_at", "min"),
        last_seen=("started_at", "max"),
        example=("url", "last"),
    )
    return out.sort_values("flaky_runs", ascending=False).reset_index()


def flaky_tests(failures: pd.DataFrame, att: pd.DataFrame) -> pd.DataFrame:
    """Tests that failed in a run that then passed: a later attempt of the same
    run, or another run of the same workflow on the same commit."""
    final = att[att["final"]]
    passed = final.loc[final["conclusion"] == "success", ["pipeline", "commit_sha"]]
    passed_keys = pd.MultiIndex.from_frame(passed.drop_duplicates())
    # GitHub run ids are unique across repositories.
    cols = ["run_id", "repository", "pipeline", "commit_sha", "started"]
    f = failures.merge(final[cols], on="run_id")
    retried_ok = f["run_id"].isin(final.loc[final["conclusion"] == "success", "run_id"])
    same_commit_ok = pd.MultiIndex.from_frame(f[["pipeline", "commit_sha"]]).isin(passed_keys)
    flaky = f[retried_ok | same_commit_ok]
    out = flaky.groupby(["repository", "pipeline", "test_id"]).agg(
        flaky_runs=("run_id", "nunique"),
        first_seen=("started", "min"),
        last_seen=("started", "max"),
    )
    return out.sort_values("flaky_runs", ascending=False).reset_index()


def billed(jobs: pd.DataFrame, prices: Mapping[str, float]) -> pd.DataFrame:
    """Jobs with billable minutes and estimated cost, and whether their attempt was re-run.
    GitHub rounds each job up to a whole minute and bills every attempt on every branch; public
    repositories run free on standard runners."""
    minutes = np.ceil(jobs["minutes"].fillna(0).clip(lower=0))
    price = jobs["runner"].map(prices).fillna(0) * jobs["is_private"]
    rerun = jobs["attempt"] < jobs.groupby(RUN)["attempt"].transform("max")
    return jobs.assign(billed=minutes, cost=minutes * price, rerun=rerun)


def minutes_by_pipeline(
    billed: pd.DataFrame, period: Period, now: pd.Timestamp, tz: str
) -> pd.DataFrame:
    """Billed minutes: a row per bucket, a column per workflow."""
    return period.each(
        now,
        tz,
        lambda a, b: (
            billed[between(billed["started_at"], a, b)].groupby("pipeline")["billed"].sum()
        ),
    ).fillna(0)


def cost_by(
    billed: pd.DataFrame, by: str, period: Period, now: pd.Timestamp, tz: str
) -> pd.DataFrame:
    """Per `by` (repository or pipeline): billed minutes and estimated cost in the period, the
    share of all minutes, the change in minutes on the period before, and minutes per bucket."""

    def window(back: int) -> pd.DataFrame:
        b = billed[between(billed["started_at"], *period.window(now, back))]
        return b.groupby(by)[["billed", "cost"]].sum()

    now_, before = window(0), window(1)
    out = pd.DataFrame({"Minutes": now_["billed"], "Est. cost ($)": now_["cost"]})
    out["Share"] = out["Minutes"] / out["Minutes"].sum()
    was = before["billed"].reindex(out.index)
    out["Change"] = (out["Minutes"] - was) / was.where(was > 0)
    trend = period.each(
        now,
        tz,
        lambda a, b: billed[between(billed["started_at"], a, b)].groupby(by)["billed"].sum(),
    )
    out["Trend"] = sparklines(trend.fillna(0), out.index)
    return out.rename_axis(by).sort_values("Minutes", ascending=False)
