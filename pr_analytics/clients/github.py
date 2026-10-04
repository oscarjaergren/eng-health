"""GitHub REST client."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import requests

from ..config import GitHubSettings
from ..models import PullRequest, Repo
from ..processing import from_github, parse_time
from .base import ApiError, AuthError, BaseClient

log = logging.getLogger(__name__)

API = "https://api.github.com"
MAX_RATE_LIMIT_WAIT = 15 * 60


class GitHubClient(BaseClient):
    platform = "github"

    def __init__(self, settings: GitHubSettings, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.settings = settings
        self.session.headers.update(
            {
                "Authorization": f"Bearer {settings.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _wait_if_rate_limited(self, resp: requests.Response) -> bool:
        if resp.status_code not in (403, 429) or resp.headers.get("x-ratelimit-remaining") != "0":
            return False
        wait = int(resp.headers.get("x-ratelimit-reset", "0")) - time.time() + 1
        if wait > MAX_RATE_LIMIT_WAIT:
            raise ApiError(f"github: rate limit resets in {wait / 60:.0f} minutes; try later")
        log.warning("GitHub rate limit reached, waiting %.0fs", wait)
        time.sleep(max(wait, 1))
        return True

    def list_repositories(self) -> list[Repo]:
        kind = "orgs" if self.settings.owner_type == "org" else "users"
        url = f"{API}/{kind}/{self.settings.owner}/repos"
        return [
            Repo(self.platform, str(r["id"]), r["name"], r)
            for page in self._follow_links(url, {"type": "all", "per_page": 100})
            for r in page
        ]

    def list_pull_requests(self, repo: Repo, since: datetime | None) -> list[dict[str, Any]]:
        url = f"{API}/repos/{self.settings.owner}/{repo.name}/pulls"
        params = {"state": "all", "sort": "updated", "direction": "desc", "per_page": 100}
        out: list[dict[str, Any]] = []
        for page in self._follow_links(url, params):
            for pr in page:
                updated = parse_time(pr.get("updated_at"))
                if since and updated and updated < since:
                    return out  # sorted newest first, so nothing older is new
                out.append(pr)
        return out

    def fetch_details(self, repo: Repo, raw: dict[str, Any]) -> None:
        base = f"{API}/repos/{self.settings.owner}/{repo.name}"
        n = raw["number"]
        for field, url in (
            ("reviews", f"{base}/pulls/{n}/reviews"),
            ("review_comments", f"{base}/pulls/{n}/comments"),
            ("issue_comments", f"{base}/issues/{n}/comments"),
        ):
            try:
                raw[field] = [
                    item for page in self._follow_links(url, {"per_page": 100}) for item in page
                ]
            except AuthError:
                raise
            except ApiError:
                raw[field] = None

    def is_unchanged(self, raw: dict[str, Any], cached: PullRequest) -> bool:
        return cached.details_complete and cached.updated_at == parse_time(raw.get("updated_at"))

    def to_pull_request(
        self, raw: dict[str, Any], repo: Repo, people: dict[str, str]
    ) -> PullRequest:
        return from_github(raw, repo, people)
