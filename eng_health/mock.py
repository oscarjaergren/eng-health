"""Generated sample data for running the dashboard without credentials.

Azure DevOps people are identified by email and GitHub people by login, as
in real data; ALIASES merges the two.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import PullRequest, State

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
    repos = [("azure_devops", n) for n in AZURE_REPOS] + [("github", n) for n in GITHUB_REPOS]
    weights = [rng.uniform(0.3, 3) for _ in repos]
    numbers = dict.fromkeys(repos, 0)
    people = {f"{login}@example.com": name for name, login in PEOPLE}
    people.update({login: login for _, login in PEOPLE})

    prs = []
    for _ in range(count):
        repo = rng.choices(repos, weights)[0]
        numbers[repo] += 1
        prs.append(_record(_spec(rng, now, numbers[repo]), *repo))
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
    }


_STATES = {"open": State.OPEN, "merged": State.MERGED, "abandoned": State.ABANDONED}


def _record(s: dict[str, Any], platform: str, repo: str) -> PullRequest:
    azure = platform == "azure_devops"

    def who(p: tuple[str, str]) -> str:
        return f"{p[1]}@example.com" if azure else p[1]

    author = who(s["author"])
    comment_counts = {who(e["who"]): e["comments"] for e in s["events"] if e["comments"]}
    if s["author_replies"]:
        comment_counts[author] = s["author_replies"]
    number = s["number"]
    return PullRequest(
        platform=platform,
        repo_id=f"{platform[:2]}-{repo}",
        repository=repo,
        number=number,
        title=s["title"],
        author=author,
        state=_STATES[s["state"]],
        is_draft=s["draft"],
        created_at=s["created"],
        closed_at=s["closed"],
        url=(
            f"https://dev.azure.com/demo/_git/{repo}/pullrequest/{number}"
            if azure
            else f"https://github.com/demo/{repo}/pull/{number}"
        ),
        is_infrastructure=s["title"] in INFRA_TITLES,
        updated_at=None if azure else max([s["created"], *(e["at"] for e in s["events"])]),
        reviewers=[who(p) for p in s["reviewers"]],
        approvers=sorted(who(e["who"]) for e in s["events"] if e["vote"] >= 5),
        rejecters=sorted(who(e["who"]) for e in s["events"] if e["vote"] == -10),
        comment_counts=comment_counts,
        first_responses={who(e["who"]): e["at"] for e in s["events"]},
    )


# --- Pipelines -------------------------------------------------------------

WORKFLOWS = {"CI": ["build", "test", "lint"], "Deploy": ["deploy"], "Nightly": ["e2e"]}
FLAKY_TESTS = ["tests.test_api::test_timeout_retry", "OrderTests.Concurrent_checkout"]
BROKEN_TESTS = ["tests.test_store::test_migration", "ParserTests.Parses_unicode"]


def mock_pipelines(
    seed: int = 7, runs: int = 300, now: datetime | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rows shaped like eng-health's `pipeline_jobs` and `test_failures` tables."""
    rng = random.Random(seed)
    now = now or datetime.now(UTC)
    jobs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for run_id in range(1, runs + 1):
        repo = rng.choice(GITHUB_REPOS)
        workflow = rng.choices(list(WORKFLOWS), [6, 2, 1])[0]
        age = rng.uniform(0, 90)
        start = now - timedelta(days=age)
        default = workflow != "CI" or rng.random() < 0.5
        test_fails = workflow in ("CI", "Nightly") and rng.random() < 0.18
        # Most failures pass on a rerun (flaky); the rest are real breakages.
        flaky = test_fails and rng.random() < 0.65
        attempts = 2 if flaky else 1
        for attempt in range(1, attempts + 1):
            for i, name in enumerate(WORKFLOWS[workflow]):
                # Nightly e2e gets slower over the window, so the trend shows.
                base = 25 + (90 - age) / 6 if workflow == "Nightly" else 3 + 2 * i
                minutes = rng.lognormvariate(0, 0.25) * base
                failed = test_fails and name in ("test", "e2e") and attempt == 1
                jobs.append(
                    {
                        "key": f"github:{repo}:{run_id}:{attempt}:{name}",
                        "repo_id": repo,
                        "repository": repo,
                        "pipeline": workflow,
                        "run_id": run_id,
                        "attempt": attempt,
                        "branch": "main" if default else f"feature/{run_id}",
                        "is_default_branch": int(default),
                        "commit_sha": f"{run_id:07x}",
                        "name": name,
                        "conclusion": "failure" if failed else "success",
                        "started_at": start.isoformat(),
                        "finished_at": (start + timedelta(minutes=minutes)).isoformat(),
                        "url": f"https://github.com/demo/{repo}/actions/runs/{run_id}",
                    }
                )
            start += timedelta(minutes=30)
        if test_fails:
            pool = FLAKY_TESTS if flaky else BROKEN_TESTS
            failures.append({"repo_id": repo, "run_id": run_id, "test_id": rng.choice(pool)})
    return jobs, failures
