"""SQLite storage for synced pull requests.

One row per PR keyed by platform, repository and number, so a sync updates
individual PRs in place instead of rewriting one large file.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import PullRequest

# Shared with the Rust sync engine (sync/src/store.rs). Bump both together when
# the tables or the PR JSON change shape.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pull_requests (
    key TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL
);
INSERT OR IGNORE INTO meta (id, revision) VALUES (1, 0);
CREATE TABLE IF NOT EXISTS sync_state (
    platform TEXT PRIMARY KEY,
    last_sync TEXT,
    last_attempt TEXT,
    last_error TEXT
);
"""


class SchemaError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncState:
    platform: str
    last_sync: datetime | None
    last_attempt: datetime | None
    last_error: str | None


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            (version,) = c.execute("PRAGMA user_version").fetchone()
            if version > SCHEMA_VERSION:
                raise SchemaError(
                    f"{self.path} uses schema version {version}, but this dashboard "
                    f"understands {SCHEMA_VERSION}. Update the dashboard."
                )
            c.executescript(_SCHEMA)
            c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _conn(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        # A connection per call: Streamlit runs each session on its own thread.
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
                if write:
                    conn.execute("UPDATE meta SET revision = revision + 1")
        finally:
            conn.close()

    def upsert(self, prs: Iterable[PullRequest], people: dict[str, str] | None = None) -> int:
        rows = [(pr.key, pr.platform, json.dumps(pr.to_dict())) for pr in prs]
        with self._conn(write=True) as c:
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

    def pull_requests(self, platform: str | None = None) -> list[PullRequest]:
        sql = "SELECT data FROM pull_requests"
        args: tuple[str, ...] = ()
        if platform:
            sql, args = sql + " WHERE platform = ?", (platform,)
        with self._conn() as c:
            return [PullRequest.from_dict(json.loads(d)) for (d,) in c.execute(sql, args)]

    def people(self) -> dict[str, str]:
        with self._conn() as c:
            return dict(c.execute("SELECT id, name FROM people"))

    def sync_state(self, platform: str) -> SyncState:
        with self._conn() as c:
            row = c.execute(
                "SELECT last_sync, last_attempt, last_error FROM sync_state WHERE platform = ?",
                (platform,),
            ).fetchone()
        last_sync, last_attempt, error = row or (None, None, None)
        return SyncState(
            platform,
            datetime.fromisoformat(last_sync) if last_sync else None,
            datetime.fromisoformat(last_attempt) if last_attempt else None,
            error,
        )

    def record_sync(
        self, platform: str, attempted: datetime, *, succeeded: bool, error: str | None = None
    ) -> None:
        with self._conn(write=True) as c:
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
        with self._conn(write=True) as c:
            c.execute("DELETE FROM pull_requests")
            c.execute("DELETE FROM people")
            c.execute("DELETE FROM sync_state")

    def version(self) -> int:
        """Increases on every write; used as a dashboard cache key."""
        with self._conn() as c:
            (revision,) = c.execute("SELECT revision FROM meta").fetchone()
        return int(revision)
