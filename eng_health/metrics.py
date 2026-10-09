"""Pure functions from pull requests to the tables the dashboard draws.

Kept free of Streamlit so they can be unit tested.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from .models import PLATFORM_NAMES, PullRequest, State

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


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
        rows.append(
            {
                "key": pr.key,
                "platform": pr.platform,
                "repository": pr.repository,
                "number": pr.number,
                "title": pr.title,
                "author": one(pr.author),
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
    return df


# Common review-size thresholds: past a few hundred lines, reviews get shallower and slower.
SIZE_EDGES = [-1, 10, 100, 400, 1000, float("inf")]
SIZE_LABELS = ["XS (≤10)", "S (≤100)", "M (≤400)", "L (≤1000)", "XL (>1000)"]


_COLUMNS = [
    "key", "platform", "repository", "number", "title", "author", "state", "is_draft",
    "is_infrastructure", "additions", "deletions", "changed_files", "details_complete",
    "created_at", "closed_at", "first_review_at",
    "url", "reviewers", "approvers", "rejecters", "comment_counts", "first_responses",
]  # fmt: skip


@dataclass(frozen=True)
class Filters:
    platforms: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None
    include_infrastructure: bool = False
    include_drafts: bool = True
    tz: str = "UTC"


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for col, wanted in (
        ("platform", f.platforms),
        ("repository", f.repositories),
        ("author", f.authors),
        ("state", f.states),
    ):
        if wanted:
            mask &= df[col].isin(wanted)
    local_day = df["created_at"].dt.tz_convert(f.tz).dt.date
    if f.start:
        mask &= local_day >= f.start
    if f.end:
        mask &= local_day <= f.end
    if not f.include_infrastructure:
        mask &= ~df["is_infrastructure"]
    if not f.include_drafts:
        mask &= ~df["is_draft"]
    return df[mask]


def _median(s: pd.Series) -> float:
    return float(s.median()) if s.notna().any() else float("nan")


def summary(df: pd.DataFrame) -> dict[str, float]:
    merged = df[df["state"] == State.MERGED.value]
    reviewed = merged["approvers"].map(len).gt(0) | merged["first_review_at"].notna()
    return {
        "prs": len(df),
        "merged": len(merged),
        "open": int((df["state"] == State.OPEN.value).sum()),
        "median_cycle_hours": _median(merged["cycle_hours"]),
        "median_first_review_hours": _median(df["first_review_hours"]),
        "merged_without_review": int((~reviewed).sum()),
    }


def repo_summary(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("repository")
    out = pd.DataFrame(
        {
            "PRs": g.size(),
            "Merged": g["state"].apply(lambda s: int((s == State.MERGED.value).sum())),
            "Open": g["state"].apply(lambda s: int((s == State.OPEN.value).sum())),
            "Median cycle (h)": g["cycle_hours"].median(),
            "Median first review (h)": g["first_review_hours"].median(),
        }
    )
    return out.sort_values("PRs", ascending=False)


def monthly_flow(df: pd.DataFrame, tz: str = "UTC") -> pd.DataFrame:
    def month(col: str) -> pd.Series:
        period: pd.Series = df[col].dt.tz_convert(tz).dt.tz_localize(None).dt.to_period("M")
        return period

    opened = df.groupby(month("created_at")).size().rename("Opened")
    merged = df[df["state"] == State.MERGED.value]
    by_close = merged.groupby(month("closed_at").loc[merged.index])
    out = pd.concat(
        [
            opened,
            by_close.size().rename("Merged"),
            by_close["cycle_hours"].median().rename("Median cycle (h)"),
            by_close["cycle_hours"].quantile(0.75).rename("75th pct cycle (h)"),
            df.groupby(month("created_at"))["first_review_hours"]
            .median()
            .rename("Median first review (h)"),
        ],
        axis=1,
    ).sort_index()
    out[["Opened", "Merged"]] = out[["Opened", "Merged"]].fillna(0).astype(int)
    out.index = pd.PeriodIndex(out.index).to_timestamp()
    out.index.name = "month"
    return out


def stale_open(df: pd.DataFrame, now: datetime, older_than_days: int = 7) -> pd.DataFrame:
    open_ = df[(df["state"] == State.OPEN.value) & ~df["is_draft"]].copy()
    open_["Age (days)"] = (pd.Timestamp(now) - open_["created_at"]).dt.days
    open_["Approvals"] = open_["approvers"].map(len)
    open_["Reviewed"] = open_["first_review_at"].notna()
    stale = open_[open_["Age (days)"] >= older_than_days]
    return stale.sort_values("Age (days)", ascending=False)[
        ["title", "repository", "author", "Age (days)", "Reviewed", "Approvals", "url"]
    ]


def comment_rows(df: pd.DataFrame, exclude_own: bool = True) -> pd.DataFrame:
    """One row per (commenter, PR) with the number of comments."""
    rows = [
        (person, author, repo, key, title, n)
        for counts, author, repo, key, title in zip(
            df["comment_counts"],
            df["author"],
            df["repository"],
            df["key"],
            df["title"],
            strict=True,
        )
        for person, n in counts.items()
        if not (exclude_own and person == author)
    ]
    return pd.DataFrame(
        rows, columns=["person", "author", "repository", "key", "title", "comments"]
    )


def reviewer_activity(df: pd.DataFrame, exclude_own_comments: bool = True) -> pd.DataFrame:
    """Per person: what they authored and how they took part in others' reviews."""
    approvals = df["approvers"].explode().dropna().value_counts()
    rejections = df["rejecters"].explode().dropna().value_counts()
    comments = comment_rows(df, exclude_own_comments).groupby("person")["comments"].sum()

    responses = [
        (person, (t - created).total_seconds() / 3600)
        for created, firsts in zip(df["created_at"], df["first_responses"], strict=True)
        for person, t in firsts.items()
    ]
    resp = pd.DataFrame(responses, columns=["person", "hours"])
    reviewed = resp.groupby("person").size()
    response_h = resp.groupby("person")["hours"].median()

    authored = df["author"].value_counts()
    out = pd.DataFrame(
        {
            "PRs authored": authored,
            "PRs reviewed": reviewed,
            "Approvals": approvals,
            "Change requests": rejections,
            "Comments": comments,
            "Median response (h)": response_h,
        }
    )
    counts = ["PRs authored", "PRs reviewed", "Approvals", "Change requests", "Comments"]
    out[counts] = out[counts].fillna(0).astype(int)
    out.index.name = "person"
    return out.sort_values(["PRs reviewed", "Comments"], ascending=False)


