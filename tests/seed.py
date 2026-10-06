"""Writes the database the way prsync does, for tests. The dashboard never writes."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime

from pr_analytics.models import PullRequest
from pr_analytics.store import Store


class WritableStore(Store):
    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._conn() as c:
            yield c
            c.execute("UPDATE meta SET revision = revision + 1")

    def upsert(self, prs: Iterable[PullRequest], people: dict[str, str] | None = None) -> int:
        rows = [(pr.key, pr.platform, json.dumps(pr.to_dict())) for pr in prs]
        with self._write() as c:
            c.executemany(
                "INSERT INTO pull_requests (key, platform, data) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET data = excluded.data",
                rows,
            )
            if people:
                c.executemany(
                    "INSERT INTO people (id, name) VALUES (?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
                    people.items(),
                )
        return len(rows)

    def record_sync(
        self, platform: str, attempted: datetime, *, succeeded: bool, error: str | None = None
    ) -> None:
        with self._write() as c:
            c.execute(
                "INSERT INTO sync_state (platform, last_sync, last_attempt, last_error) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(platform) DO UPDATE SET "
                "last_sync = COALESCE(excluded.last_sync, sync_state.last_sync), "
                "last_attempt = excluded.last_attempt, last_error = excluded.last_error",
                (
                    platform,
                    attempted.isoformat() if succeeded else None,
                    attempted.isoformat(),
                    error,
                ),
            )

    def clear(self) -> None:
        with self._write() as c:
            c.execute("DELETE FROM pull_requests")
            c.execute("DELETE FROM people")
            c.execute("DELETE FROM sync_state")

    def upsert_jobs(self, jobs: Iterable[dict]) -> None:
        """Rows shaped like prsync's `pipeline_jobs` (see sync/src/store.rs)."""
        rows = list(jobs)
        with self._write() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS pipeline_jobs (key TEXT PRIMARY KEY, repo_id TEXT, "
                "repository TEXT, pipeline TEXT, run_id INTEGER, attempt INTEGER, branch TEXT, "
                "is_default_branch INTEGER, commit_sha TEXT, name TEXT, conclusion TEXT, "
                "started_at TEXT, finished_at TEXT, url TEXT)"
            )
            c.executemany(
                f"INSERT OR REPLACE INTO pipeline_jobs ({', '.join(rows[0])}) "
                f"VALUES ({', '.join('?' * len(rows[0]))})",
                [tuple(r.values()) for r in rows],
            )
