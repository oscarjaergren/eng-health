from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pytest

from pr_analytics.clients import AuthError, AzureDevOpsClient, GitHubClient
from pr_analytics.config import AzureDevOpsSettings, GitHubSettings
from pr_analytics.models import Repo

from .helpers import FakeSession, response

AZ_REPO = Repo("azure_devops", "r1", "api", {"project": {"id": "p1"}})
GH_REPO = Repo("github", "101", "web")
SINCE = datetime(2026, 9, 1, tzinfo=UTC)


def azure(handler: Any) -> tuple[AzureDevOpsClient, FakeSession]:
    session = FakeSession(handler)
    return AzureDevOpsClient(AzureDevOpsSettings("org", "pat"), session=session), session


def github(handler: Any) -> tuple[GitHubClient, FakeSession]:
    session = FakeSession(handler)
    return GitHubClient(GitHubSettings("acme", "tok"), session=session), session


def test_azure_full_listing_pages_until_a_short_page() -> None:
    def handler(url: str, params: dict) -> Any:
        skip = params["$skip"]
        count = 100 if skip < 200 else 5
        return response({"value": [{"pullRequestId": skip + i} for i in range(count)]})

    client, session = azure(handler)
    prs = client.list_pull_requests(AZ_REPO, None)
    assert len(prs) == 205
    assert [p["$skip"] for _, p in session.calls] == [0, 100, 200]
    assert all(p["searchCriteria.status"] == "all" for _, p in session.calls)
    assert (
        session.calls[0][0] == "https://dev.azure.com/org/p1/_apis/git/repositories/r1/pullrequests"
    )


def test_azure_incremental_reads_open_prs_and_prs_closed_since() -> None:
    def handler(url: str, params: dict) -> Any:
        if params["searchCriteria.status"] == "active":
            return response({"value": [{"pullRequestId": 1}, {"pullRequestId": 2}]})
        return response({"value": [{"pullRequestId": 2}, {"pullRequestId": 3}]})

    client, session = azure(handler)
    prs = client.list_pull_requests(AZ_REPO, SINCE)
    assert sorted(p["pullRequestId"] for p in prs) == [1, 2, 3]
    closed = session.calls[1][1]
    assert closed["searchCriteria.queryTimeRangeType"] == "closed"
    assert closed["searchCriteria.minTime"] == "2026-09-01T00:00:00Z"


def test_azure_detail_failure_leaves_threads_unset() -> None:
    client, _ = azure(lambda url, params: response(status=500))
    raw = {"pullRequestId": 1}
    client.fetch_details(AZ_REPO, raw)
    assert raw["threads"] is None


@pytest.mark.parametrize("status", [401, 203])
def test_azure_rejected_credentials_raise(status: int) -> None:
    client, _ = azure(lambda url, params: response(status=status))
    with pytest.raises(AuthError):
        client.fetch_details(AZ_REPO, {"pullRequestId": 1})


def test_github_listing_follows_links_and_stops_at_older_prs() -> None:
    pages = {
        1: [{"number": 3, "updated_at": "2026-09-05T00:00:00Z"}],
        2: [
            {"number": 2, "updated_at": "2026-09-02T00:00:00Z"},
            {"number": 1, "updated_at": "2026-08-01T00:00:00Z"},
        ],
        3: [{"number": 0, "updated_at": "2026-07-01T00:00:00Z"}],
    }

    def handler(url: str, params: dict) -> Any:
        page = int(url.rsplit("page=", 1)[1]) if "page=" in url else 1
        link = f'<https://api.github.com/x?page={page + 1}>; rel="next"'
        return response(pages[page], headers={"Link": link} if page < 3 else {})

    client, session = github(handler)
    prs = client.list_pull_requests(GH_REPO, SINCE)
    assert [p["number"] for p in prs] == [3, 2]
    assert len(session.calls) == 2  # never asked for page 3


def test_github_partial_detail_failure() -> None:
    def handler(url: str, params: dict) -> Any:
        return response(status=500) if "/issues/" in url else response([])

    client, _ = github(handler)
    raw: dict[str, Any] = {"number": 9}
    client.fetch_details(GH_REPO, raw)
    assert raw["reviews"] == [] and raw["review_comments"] == [] and raw["issue_comments"] is None


def test_github_waits_for_rate_limit_reset(no_sleep: list[float]) -> None:
    replies = [
        response(
            status=403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 30)},
        ),
        response([]),
    ]
    client, _ = github(lambda url, params: replies.pop(0))
    assert client.list_repositories() == []
    assert len(no_sleep) == 1 and 0 < no_sleep[0] <= 31


def test_github_bad_token_raises() -> None:
    client, _ = github(lambda url, params: response({"message": "Bad credentials"}, status=401))
    with pytest.raises(AuthError):
        client.list_repositories()
