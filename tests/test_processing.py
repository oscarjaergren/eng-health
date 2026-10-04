from datetime import UTC, datetime, timedelta

import pytest

from pr_analytics.models import PullRequest, Repo, State
from pr_analytics.processing import from_azure, from_github, is_bot, is_infrastructure

from .helpers import AZ_REPO, GH_REPO, az_comment, az_pr, az_user, az_vote_thread, gh_pr

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Add platform settings page", False),
        ("Fix login alarm threshold", False),
        ("Fix harmful null check", False),
        ("Add pharmacy lookup endpoint", False),
        ("Bump package.json versions", False),
        ("Fix deploy script typo", False),
        ("Bump Terraform AWS provider", True),
        ("Update Helm chart values", True),
        ("infra: rotate storage keys", True),
        ("Add ARM template for queue", True),
        ("k8s: raise memory limit", True),
    ],
)
def test_infrastructure_matches_whole_words_only(title: str, expected: bool) -> None:
    assert is_infrastructure(title) is expected


@pytest.mark.parametrize(
    ("ident", "expected"),
    [
        ("jane@example.com", False),
        ("talbot", False),
        ("dependabot[bot]", True),
        ("github-actions", True),
        ("build\\0f1e2d3c", True),
        ("vstfs:///classification/teamproject/x", True),
        ("", True),
    ],
)
def test_is_bot(ident: str, expected: bool) -> None:
    assert is_bot(ident) is expected


def test_azure_counts_only_human_text_comments() -> None:
    raw = az_pr(
        threads=[
            {
                "comments": [
                    az_comment("bob", T0 + timedelta(hours=2)),
                    az_comment("bob", T0 + timedelta(hours=3)),
                    az_comment("bob", T0, kind="system"),
                    az_comment("carol", T0, isDeleted=True),
                    {"commentType": "text", "author": {"uniqueName": "Build\\abc"}},
                    az_comment("alice", T0 + timedelta(hours=4)),
                ]
            }
        ]
    )
    pr = from_azure(raw, AZ_REPO, {})
    assert pr.comment_counts == {"bob@example.com": 2, "alice@example.com": 1}


def test_azure_keeps_approvals_that_were_reset_by_new_commits() -> None:
    raw = az_pr(
        reviewers=[{**az_user("bob"), "vote": 0}, {**az_user("carol"), "vote": -10}],
        threads=[az_vote_thread("bob", 10, T0 + timedelta(hours=5))],
    )
    pr = from_azure(raw, AZ_REPO, {})
    assert pr.approvers == ["bob@example.com"]
    assert pr.rejecters == ["carol@example.com"]


def test_azure_ignores_self_approval_and_group_reviewers() -> None:
    raw = az_pr(
        reviewers=[
            {**az_user("alice"), "vote": 10},
            {"uniqueName": "vstfs:///x\\Team", "isContainer": True, "vote": 10},
        ],
        threads=[az_vote_thread("alice", 10, T0)],
    )
    pr = from_azure(raw, AZ_REPO, {})
    assert pr.approvers == []
    assert pr.reviewers == []


def test_azure_first_response_is_earliest_non_author_activity() -> None:
    raw = az_pr(
        threads=[
            {"comments": [az_comment("alice", T0 + timedelta(minutes=5))]},
            {"comments": [az_comment("bob", T0 + timedelta(hours=3))]},
            az_vote_thread("bob", 10, T0 + timedelta(hours=1)),
        ]
    )
    pr = from_azure(raw, AZ_REPO, {})
    assert pr.first_responses == {"bob@example.com": T0 + timedelta(hours=1)}
    assert pr.first_review_at == T0 + timedelta(hours=1)


def test_azure_states_dates_and_people() -> None:
    people: dict[str, str] = {}
    pr = from_azure(
        az_pr(status="active", closedDate="0001-01-01T00:00:00", isDraft=True), AZ_REPO, people
    )
    assert pr.state is State.OPEN
    assert pr.closed_at is None
    assert pr.is_draft
    assert pr.url == "https://dev.azure.com/o/p/_git/api/pullrequest/1"
    assert people == {"alice@example.com": "Alice"}


def test_azure_missing_threads_marks_details_incomplete() -> None:
    assert from_azure(az_pr(threads=None), AZ_REPO, {}).details_complete is False
    assert from_azure(az_pr(), AZ_REPO, {}).details_complete is True


@pytest.mark.parametrize(
    ("fields", "state"),
    [
        ({}, State.MERGED),
        ({"merged_at": None}, State.ABANDONED),
        ({"state": "open", "merged_at": None, "closed_at": None}, State.OPEN),
    ],
)
def test_github_states(fields: dict, state: State) -> None:
    assert from_github(gh_pr(**fields), GH_REPO, {}).state is state


def test_github_reviews_and_comments() -> None:
    raw = gh_pr(
        requested_reviewers=[{"login": "dave"}],
        reviews=[
            {"user": {"login": "bob"}, "state": "APPROVED", "submitted_at": "2026-09-01T12:00:00Z"},
            {
                "user": {"login": "carol"},
                "state": "CHANGES_REQUESTED",
                "submitted_at": "2026-09-01T10:00:00Z",
            },
            {
                "user": {"login": "alice"},
                "state": "APPROVED",
                "submitted_at": "2026-09-01T09:30:00Z",
            },
            {"user": {"login": "erin"}, "state": "PENDING"},
        ],
        review_comments=[{"user": {"login": "bob"}, "created_at": "2026-09-01T11:00:00Z"}],
        issue_comments=[
            {"user": {"login": "github-actions[bot]"}, "created_at": "2026-09-01T09:01:00Z"},
            {"user": {"login": "alice"}, "created_at": "2026-09-01T13:00:00Z"},
        ],
    )
    pr = from_github(raw, GH_REPO, {})
    assert pr.approvers == ["bob"]
    assert pr.rejecters == ["carol"]
    assert pr.comment_counts == {"bob": 1, "alice": 1}
    assert pr.first_review_at == datetime(2026, 9, 1, 10, tzinfo=UTC)
    assert set(pr.reviewers) == {"dave", "bob", "carol"}


def test_github_missing_detail_marks_incomplete() -> None:
    assert from_github(gh_pr(issue_comments=None), GH_REPO, {}).details_complete is False


def test_key_distinguishes_repositories_with_the_same_pr_number() -> None:
    a = from_github(gh_pr(7), GH_REPO, {})
    b = from_github(gh_pr(7), Repo("github", "202", "other"), {})
    assert a.key != b.key


def test_round_trip_through_dict() -> None:
    pr = from_azure(az_pr(threads=[az_vote_thread("bob", 10, T0)]), AZ_REPO, {})
    assert PullRequest.from_dict(pr.to_dict()) == pr
