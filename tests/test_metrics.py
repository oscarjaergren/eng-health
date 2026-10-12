from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from eng_health import metrics
from eng_health.models import PullRequest, State
from eng_health.period import Period

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


def test_filters_hide_bots_and_infrastructure_by_default() -> None:
    df = frame(
        pr(1),
        pr(2, author="dependabot[bot]"),
        pr(3, is_draft=True),
        pr(4, author="Renovate"),
        pr(5, is_infrastructure=True),
    )
    assert metrics.apply_filters(df, metrics.Filters())["number"].tolist() == [1, 3]
    f = metrics.Filters(include_bots=True, include_drafts=False, include_infrastructure=True)
    assert metrics.apply_filters(df, f)["number"].tolist() == [1, 2, 4, 5]


def test_people_count_what_happened_in_the_period() -> None:
    now = pd.Timestamp(T0) + pd.Timedelta(days=10)
    df = frame(
        # Bob reviewed this one inside the period; alice's replies on her own PR don't count.
        pr(1, created_at=T0 + timedelta(days=8), closed_at=T0 + timedelta(days=9),
           additions=10, deletions=5, comment_counts={"bob": 2, "alice": 3},
           first_responses={"bob": T0 + timedelta(days=8, hours=1)}),
        pr(2, author="bob", platform="azure_devops"),  # merged before the period, no size
        pr(3, author="carol", state=State.OPEN, closed_at=None),
    )  # fmt: skip
    assert df["comments"].tolist() == [2, 0, 0]
    people = metrics.people(df, Period(7, "7 days", "D", 7), now, "UTC")
    alice, bob = people.loc["alice"].to_dict(), people.loc["bob"].to_dict()
    assert (alice["Opened"], alice["Merged"], alice["Reviews"]) == (1, 1, 0)
    assert (alice["Lines added"], alice["Lines deleted"], alice["Net"]) == (10, 5, 5)
    assert (bob["Opened"], bob["Merged"], bob["Reviews"]) == (0, 0, 1)
    assert pd.isna(bob["Lines added"])  # not reported, rather than 0
    assert alice["Trend"][-3:] == [0.0, 1.0, 0.0]  # merged the day before now
    assert "carol" not in people.index  # nothing in the period


def test_aliases_merge_identities() -> None:
    df = frame(
        pr(1, comment_counts={"bob": 1, "bob@example.com": 2}),
        aliases={"bob": "bob@example.com"},
    )
    assert df["comment_counts"][0] == {"bob@example.com": 3}


def test_waiting_skips_drafts_and_new_prs_and_says_where_review_stands() -> None:
    now = T0 + timedelta(days=10)
    opened = {"state": State.OPEN, "closed_at": None}
    df = frame(
        pr(1, **opened),
        pr(2, **opened, is_draft=True),
        pr(3, **opened, created_at=now - timedelta(days=1)),
        pr(4, **opened, rejecters=["bob"]),
        pr(5, **opened, rejecters=["bob"], approvers=["carol"]),  # approved since
        pr(6, **opened, first_responses={"bob": T0 + timedelta(hours=1)}),
    )
    waiting = metrics.waiting(df, now).set_index("title")["status"].to_dict()
    assert waiting == {
        "PR 1": "No review",
        "PR 4": "Changes requested",
        "PR 5": "Approved, not merged",
        "PR 6": "Commented",
    }


def test_export_table_uses_display_names() -> None:
    out = metrics.export_table(frame(pr(1, approvers=["bob"])), {"alice": "Alice", "bob": "Bob"})
    row = out.iloc[0]
    assert (row["Platform"], row["Author"], row["Approved by"]) == ("GitHub", "Alice", "Bob")


def test_size_buckets_and_depth() -> None:
    # (additions, deletions): 10 lines is XS, 11 is S, 1000 is L, 1001 is XL.
    sizes = {1: (6, 4), 2: (11, 0), 3: (900, 100), 4: (1000, 1)}
    prs = [pr(n, additions=a, deletions=d, changed_files=1) for n, (a, d) in sizes.items()]
    prs[2].comment_counts = {"bob": 5, "alice": 9}  # alice wrote it: her replies don't count
    prs.append(pr(5, platform="azure_devops"))  # no size yet: left out of every size view
    df = frame(*prs)

    assert df["size"].tolist()[:4] == ["XS (≤10)", "S (≤100)", "L (≤1000)", "XL (>1000)"]
    assert pd.isna(df["size"].iloc[4])
    table = metrics.by_size(df)
    assert table["PRs"].tolist() == [1, 1, 1, 1]
    assert table.loc["L (≤1000)", "Comments per 100 lines"] == 0.5
