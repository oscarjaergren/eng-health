"""Pure functions from pull requests to the tables the dashboard draws.

Kept free of Streamlit so they can be unit tested.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from .models import PLATFORM_NAMES, PullRequest, State
from .period import Period, between, sparklines

# Dependency update bots: their PRs follow no human review process, so they are left out by default.
BOTS = "dependabot|renovate"


def to_frame(prs: Iterable[PullRequest], aliases: Mapping[str, str] | None = None) -> pd.DataFrame:
    """One row per PR. `aliases` maps one identity onto another, e.g. a login onto an email."""
    a = aliases or {}

    def one(p: str) -> str:
        return a.get(p, p)

    rows = []
    for pr in prs:
        responses = {one(p): t for p, t in pr.first_responses.items()}
        counts: dict[str, int] = {}
        for p, n in pr.comment_counts.items():
            counts[one(p)] = counts.get(one(p), 0) + n
        author = one(pr.author)
        rows.append(
            {
                "key": pr.key,
                "platform": pr.platform,
                "repo_id": pr.repo_id,
                "repository": pr.repository,
                "number": pr.number,
                "title": pr.title,
                "author": author,
                "state": pr.state.value,
                "is_draft": pr.is_draft,
                "is_infrastructure": pr.is_infrastructure,
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files": pr.changed_files,
                "details_complete": pr.details_complete,
                "created_at": pr.created_at,
                "closed_at": pr.closed_at,
                "first_review_at": min(responses.values(), default=None),
                "url": pr.url,
                "reviewers": sorted({one(p) for p in pr.reviewers}),
                "approvers": sorted({one(p) for p in pr.approvers}),
                "rejecters": sorted({one(p) for p in pr.rejecters}),
                "comment_counts": counts,
                # Authors replying on their own PR is not review.
                "comments": sum(n for p, n in counts.items() if p != author),
                "first_responses": responses,
            }
        )
    df = pd.DataFrame(rows, columns=_COLUMNS)
    for col in ("created_at", "closed_at", "first_review_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    merged = df["state"] == State.MERGED.value
    df["cycle_hours"] = ((df["closed_at"] - df["created_at"]).dt.total_seconds() / 3600).where(
        merged
    )
    df["first_review_hours"] = (df["first_review_at"] - df["created_at"]).dt.total_seconds() / 3600
    for col in ("additions", "deletions", "changed_files"):
        df[col] = pd.to_numeric(df[col]).astype("Float64")
    df["lines"] = df["additions"] + df["deletions"]
    df["size"] = pd.cut(df["lines"], SIZE_EDGES, labels=SIZE_LABELS)
    df["is_bot"] = df["author"].str.contains(BOTS, case=False)
    # Repository names repeat across Azure DevOps projects and platforms; ids don't.
    df["repo"] = df["platform"] + ":" + df["repo_id"]
    return df


def name_repositories(df: pd.DataFrame, repos: pd.DataFrame) -> pd.DataFrame:
    """`df` with each repository named so no two share a name: "owner/name" where a name is
    used by more than one, the owner being the GitHub owner or Azure DevOps project. `repos` is
    the store's repositories table; repositories missing from it use their platform instead."""
    owners = dict(zip(repos["platform"] + ":" + repos["repo_id"], repos["owner"], strict=True))
    pairs = df[["repo", "repository", "platform"]].drop_duplicates("repo")
    shared = pairs["repository"].duplicated(keep=False)
    names = {
        key: f"{owners.get(key) or PLATFORM_NAMES.get(platform, platform)}/{name}"
        if twice
        else name
        for key, name, platform, twice in zip(
            pairs["repo"], pairs["repository"], pairs["platform"], shared, strict=True
        )
    }
    return df.assign(repository=df["repo"].map(names))


# Common review-size thresholds: past a few hundred lines, reviews get shallower and slower.
SIZE_EDGES = [-1, 10, 100, 400, 1000, float("inf")]
SIZE_LABELS = ["XS (≤10)", "S (≤100)", "M (≤400)", "L (≤1000)", "XL (>1000)"]


