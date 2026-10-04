"""Turn raw Azure DevOps and GitHub API payloads into `PullRequest` records.

Each function also fills a `people` map of identity -> display name, so the
dashboard can show names while every calculation keys on a stable identity.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .models import PullRequest, Repo, State

# Matched as whole words against the title only. Substring matching against
# descriptions and repo names used to drop ordinary PRs ("platform" contains
# "tf", "alarm" contains "arm").
INFRA_PATTERN = re.compile(
    r"\b(terraform|tf|tfvars|bicep|helm|kubernetes|k8s|ansible|pulumi|"
    r"cloudformation|arm templates?|iac|infra|infrastructure)\b",
    re.IGNORECASE,
)

KNOWN_BOTS = {"github-actions", "dependabot", "renovate", "copilot"}

People = dict[str, str]


def is_infrastructure(title: str) -> bool:
    return bool(INFRA_PATTERN.search(title or ""))


def identity(value: str | None) -> str:
    return (value or "").strip().lower()


def is_bot(ident: str, *, is_group: bool = False) -> bool:
    return (
        is_group
        or not ident
        or ident.startswith("vstfs:")
        or ident.endswith("[bot]")
        # Azure DevOps groups and build services look like "domain\name" with no email.
        or ("\\" in ident and "@" not in ident)
        or ident in KNOWN_BOTS
    )


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    t = datetime.fromisoformat(value)
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    # Azure DevOps uses 0001-01-01 as "not set".
    return None if t.year < 1970 else t.astimezone(UTC)


def _note_response(responses: dict[str, datetime], who: str, when: datetime | None) -> None:
    if when and (who not in responses or when < responses[who]):
        responses[who] = when


# --- Azure DevOps ----------------------------------------------------------

_AZURE_STATES = {"active": State.OPEN, "completed": State.MERGED, "abandoned": State.ABANDONED}


def _azure_identity(ref: dict[str, Any] | None, people: People) -> str:
    ref = ref or {}
    ident = identity(ref.get("uniqueName"))
    if ident and ref.get("displayName"):
        people.setdefault(ident, ref["displayName"])
    return ident


def from_azure(raw: dict[str, Any], repo: Repo, people: People) -> PullRequest:
    author = _azure_identity(raw.get("createdBy"), people)
    threads: list[dict[str, Any]] | None = raw.get("threads")

    approvers: set[str] = set()
    rejecters: set[str] = set()
    reviewers: list[str] = []
    for r in raw.get("reviewers", []):
        who = _azure_identity(r, people)
        if is_bot(who, is_group=bool(r.get("isContainer"))) or who == author:
            continue
        reviewers.append(who)
        vote = r.get("vote", 0)
        if vote >= 5:
            approvers.add(who)
        elif vote == -10:
            rejecters.add(who)

    comment_counts: dict[str, int] = {}
    responses: dict[str, datetime] = {}
    for thread in threads or []:
        props = thread.get("properties") or {}
        if (props.get("CodeReviewThreadType") or {}).get("$value") == "VoteUpdate":
            # Current reviewer votes reset when new commits are pushed; the vote
            # history in these system threads keeps approvals that were reset.
            voter = _vote_thread_voter(thread, people)
            if voter and voter != author and not is_bot(voter):
                vote = int((props.get("CodeReviewVoteResult") or {}).get("$value") or 0)
                if vote >= 5:
                    approvers.add(voter)
                elif vote == -10:
                    rejecters.add(voter)
                _note_response(responses, voter, parse_time(thread.get("publishedDate")))
            continue

        for c in thread.get("comments", []):
            # System comments ("X updated the PR", "X voted") are not review comments.
            if c.get("commentType") != "text" or c.get("isDeleted"):
                continue
            who = _azure_identity(c.get("author"), people)
            if is_bot(who):
                continue
            comment_counts[who] = comment_counts.get(who, 0) + 1
            if who != author:
                _note_response(responses, who, parse_time(c.get("publishedDate")))

    web_url = repo.raw.get("webUrl", "")
    number = int(raw["pullRequestId"])
    return PullRequest(
        platform="azure_devops",
        repo_id=repo.id,
        repository=repo.name,
        number=number,
        title=raw.get("title") or "",
        author=author,
        state=_AZURE_STATES.get(raw.get("status", ""), State.OPEN),
        is_draft=bool(raw.get("isDraft")),
        created_at=parse_time(raw.get("creationDate")) or datetime.now(UTC),
        closed_at=parse_time(raw.get("closedDate")),
        url=f"{web_url}/pullrequest/{number}" if web_url else "",
        is_infrastructure=is_infrastructure(raw.get("title", "")),
        reviewers=reviewers,
        approvers=sorted(approvers),
        rejecters=sorted(rejecters),
        comment_counts=comment_counts,
        first_responses=responses,
        details_complete=threads is not None,
    )


def _vote_thread_voter(thread: dict[str, Any], people: People) -> str:
    ref_id = ((thread.get("properties") or {}).get("CodeReviewVotedByIdentity") or {}).get("$value")
    ident = (thread.get("identities") or {}).get(str(ref_id))
    if ident:
        return _azure_identity(ident, people)
    comments = thread.get("comments") or [{}]
    return _azure_identity(comments[0].get("author"), people)


# --- GitHub ----------------------------------------------------------------


def _gh_login(user: dict[str, Any] | None, people: People) -> str:
    login = (user or {}).get("login") or ""
    ident = identity(login)
    if ident:
        people.setdefault(ident, login)
    return ident


def from_github(raw: dict[str, Any], repo: Repo, people: People) -> PullRequest:
    author = _gh_login(raw.get("user"), people)
    reviews = raw.get("reviews")
    review_comments = raw.get("review_comments")
    issue_comments = raw.get("issue_comments")

    approvers: set[str] = set()
    rejecters: set[str] = set()
    responses: dict[str, datetime] = {}
    for rv in reviews or []:
        who = _gh_login(rv.get("user"), people)
        if is_bot(who) or who == author:
            continue
        state = rv.get("state", "").upper()
        if state == "APPROVED":
            approvers.add(who)
        elif state == "CHANGES_REQUESTED":
            rejecters.add(who)
        if state != "PENDING":
            _note_response(responses, who, parse_time(rv.get("submitted_at")))

    comment_counts: dict[str, int] = {}
    for c in (review_comments or []) + (issue_comments or []):
        who = _gh_login(c.get("user"), people)
        if is_bot(who):
            continue
        comment_counts[who] = comment_counts.get(who, 0) + 1
        if who != author:
            _note_response(responses, who, parse_time(c.get("created_at")))

    reviewers = [_gh_login(u, people) for u in raw.get("requested_reviewers", [])]
    reviewers += [p for p in responses if p not in reviewers]
    reviewers = [r for r in reviewers if r != author and not is_bot(r)]

    if raw.get("merged_at"):
        state = State.MERGED
    elif raw.get("state") == "closed":
        state = State.ABANDONED
    else:
        state = State.OPEN

    return PullRequest(
        platform="github",
        repo_id=repo.id,
        repository=repo.name,
        number=int(raw["number"]),
        title=raw.get("title") or "",
        author=author,
        state=state,
        is_draft=bool(raw.get("draft")),
        created_at=parse_time(raw.get("created_at")) or datetime.now(UTC),
        closed_at=parse_time(raw.get("merged_at") or raw.get("closed_at")),
        updated_at=parse_time(raw.get("updated_at")),
        url=raw.get("html_url", ""),
        is_infrastructure=is_infrastructure(raw.get("title", "")),
        reviewers=reviewers,
        approvers=sorted(approvers),
        rejecters=sorted(rejecters),
        comment_counts=comment_counts,
        first_responses=responses,
        details_complete=None not in (reviews, review_comments, issue_comments),
    )
