"""Builders for raw API payloads and fake HTTP responses."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import requests

from pr_analytics.clients import ApiError, AuthError
from pr_analytics.models import PullRequest, Repo
from pr_analytics.processing import from_github, parse_time

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def az_user(name: str) -> dict[str, str]:
    return {"displayName": name.title(), "uniqueName": f"{name}@example.com"}


def az_comment(name: str, at: datetime, kind: str = "text", **extra: Any) -> dict[str, Any]:
    return {"commentType": kind, "author": az_user(name), "publishedDate": iso(at), **extra}


def az_vote_thread(name: str, vote: int, at: datetime) -> dict[str, Any]:
    return {
        "publishedDate": iso(at),
        "properties": {
            "CodeReviewThreadType": {"$value": "VoteUpdate"},
            "CodeReviewVoteResult": {"$value": str(vote)},
            "CodeReviewVotedByIdentity": {"$value": "7"},
        },
        "identities": {"7": az_user(name)},
        "comments": [az_comment(name, at, kind="system")],
    }


def az_pr(number: int = 1, **overrides: Any) -> dict[str, Any]:
    pr = {
        "pullRequestId": number,
        "title": "Add search",
        "status": "completed",
        "createdBy": az_user("alice"),
        "creationDate": "2026-09-01T09:00:00Z",
        "closedDate": "2026-09-02T09:00:00Z",
        "reviewers": [],
        "threads": [],
    }
    pr.update(overrides)
    return pr


def gh_pr(number: int = 1, **overrides: Any) -> dict[str, Any]:
    pr = {
        "number": number,
        "title": "Add search",
        "state": "closed",
        "user": {"login": "alice"},
        "created_at": "2026-09-01T09:00:00Z",
        "updated_at": "2026-09-02T09:00:00Z",
        "closed_at": "2026-09-02T09:00:00Z",
        "merged_at": "2026-09-02T09:00:00Z",
        "html_url": f"https://github.com/o/r/pull/{number}",
        "requested_reviewers": [],
        "reviews": [],
        "review_comments": [],
        "issue_comments": [],
    }
    pr.update(overrides)
    return pr


AZ_REPO = Repo("azure_devops", "repo-1", "api", {"webUrl": "https://dev.azure.com/o/p/_git/api"})
GH_REPO = Repo("github", "101", "web")


def response(
    body: Any = None, status: int = 200, headers: dict[str, str] | None = None, url: str = ""
) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body if body is not None else {}).encode()
    r.headers.update(headers or {})
    r.url = url
    return r


class FakeSession(requests.Session):
    """Records GET calls and answers them from a handler function."""

    def __init__(self, handler: Any) -> None:
        super().__init__()
        self.handler = handler
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: Any = None, **kwargs: Any) -> requests.Response:  # type: ignore[override]
        self.calls.append((url, dict(params or {})))
        return self.handler(url, dict(params or {}))


WEB = Repo("github", "1", "web")
API = Repo("github", "2", "api")


class FakeClient:
    """Serves GitHub-shaped PRs from memory; details are the review/comment fields."""

    platform = "github"

    def __init__(self) -> None:
        self.prs: dict[str, list[dict[str, Any]]] = {"web": [], "api": []}
        self.since_seen: list[datetime | None] = []
        self.fetched: list[tuple[str, int]] = []
        self.failing_details: set[int] = set()
        self.failing_repos: set[str] = set()
        self.auth_broken = False

    def add(self, repo: str, number: int, **fields: Any) -> None:
        self.prs[repo].append(gh_pr(number, **fields))

    def list_repositories(self) -> list[Repo]:
        if self.auth_broken:
            raise AuthError("github: credentials rejected (401)")
        return [WEB, API]

    def list_pull_requests(self, repo: Repo, since: datetime | None) -> list[dict[str, Any]]:
        self.since_seen.append(since)
        if repo.name in self.failing_repos:
            raise ApiError("github: 502")
        # The list endpoint does not include reviews or comments.
        return [
            {
                k: v
                for k, v in pr.items()
                if k not in ("reviews", "review_comments", "issue_comments")
            }
            for pr in self.prs[repo.name]
        ]

    def fetch_details(self, repo: Repo, raw: dict[str, Any]) -> None:
        self.fetched.append((repo.name, raw["number"]))
        full = next(p for p in self.prs[repo.name] if p["number"] == raw["number"])
        for field in ("reviews", "review_comments", "issue_comments"):
            raw[field] = (
                None if raw["number"] in self.failing_details else copy.deepcopy(full[field])
            )

    def is_unchanged(self, raw: dict[str, Any], cached: PullRequest) -> bool:
        return cached.details_complete and cached.updated_at == parse_time(raw.get("updated_at"))

    def to_pull_request(
        self, raw: dict[str, Any], repo: Repo, people: dict[str, str]
    ) -> PullRequest:
        return from_github(raw, repo, people)
