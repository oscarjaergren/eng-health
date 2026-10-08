from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from eng_health import metrics
from eng_health.models import PullRequest, State

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def pr(number: int, **kw: Any) -> PullRequest:
    base: dict[str, Any] = {
        "platform": "github",
        "repo_id": "1",
        "repository": "web",
        "number": number,
        "title": f"PR {number}",
        "author": "alice",
        "state": State.MERGED,
        "is_draft": False,
        "created_at": T0,
        "closed_at": T0 + timedelta(hours=10),
        "url": "",
        "is_infrastructure": False,
    }
    base.update(kw)
    return PullRequest(**base)


def frame(*prs: PullRequest, aliases: dict[str, str] | None = None) -> pd.DataFrame:
    return metrics.to_frame(prs, aliases)


def test_cycle_and_first_review_hours() -> None:
    df = frame(
        pr(1, first_responses={"bob": T0 + timedelta(hours=2)}),
        pr(2, state=State.OPEN, closed_at=None),
    )
    assert df["cycle_hours"].tolist()[0] == 10
    assert pd.isna(df["cycle_hours"].tolist()[1])  # not merged
    assert df["first_review_hours"].tolist()[0] == 2


def test_filters_default_to_excluding_infrastructure() -> None:
    df = frame(pr(1), pr(2, is_infrastructure=True), pr(3, is_draft=True))
    assert metrics.apply_filters(df, metrics.Filters())["number"].tolist() == [1, 3]
    f = metrics.Filters(include_infrastructure=True, include_drafts=False)
    assert metrics.apply_filters(df, f)["number"].tolist() == [1, 2]


def test_date_filter_uses_local_day() -> None:
    late = datetime(2026, 9, 1, 23, 30, tzinfo=UTC)  # already 2 September in Berlin
    df = frame(pr(1, created_at=late))
    utc = metrics.Filters(start=date(2026, 9, 2), tz="UTC")
    berlin = metrics.Filters(start=date(2026, 9, 2), tz="Europe/Berlin")
    assert metrics.apply_filters(df, utc).empty
    assert len(metrics.apply_filters(df, berlin)) == 1


def test_reviewer_activity_and_own_comments() -> None:
    df = frame(
        pr(1, approvers=["bob"], comment_counts={"bob": 2, "alice": 3},
           first_responses={"bob": T0 + timedelta(hours=4)}),
        pr(2, author="bob", rejecters=["carol"], comment_counts={"carol": 1},
           first_responses={"carol": T0 + timedelta(hours=1)}),
        pr(3, author="dave"),
    )  # fmt: skip
    act = metrics.reviewer_activity(df)
    assert act.loc["bob", "Approvals"] == 1
    assert act.loc["bob", "Comments"] == 2
    assert act.loc["alice", "Comments"] == 0  # replies on her own PR
    assert act.loc["carol", "Change requests"] == 1
    assert act.loc["bob", "Median response (h)"] == 4
    with_own = metrics.reviewer_activity(df, exclude_own_comments=False)
    assert with_own.loc["alice", "Comments"] == 3
    assert metrics.non_reviewers(act).index.tolist() == ["alice", "dave"]


def test_aliases_merge_identities() -> None:
    df = frame(
        pr(1, comment_counts={"bob": 1, "bob@example.com": 2}),
        aliases={"bob": "bob@example.com"},
    )
    assert df["comment_counts"][0] == {"bob@example.com": 3}


def test_stale_open_ignores_drafts_and_recent() -> None:
    now = T0 + timedelta(days=10)
    df = frame(
        pr(1, state=State.OPEN, closed_at=None),
        pr(2, state=State.OPEN, closed_at=None, is_draft=True),
        pr(3, state=State.OPEN, closed_at=None, created_at=now - timedelta(days=1)),
    )
    assert metrics.stale_open(df, now, 7)["title"].tolist() == ["PR 1"]


def test_monthly_flow_counts_merges_in_the_month_they_closed() -> None:
    df = frame(pr(1, closed_at=datetime(2026, 10, 2, tzinfo=UTC)), pr(2))
    flow = metrics.monthly_flow(df)
    assert flow.loc["2026-09-01", "Opened"] == 2
    assert flow.loc["2026-09-01", "Merged"] == 1
    assert flow.loc["2026-10-01", "Merged"] == 1


def test_summary_counts_merged_without_review() -> None:
    df = frame(pr(1), pr(2, approvers=["bob"]))
    assert metrics.summary(df)["merged_without_review"] == 1


def test_export_table_uses_display_names() -> None:
    out = metrics.export_table(frame(pr(1, approvers=["bob"])), {"alice": "Alice", "bob": "Bob"})
    row = out.iloc[0]
    assert (row["Platform"], row["Author"], row["Approved by"]) == ("GitHub", "Alice", "Bob")