def non_reviewers(activity: pd.DataFrame) -> pd.DataFrame:
    """People who author PRs but have not reviewed anyone else's."""
    mask = (activity["PRs authored"] > 0) & (activity["PRs reviewed"] == 0)
    return activity.loc[mask, ["PRs authored"]].sort_values("PRs authored", ascending=False)


def weekday_hour(df: pd.DataFrame, tz: str = "UTC") -> pd.DataFrame:
    local = df["created_at"].dt.tz_convert(tz)
    grid = pd.crosstab(local.dt.day_name(), local.dt.hour)
    return grid.reindex(index=WEEKDAYS, columns=range(24), fill_value=0)


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
    others = comment_rows(sized).groupby("key")["comments"].sum()
    sized = sized.assign(comments=sized["key"].map(others).fillna(0))
    g = sized.groupby("size", observed=False)
    out = pd.DataFrame(
        {
            "PRs": g.size(),
            "Median first review (h)": g["first_review_hours"].median(),
            "Median to merge (h)": g["cycle_hours"].median(),
            # Comments from people other than the author, per 100 changed lines.
            "Comments per 100 lines": 100 * g["comments"].sum() / g["lines"].sum(),
        }
    )
    return out[out["PRs"] > 0]


def size_trend(df: pd.DataFrame, tz: str = "UTC") -> pd.DataFrame:
    """Median lines changed per PR, by the month PRs were opened (weeks are too few PRs)."""
    sized = df[df["lines"].notna()]
    month = sized["created_at"].dt.tz_convert(tz).dt.tz_localize(None).dt.to_period("M")
    out = sized.groupby(month.dt.start_time)["lines"].agg(["median", "size"])
    return out.rename(columns={"median": "Median lines", "size": "PRs"}).rename_axis("month")


def author_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Per author: lines written in the selection's PRs, and how big their PRs usually are."""
    sized = df[df["lines"].notna()]
    g = sized.groupby("author")
    out = pd.DataFrame(
        {
            "PRs": g.size(),
            "Lines added": g["additions"].sum(),
            "Lines deleted": g["deletions"].sum(),
            "Median PR (lines)": g["lines"].median(),
            "Largest PR (lines)": g["lines"].max(),
        }
    ).rename_axis("person")
    return out.sort_values("Lines added", ascending=False)