_COLUMNS = [
    "key", "platform", "repo_id", "repository", "number", "title", "author", "state", "is_draft",
    "is_infrastructure", "additions", "deletions", "changed_files", "details_complete",
    "created_at", "closed_at", "first_review_at",
    "url", "reviewers", "approvers", "rejecters", "comment_counts", "comments", "first_responses",
]  # fmt: skip


@dataclass(frozen=True)
class Filters:
    platforms: tuple[str, ...] = ()
    # Repository keys, "platform:repo_id". None chosen means every one but `hidden`: archived
    # ones and forks, which only count when chosen.
    repositories: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    include_drafts: bool = True
    include_bots: bool = False
    include_infrastructure: bool = False


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for col, wanted in (
        ("platform", f.platforms),
        ("repo", f.repositories),
        ("author", f.authors),
        ("state", f.states),
    ):
        if wanted:
            mask &= df[col].isin(wanted)
    if not f.repositories:
        mask &= ~df["repo"].isin(f.hidden)
    if not f.include_drafts:
        mask &= ~df["is_draft"]
    if not f.include_bots:
        mask &= ~df["is_bot"]
    if not f.include_infrastructure:
        mask &= ~df["is_infrastructure"]
    return df[mask]


def merged_in(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df[(df["state"] == State.MERGED.value) & between(df["closed_at"], start, end)]


def opened_in(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df[between(df["created_at"], start, end)]


def activity(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, by: str) -> pd.Series:
    """PRs opened or merged in (start, end], per value of `by`, such as "repo" or "author"."""
    merged = (df["state"] == State.MERGED.value) & between(df["closed_at"], start, end)
    return df.loc[between(df["created_at"], start, end) | merged, by].value_counts()


def repo_options(
    df: pd.DataFrame, repos: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    """Every repository with PRs or in `repos` (the store's table), by key: its name, PRs in
    (start, end], and its status, "archived", "fork" or "". Most active first; archived ones and
    forks last, because they only count when chosen."""
    names = dict(zip(df["repo"], df["repository"], strict=True))
    keys = repos["platform"] + ":" + repos["repo_id"]
    status = dict(
        zip(
            keys,
            np.where(
                repos["is_archived"] == 1, "archived", np.where(repos["is_fork"] == 1, "fork", "")
            ),
            strict=True,
        )
    )
    for key, name, owner in zip(keys, repos["name"], repos["owner"], strict=True):
        if key not in names:  # no PRs yet
            names[key] = f"{owner}/{name}" if name in names.values() else name
    out = pd.DataFrame({"name": pd.Series(names, dtype="str")})
    out["prs"] = activity(df, start, end, "repo").reindex(out.index, fill_value=0).astype(int)
    out["status"] = [status.get(k, "") for k in out.index]
    out["hidden"] = out["status"] != ""
    out = out.sort_values(["hidden", "prs", "name"], ascending=[True, False, True])
    return out.drop(columns="hidden")


def review_status(df: pd.DataFrame) -> pd.Series:
    """Where each PR's review stands. An approval outranks an earlier change request."""
    approved = df["approvers"].map(len).gt(0)
    status = np.select(
        [approved, df["rejecters"].map(len).gt(0), df["first_review_at"].notna()],
        ["Approved, not merged", "Changes requested", "Commented"],
        "No review",
    )
    return pd.Series(status, index=df.index)


def waiting(df: pd.DataFrame, now: datetime, min_days: int = 2) -> pd.DataFrame:
    """Open, non-draft PRs open for `min_days` or more, oldest first."""
    open_ = df[(df["state"] == State.OPEN.value) & ~df["is_draft"]]
    open_ = open_.assign(
        status=review_status(open_), age=(pd.Timestamp(now) - open_["created_at"]).dt.days
    )
    out = open_[open_["age"] >= min_days].sort_values("age", ascending=False)
    return out[["title", "repository", "author", "status", "age", "url"]]


def reviews_given(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Per person: PRs they first responded to (comment, vote or review) in (start, end]."""
    people = [p for firsts in df["first_responses"] for p, t in firsts.items() if start < t <= end]
    return pd.Series(people, dtype="str").value_counts()


def _merges(df: pd.DataFrame, period: Period, now: pd.Timestamp, tz: str, by: str) -> pd.DataFrame:
    """PRs merged: a row per chart bucket, a column per value of `by`."""
    return period.each(now, tz, lambda a, b: merged_in(df, a, b)[by].value_counts()).fillna(0)


def repositories(df: pd.DataFrame, period: Period, now: pd.Timestamp, tz: str) -> pd.DataFrame:
    """Per repository: PRs merged and opened in the period, open now, and merges per bucket."""
    start, end = period.window(now)
    merged = merged_in(df, start, end)
    out = pd.DataFrame(
        {
            "Merged": merged["repository"].value_counts(),
            "Opened": opened_in(df, start, end)["repository"].value_counts(),
            "Open now": df.loc[df["state"] == State.OPEN.value, "repository"].value_counts(),
            "Median to merge (h)": merged.groupby("repository")["cycle_hours"].median(),
        }
    ).rename_axis("repository")
    counts = ["Merged", "Opened", "Open now"]
    out[counts] = out[counts].fillna(0).astype(int)
    out["Trend"] = sparklines(_merges(df, period, now, tz, "repository"), out.index)
    return out.sort_values(["Merged", "Opened"], ascending=False)


def people(df: pd.DataFrame, period: Period, now: pd.Timestamp, tz: str) -> pd.DataFrame:
    """Per person, in the period: PRs opened, merged and reviewed, and lines in merged PRs.
    Lines are missing for people whose PRs report no size (Azure DevOps)."""
    start, end = period.window(now)
    merged = merged_in(df, start, end)
    sized = merged[merged["lines"].notna()].groupby("author")
    out = pd.DataFrame(
        {
            "Opened": opened_in(df, start, end)["author"].value_counts(),
            "Merged": merged["author"].value_counts(),
            "Reviews": reviews_given(df, start, end),
            "Lines added": sized["additions"].sum(),
            "Lines deleted": sized["deletions"].sum(),
            "Median to merge (h)": merged.groupby("author")["cycle_hours"].median(),
        }
    ).rename_axis("person")
    counts = ["Opened", "Merged", "Reviews"]
    out[counts] = out[counts].fillna(0).astype(int)
    out["Net"] = out["Lines added"] - out["Lines deleted"]
    # NaN, not pd.NA, so a missing size shows as a blank rather than "None".
    out[["Lines added", "Lines deleted", "Net"]] = out[
        ["Lines added", "Lines deleted", "Net"]
    ].astype(float)
    out["Trend"] = sparklines(_merges(df, period, now, tz, "author"), out.index)
    return out.sort_values(["Merged", "Reviews"], ascending=False)


EXPORT_COLUMNS = {
    "platform": "Platform",
    "repository": "Repository",
    "number": "Number",
    "title": "Title",
    "author": "Author",
    "state": "State",
    "is_draft": "Draft",
    "created_at": "Created",
    "closed_at": "Closed",
    "first_review_at": "First review",
    "cycle_hours": "Hours to merge",
    "first_review_hours": "Hours to first review",
    "reviewers": "Reviewers",
    "approvers": "Approved by",
    "rejecters": "Changes requested by",
    "url": "Link",
}


def export_table(df: pd.DataFrame, people: Mapping[str, str]) -> pd.DataFrame:
    """Flat, human-readable table for display and CSV export."""

    def names(ps: list[str]) -> str:
        return ", ".join(people.get(p, p) for p in ps)

    out = df[list(EXPORT_COLUMNS)].copy()
    out["platform"] = out["platform"].map(PLATFORM_NAMES)
    out["author"] = out["author"].map(lambda p: people.get(p, p))
    for col in ("reviewers", "approvers", "rejecters"):
        out[col] = out[col].map(names)
    return out.rename(columns=EXPORT_COLUMNS).sort_values("Created", ascending=False)


def by_size(df: pd.DataFrame) -> pd.DataFrame:
    """Per size bucket: how long PRs wait for review and merge, and how closely they are read."""
    sized = df[df["lines"].notna()]
    g = sized.groupby("size", observed=False)
    out = pd.DataFrame(
        {
            "PRs": g.size(),
            "Median first review (h)": g["first_review_hours"].median(),
            "Median to merge (h)": g["cycle_hours"].median(),
            "Comments per 100 lines": 100 * g["comments"].sum() / g["lines"].sum(),
        }
    )
    return out[out["PRs"] > 0]
