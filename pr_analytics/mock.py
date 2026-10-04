"""Generated sample data for running the dashboard without credentials.

It builds raw API-shaped payloads and runs them through the real processing
code, so mock mode exercises the same path as live data.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import PullRequest, Repo
from .processing import from_azure, from_github

PEOPLE = [
    ("Alice Johnson", "alice"),
    ("Bob Smith", "bob"),
    ("Charlie Brown", "charlie"),
    ("Diana Prince", "diana"),
    ("Eve Wilson", "eve"),
    ("Frank Miller", "frank"),
    ("Grace Lee", "grace"),
    ("Henry Davis", "henry"),
    ("Ivy Chen", "ivy"),
    ("Jack Taylor", "jack"),
]
AZURE_REPOS = ["UserService", "PaymentAPI", "WebApp", "AuthService", "ReportingEngine", "Platform"]
GITHUB_REPOS = ["mobile-app", "docs-site", "data-pipeline"]
TITLES = [
    "Add user authentication feature",
    "Fix memory leak in data processing",
    "Add caching layer to search",
    "Refactor database connection handling",
    "Add unit tests for payment module",
    "Fix bug in registration flow",
    "Add rate limiting to public endpoints",
    "Update dependencies",
    "Improve error handling in importer",
    "Add platform settings page",
    "Fix alarm threshold for queue depth",
    "Optimise slow report queries",
]
# Merges each sample GitHub login with the same person's Azure DevOps identity.
ALIASES = {login: f"{login}@example.com" for _, login in PEOPLE}
INFRA_TITLES = [
    "Bump Terraform AWS provider",
    "Update Helm chart values",
    "Add Bicep module for storage",
]


def mock_pull_requests(
    seed: int = 42, count: int = 400, now: datetime | None = None
) -> tuple[list[PullRequest], dict[str, str]]:
    rng = random.Random(seed)
    now = now or datetime.now(UTC)
    people: dict[str, str] = {}
    prs: list[PullRequest] = []
    repos = [
        Repo("azure_devops", f"az-{n}", n, {"webUrl": f"https://dev.azure.com/demo/_git/{n}"})
        for n in AZURE_REPOS
    ]
    repos += [Repo("github", f"gh-{n}", n) for n in GITHUB_REPOS]
    weights = [rng.uniform(0.3, 3) for _ in repos]
    numbers = {r.id: 0 for r in repos}

    for _ in range(count):
        repo = rng.choices(repos, weights)[0]
        numbers[repo.id] += 1
        spec = _spec(rng, now, numbers[repo.id])
        if repo.platform == "azure_devops":
            prs.append(from_azure(_azure_raw(spec), repo, people))
        else:
            prs.append(from_github(_github_raw(spec, repo.name), repo, people))
    return prs, people


def _spec(rng: random.Random, now: datetime, number: int) -> dict[str, Any]:
    author = rng.choice(PEOPLE)
    # Weekday office hours, as people actually work.
    day = now - timedelta(days=rng.uniform(0, 270))
    while day.weekday() >= 5:
        day -= timedelta(days=rng.randint(1, 5))
    created = day.replace(
        hour=rng.randint(8, 17), minute=rng.randint(0, 59), second=0, microsecond=0
    )
    age = now - created
    roll = rng.random()
    state = (
        "open"
        if age < timedelta(days=4) or roll < 0.05
        else ("abandoned" if roll < 0.12 else "merged")
    )
    cycle = timedelta(hours=rng.lognormvariate(3, 1))
    closed = created + cycle if state != "open" and created + cycle < now else None
    if closed is None and state != "open":
        state = "open"

    # Jack never reviews, so the "not reviewing" view has something to show.
    others = [p for p in PEOPLE if p != author and p[1] != "jack"]
    reviewers = rng.sample(others, rng.choice([0, 1, 1, 2, 2, 2, 3]))
    events = []
    for r in reviewers:
        t = created + timedelta(hours=rng.lognormvariate(1.5, 1.2))
        if t < now:
            vote = rng.choices([10, 5, -10, 0], [70, 15, 5, 10])[0] if state != "abandoned" else 0
            events.append(
                {"who": r, "at": t, "vote": vote, "comments": rng.choice([0, 0, 1, 2, 3, 5])}
            )
    return {
        "number": number,
        "title": rng.choice(INFRA_TITLES) if rng.random() < 0.06 else rng.choice(TITLES),
        "author": author,
        "created": created,
        "closed": closed,
        "state": state,
        "draft": state == "open" and rng.random() < 0.15,
        "reviewers": reviewers,
        "events": events,
        "author_replies": rng.choice([0, 0, 1, 2]) if events else 0,
        "bot_comments": rng.random() < 0.3,
    }


def _iso(t: datetime | None) -> str | None:
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if t else None


def _azure_ref(p: tuple[str, str]) -> dict[str, str]:
    return {"displayName": p[0], "uniqueName": f"{p[1]}@example.com"}


def _azure_raw(s: dict[str, Any]) -> dict[str, Any]:
    status = {"open": "active", "merged": "completed", "abandoned": "abandoned"}[s["state"]]
    votes = {e["who"]: e["vote"] for e in s["events"]}
    threads: list[dict[str, Any]] = []
    for e in s["events"]:
        if e["vote"]:
            threads.append(
                {
                    "publishedDate": _iso(e["at"]),
                    "properties": {
                        "CodeReviewThreadType": {"$value": "VoteUpdate"},
                        "CodeReviewVoteResult": {"$value": str(e["vote"])},
                        "CodeReviewVotedByIdentity": {"$value": "1"},
                    },
                    "identities": {"1": _azure_ref(e["who"])},
                    "comments": [{"commentType": "system", "author": _azure_ref(e["who"])}],
                }
            )
        comments = [
            {"commentType": "text", "author": _azure_ref(e["who"]), "publishedDate": _iso(e["at"])}
            for _ in range(e["comments"])
        ]
        comments += [
            {
                "commentType": "text",
                "author": _azure_ref(s["author"]),
                "publishedDate": _iso(e["at"]),
            }
            for _ in range(s["author_replies"])
        ]
        if comments:
            threads.append({"status": "fixed", "comments": comments})
    if s["bot_comments"]:
        bot = {"displayName": "Build Service", "uniqueName": "Build\\0f1e2d3c"}
        threads.append({"comments": [{"commentType": "text", "author": bot}]})
    reviewers = [{**_azure_ref(p), "vote": votes.get(p, 0)} for p in s["reviewers"]]
    reviewers.append(
        {
            "displayName": "[Demo]\\Reviewers",
            "uniqueName": "vstfs:///Classification/TeamProject/x\\Reviewers",
            "isContainer": True,
            "vote": 0,
        }
    )
    return {
        "pullRequestId": s["number"],
        "title": s["title"],
        "status": status,
        "isDraft": s["draft"],
        "createdBy": _azure_ref(s["author"]),
        "creationDate": _iso(s["created"]),
        "closedDate": _iso(s["closed"]),
        "reviewers": reviewers,
        "threads": threads,
    }


def _gh_user(p: tuple[str, str]) -> dict[str, str]:
    return {"login": p[1]}


def _github_raw(s: dict[str, Any], repo: str) -> dict[str, Any]:
    reviews, review_comments, issue_comments = [], [], []
    state_for = {10: "APPROVED", 5: "APPROVED", -10: "CHANGES_REQUESTED", 0: "COMMENTED"}
    for e in s["events"]:
        reviews.append(
            {
                "user": _gh_user(e["who"]),
                "state": state_for[e["vote"]],
                "submitted_at": _iso(e["at"]),
            }
        )
        review_comments += [
            {"user": _gh_user(e["who"]), "created_at": _iso(e["at"])} for _ in range(e["comments"])
        ]
    issue_comments += [
        {"user": _gh_user(s["author"]), "created_at": _iso(s["created"])}
        for _ in range(s["author_replies"])
    ]
    if s["bot_comments"]:
        issue_comments.append(
            {"user": {"login": "github-actions[bot]"}, "created_at": _iso(s["created"])}
        )
    reviewed = {e["who"] for e in s["events"]}
    last = max(
        [s["created"], *(e["at"] for e in s["events"])] + ([s["closed"]] if s["closed"] else [])
    )
    return {
        "number": s["number"],
        "title": s["title"],
        "state": "open" if s["state"] == "open" else "closed",
        "draft": s["draft"],
        "user": _gh_user(s["author"]),
        "created_at": _iso(s["created"]),
        "updated_at": _iso(last),
        "closed_at": _iso(s["closed"]),
        "merged_at": _iso(s["closed"]) if s["state"] == "merged" else None,
        "html_url": f"https://github.com/demo/{repo}/pull/{s['number']}",
        "requested_reviewers": [_gh_user(p) for p in s["reviewers"] if p not in reviewed],
        "reviews": reviews,
        "review_comments": review_comments,
        "issue_comments": issue_comments,
    }
