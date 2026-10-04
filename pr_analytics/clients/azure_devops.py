"""Azure DevOps REST client."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from ..config import AzureDevOpsSettings
from ..models import PullRequest, Repo, State
from ..processing import from_azure
from .base import ApiError, AuthError, BaseClient

API_VERSION = "7.1"
PAGE_SIZE = 100

_STATES = {"active": State.OPEN, "completed": State.MERGED, "abandoned": State.ABANDONED}


class AzureDevOpsClient(BaseClient):
    platform = "azure_devops"

    def __init__(self, settings: AzureDevOpsSettings, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base = f"https://dev.azure.com/{quote(settings.organization)}"
        self.session.auth = ("", settings.token)

    def list_repositories(self) -> list[Repo]:
        data = self._get(f"{self.base}/_apis/git/repositories", {"api-version": API_VERSION})
        return [
            Repo(self.platform, r["id"], r["name"], r)
            for r in data.json().get("value", [])
            if not r.get("isDisabled")
        ]

    def list_pull_requests(self, repo: Repo, since: datetime | None) -> list[dict[str, Any]]:
        if since is None:
            return self._paged(repo, {"searchCriteria.status": "all"})

        # minTime filters on creation date unless told otherwise, which would miss
        # older PRs that closed since the last sync. So: every open PR, plus
        # anything closed since then.
        prs = {
            p["pullRequestId"]: p for p in self._paged(repo, {"searchCriteria.status": "active"})
        }
        closed = self._paged(
            repo,
            {
                "searchCriteria.status": "all",
                "searchCriteria.queryTimeRangeType": "closed",
                "searchCriteria.minTime": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        prs.update({p["pullRequestId"]: p for p in closed})
        return list(prs.values())

    def _paged(self, repo: Repo, criteria: dict[str, str]) -> list[dict[str, Any]]:
        url = f"{self._repo_url(repo)}/pullrequests"
        out: list[dict[str, Any]] = []
        while True:
            params = {**criteria, "$top": PAGE_SIZE, "$skip": len(out), "api-version": API_VERSION}
            page = self._get(url, params).json().get("value", [])
            out.extend(page)
            if len(page) < PAGE_SIZE:
                return out

    def fetch_details(self, repo: Repo, raw: dict[str, Any]) -> None:
        url = f"{self._repo_url(repo)}/pullRequests/{raw['pullRequestId']}/threads"
        try:
            raw["threads"] = self._get(url, {"api-version": API_VERSION}).json().get("value", [])
        except AuthError:
            raise
        except ApiError:
            raw["threads"] = None

    def is_unchanged(self, raw: dict[str, Any], cached: PullRequest) -> bool:
        # No "last updated" field exists, so only closed PRs that stayed closed
        # are safe to skip. Open PRs are re-read on every sync.
        return (
            cached.details_complete
            and cached.state != State.OPEN
            and _STATES.get(raw.get("status", "")) == cached.state
        )

    def to_pull_request(
        self, raw: dict[str, Any], repo: Repo, people: dict[str, str]
    ) -> PullRequest:
        return from_azure(raw, repo, people)

    def _repo_url(self, repo: Repo) -> str:
        project = (repo.raw.get("project") or {}).get("id", "")
        return f"{self.base}/{project}/_apis/git/repositories/{repo.id}"
