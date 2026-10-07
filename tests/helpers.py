"""Shared builders for tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from eng_health.models import PullRequest, State

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def make_pr(number: int = 1, **overrides: Any) -> PullRequest:
    fields: dict[str, Any] = {
        "platform": "github",
        "repo_id": "1",
        "repository": "web",
        "number": number,
        "title": f"PR {number}",
        "author": "alice",
        "state": State.MERGED,
        "is_draft": False,
        "created_at": NOW - timedelta(days=30),
        "closed_at": NOW - timedelta(days=29),
        "url": f"https://github.com/o/web/pull/{number}",
        "is_infrastructure": False,
    }
    fields.update(overrides)
    return PullRequest(**fields)
