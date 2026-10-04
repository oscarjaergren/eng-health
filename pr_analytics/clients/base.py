"""HTTP plumbing shared by the platform clients."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..models import PullRequest, Repo

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


class AuthError(ApiError):
    """Credentials were rejected. Never swallowed: retrying will not help."""


class PlatformClient(Protocol):
    platform: str

    def list_repositories(self) -> list[Repo]: ...

    def list_pull_requests(self, repo: Repo, since: datetime | None) -> list[dict[str, Any]]: ...

    def fetch_details(self, repo: Repo, raw: dict[str, Any]) -> None: ...

    def is_unchanged(self, raw: dict[str, Any], cached: PullRequest) -> bool: ...

    def to_pull_request(
        self, raw: dict[str, Any], repo: Repo, people: dict[str, str]
    ) -> PullRequest: ...


class BaseClient:
    platform = ""

    def __init__(self, timeout: float = 30, session: requests.Session | None = None) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        retry = Retry(
            total=4,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
        self.session.mount("https://", adapter)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise ApiError(f"{self.platform}: request to {url} failed: {e}") from e
        if self._wait_if_rate_limited(resp):
            return self._get(url, params)
        # Azure DevOps answers a bad PAT with 203 and an HTML sign-in page.
        if resp.status_code in (401, 203) or (
            resp.status_code == 403 and self.platform == "azure_devops"
        ):
            raise AuthError(f"{self.platform}: credentials rejected ({resp.status_code})")
        if not resp.ok:
            raise ApiError(f"{self.platform}: {resp.status_code} from {url}")
        return resp

    def _wait_if_rate_limited(self, resp: requests.Response) -> bool:
        return False

    def _follow_links(self, url: str, params: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
        """Yield pages from an API that paginates with `Link: rel=next` headers."""
        next_url: str | None = url
        next_params: dict[str, Any] | None = params
        while next_url:
            resp = self._get(next_url, next_params)
            yield resp.json()
            next_url = resp.links.get("next", {}).get("url")
            next_params = None  # the next link already carries the query string
