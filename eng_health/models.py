"""The normalised pull request record that every other module works with."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

PLATFORM_NAMES = {"azure_devops": "Azure DevOps", "github": "GitHub"}


class State(StrEnum):
    OPEN = "open"
    MERGED = "merged"
    ABANDONED = "abandoned"


@dataclass
class PullRequest:
    platform: str
    repo_id: str
    repository: str
    number: int
    title: str
    author: str
    state: State
    is_draft: bool
    created_at: datetime
    closed_at: datetime | None
    url: str
    is_infrastructure: bool
    # Lines and files changed, without lock files and generated code (the engine's
    # rules::is_noise). None where the platform doesn't report them: Azure DevOps, for now.
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None
    # GitHub exposes this and we use it to skip unchanged PRs; Azure DevOps does not.
    updated_at: datetime | None = None
    reviewers: list[str] = field(default_factory=list)
    approvers: list[str] = field(default_factory=list)
    rejecters: list[str] = field(default_factory=list)
    comment_counts: dict[str, int] = field(default_factory=dict)
    # Earliest comment, vote or review from each person other than the author.
    first_responses: dict[str, datetime] = field(default_factory=dict)
    # False when fetching comments/reviews failed, so the next sync retries this PR
    # instead of trusting empty review data.
    details_complete: bool = True

    @property
    def key(self) -> str:
        # PR numbers are only unique within a repository on GitHub, and the two
        # platforms' numbering overlaps, so all three parts are needed.
        return f"{self.platform}:{self.repo_id}:{self.number}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        for k in ("created_at", "closed_at", "updated_at"):
            d[k] = d[k].isoformat() if d[k] else None
        d["first_responses"] = {p: t.isoformat() for p, t in self.first_responses.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PullRequest:
        d = dict(d)
        d["state"] = State(d["state"])
        for k in ("created_at", "closed_at", "updated_at"):
            d[k] = datetime.fromisoformat(d[k]) if d.get(k) else None
        d["first_responses"] = {
            p: datetime.fromisoformat(t) for p, t in d.get("first_responses", {}).items()
        }
        return cls(**d)
