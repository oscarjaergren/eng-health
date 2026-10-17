from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from eng_health import metrics
from eng_health.models import PullRequest, State, Team
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


def test_review_timings_start_when_a_draft_was_marked_ready() -> None:
    ready = {"ready_at": T0 + timedelta(hours=5)}  # a draft for its first five hours
    df = frame(
        pr(1, **ready, first_responses={"bob": T0 + timedelta(hours=6)}),
        pr(2, **ready, first_responses={"bob": T0 + timedelta(hours=1)}),  # on the draft
    )
    assert df["first_review_hours"].tolist() == [1, 0]
    assert df["cycle_hours"].tolist() == [5, 5]  # merged at 10 hours, ready at 5


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


def repo_row(
    repo_id: str, name: str, owner: str, archived: int = 0, fork: int = 0
) -> dict[str, object]:
    return {
        "platform": "azure_devops",
        "repo_id": repo_id,
        "name": name,
        "owner": owner,
        "is_archived": archived,
        "is_fork": fork,
    }


def test_same_named_repositories_stay_apart() -> None:
    azure = {"platform": "azure_devops"}
    df = frame(
        pr(1, **azure, repo_id="a", repository="web"),
        pr(2, **azure, repo_id="b", repository="web"),
        pr(3, **azure, repo_id="c", repository="api"),
    )
    repos = pd.DataFrame([repo_row("a", "web", "Payments"), repo_row("b", "web", "Identity")])
    named = metrics.name_repositories(df, repos)
    assert named["repository"].tolist() == ["Payments/web", "Identity/web", "api"]
    chosen = metrics.Filters(repositories=("azure_devops:a",))
    assert metrics.apply_filters(named, chosen)["number"].tolist() == [1]


def test_archived_repositories_and_forks_count_only_when_chosen() -> None:
    df = frame(pr(1, repo_id="live"), pr(2, repo_id="old"), pr(3, repo_id="copy"))
    hidden = ("github:old", "github:copy")
    assert metrics.apply_filters(df, metrics.Filters(hidden=hidden))["number"].tolist() == [1]
    chosen = metrics.Filters(repositories=("github:old",), hidden=hidden)
    assert metrics.apply_filters(df, chosen)["number"].tolist() == [2]


def test_repository_options_put_the_busy_ones_first_and_hidden_ones_last() -> None:
    now = pd.Timestamp(T0) + pd.Timedelta(days=10)
    recent = {"created_at": T0 + timedelta(days=9), "closed_at": None, "state": State.OPEN}
    df = frame(
        pr(1, repo_id="a", repository="quiet"),  # before the period
        pr(2, repo_id="b", repository="busy", **recent),
        pr(3, repo_id="b", repository="busy", **recent),
        pr(4, repo_id="c", repository="some", **recent),
        pr(5, repo_id="d", repository="old", **recent),
    )
    repos = pd.DataFrame(
        [repo_row("d", "old", "o", archived=1), repo_row("e", "empty", "o", fork=1)]
    )
    repos["platform"] = "github"
    options = metrics.repo_options(df, repos, now - pd.Timedelta(days=7), now)
    assert options["name"].tolist() == ["busy", "some", "quiet", "old", "empty"]
    assert options["prs"].tolist() == [2, 1, 0, 1, 0]
    assert options["status"].tolist() == ["", "", "", "archived", "fork"]


def test_mine_is_where_i_opened_reviewed_or_still_have_a_pr_open() -> None:
    now = T0 + timedelta(days=200)
    recent, old = now - timedelta(days=10), now - timedelta(days=150)
    df = frame(
        pr(1, repo_id="authored", author="me", created_at=recent, closed_at=recent),
        pr(2, repo_id="reviewed", author="bob", first_responses={"me": recent}),
        pr(3, repo_id="still-open", author="me", created_at=old, closed_at=None, state=State.OPEN),
        pr(4, repo_id="long-ago", author="me", created_at=old, closed_at=old),
        pr(5, repo_id="not-mine", author="bob", first_responses={"carol": recent}),
    )
    assert metrics.mine(df, {"me"}, now) == {
        "github:authored",
        "github:reviewed",
        "github:still-open",
    }


def test_scopes_put_mine_and_all_first_and_mark_my_teams() -> None:
    now = T0 + timedelta(days=10)
    df = frame(
        pr(1, repo_id="web", author="me", created_at=T0 + timedelta(days=9)),
        pr(2, repo_id="api", author="ann", created_at=T0 + timedelta(days=9)),
    )
    teams = [
        Team("github:zed", "Zed", frozenset({"me"}), frozenset({"github:web"})),
        Team("azure_devops:ops", "Ops", frozenset({"ann"}), frozenset()),  # goes by where ann works
        Team("azure_devops:zed", "Zed", frozenset({"ann"}), frozenset()),
        Team("github:idle", "Idle", frozenset({"nobody"}), frozenset()),
    ]
    found = metrics.scopes(df, {"me"}, teams, now)
    assert list(found) == [
        "mine", "all", "team:github:zed", "team:azure_devops:ops", "team:azure_devops:zed",
    ]  # fmt: skip
    assert found["team:github:zed"][0] == "Zed · your team"
    assert found["team:azure_devops:ops"] == ("Ops", {"github:api"})
    assert found["team:azure_devops:zed"][0] == "Zed (Azure DevOps)"
    assert found["all"] == ("All repositories", None)
    assert list(metrics.scopes(df, set(), [], now)) == ["all"]


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


def test_idle_counts_from_the_latest_sign_of_life() -> None:
    now = T0 + timedelta(days=40)
    opened = {"state": State.OPEN, "closed_at": None}
    df = frame(
        pr(1, **opened),  # nothing since it opened
        pr(2, **opened, updated_at=now - timedelta(days=3)),  # GitHub says when it changed
        # Azure DevOps doesn't: its newest first response is the latest sign there is.
        pr(3, **opened, platform="azure_devops", first_responses={"bob": now - timedelta(days=5)}),
    )
    idle = metrics.waiting(df, now).set_index("title")["idle"].to_dict()
    assert idle == {"PR 1": 40, "PR 2": 3, "PR 3": 5}


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
