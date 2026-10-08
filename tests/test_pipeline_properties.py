"""The pipeline metrics against a plain-Python reading of the README's definitions, on random runs.

The definitions are simple; the pandas joins and groupings that compute them are where a bug
would hide, so each property recomputes the answer with loops and compares.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from eng_health import pipelines as pl

from .test_pipelines import job

CONCLUSIONS = ["success", "failure", "timed_out", "cancelled", "skipped"]
JOBS = ["build", "test"]
TESTS = ["t1", "t2", "t3"]


@st.composite
def runs(draw: st.DrawFn) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Job rows for a few runs (small commit pool, so runs share commits), and test failures."""
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for run_id in range(1, draw(st.integers(1, 6)) + 1):
        pipeline = draw(st.sampled_from(["CI", "Nightly"]))
        sha = draw(st.sampled_from(["a", "b", "c"]))
        for attempt in range(1, draw(st.integers(1, 3)) + 1):
            for name in JOBS:
                conclusion = draw(st.sampled_from(CONCLUSIONS))
                rows.append(
                    job(run_id, attempt, conclusion, name, pipeline=pipeline, commit_sha=sha)
                )
        tests = draw(st.sets(st.sampled_from(TESTS), max_size=2))
        failures.extend({"repo_id": "1", "run_id": run_id, "test_id": t} for t in tests)
    return rows, failures


def final_outcomes(rows: list[dict[str, Any]]) -> dict[int, tuple[str, str, str]]:
    """run_id -> (pipeline, commit, conclusion of its last attempt)."""
    last: dict[int, int] = defaultdict(int)
    for r in rows:
        last[r["run_id"]] = max(last[r["run_id"]], r["attempt"])
    out = {}
    for run_id, attempt in last.items():
        jobs = [r for r in rows if r["run_id"] == run_id and r["attempt"] == attempt]
        if any(r["conclusion"] in pl.FAILED for r in jobs):
            conclusion = "failure"
        elif any(r["conclusion"] == "cancelled" for r in jobs):
            conclusion = "cancelled"
        else:
            conclusion = "success"
        out[run_id] = (jobs[0]["pipeline"], jobs[0]["commit_sha"], conclusion)
    return out


@settings(max_examples=150, deadline=None)
@given(runs())
def test_flaky_jobs_match_the_definition(data: tuple[list[dict[str, Any]], Any]) -> None:
    rows, _ = data
    # A job is flaky in a run if it failed in some attempt and succeeded in a later one.
    expected: dict[tuple[str, str], set[int]] = defaultdict(set)
    for f in rows:
        for s in rows:
            if (
                f["run_id"] == s["run_id"]
                and f["name"] == s["name"]
                and f["conclusion"] in pl.FAILED
                and s["conclusion"] == "success"
                and f["attempt"] < s["attempt"]
            ):
                expected[(f["pipeline"], f["name"])].add(f["run_id"])

    got = pl.flaky_jobs(pl.prepare(pd.DataFrame(rows)))
    assert {(r.pipeline, r.name): r.flaky_runs for r in got.itertuples()} == {
        k: len(v) for k, v in expected.items()
    }


@settings(max_examples=150, deadline=None)
@given(runs())
def test_flaky_tests_match_the_definition(data: tuple[list[dict[str, Any]], Any]) -> None:
    rows, failures = data
    final = final_outcomes(rows)
    passed = {(p, sha) for p, sha, c in final.values() if c == "success"}
    # A failed test is flaky if its run finally passed, or a run of the same workflow passed on
    # the same commit.
    expected: dict[str, set[int]] = defaultdict(set)
    for f in failures:
        pipeline, sha, conclusion = final[f["run_id"]]
        if conclusion == "success" or (pipeline, sha) in passed:
            expected[f["test_id"]].add(f["run_id"])

    att = pl.attempts(pl.prepare(pd.DataFrame(rows)))
    got = pl.flaky_tests(pd.DataFrame(failures, columns=["repo_id", "run_id", "test_id"]), att)
    # One row per workflow and test; the oracle counts per test.
    counts = got.groupby("test_id")["flaky_runs"].sum().to_dict() if len(got) else {}
    assert counts == {t: len(runs) for t, runs in expected.items()}


@settings(max_examples=150, deadline=None)
@given(runs())
def test_each_run_has_one_final_attempt_and_rates_are_shares(
    data: tuple[list[dict[str, Any]], Any],
) -> None:
    rows, _ = data
    att = pl.attempts(pl.prepare(pd.DataFrame(rows)))
    assert att.groupby("run_id")["final"].sum().eq(1).all()
    assert dict(zip(att[att["final"]]["run_id"], att[att["final"]]["conclusion"], strict=True)) == {
        run_id: c for run_id, (_, _, c) in final_outcomes(rows).items()
    }
    rates = pl.failure_rate(att)["failed"]
    assert rates.between(0, 1).all()
