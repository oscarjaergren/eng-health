"""Reads the SQLite database that eng-health (sync/) writes.

One row per PR keyed by platform, repository and number. eng-health is the only
writer; the schema is sync/schema.sql, which both sides run on open.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .models import PullRequest, Team

# The schema shared with the sync engine; it ends by setting user_version.
_SCHEMA = (Path(__file__).resolve().parent.parent / "sync" / "schema.sql").read_text()
SCHEMA_VERSION = int(re.findall(r"PRAGMA user_version = (\d+);", _SCHEMA)[-1])


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
            # Without the final PRAGMA: the engine stamps the version, because it alone re-syncs
            # when it finds an older one.
            c.executescript(_SCHEMA.rsplit("PRAGMA user_version", 1)[0])

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # A connection per call: Streamlit runs each session on its own thread.
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def pull_requests(self, platform: str | None = None) -> list[PullRequest]:
        sql = "SELECT data FROM pull_requests"
        args: tuple[str, ...] = ()
        if platform:
            sql, args = sql + " WHERE platform = ?", (platform,)
        with self._conn() as c:
            return [PullRequest.from_dict(json.loads(d)) for (d,) in c.execute(sql, args)]

    def pipeline_jobs(self) -> pd.DataFrame:
        return self._query("SELECT * FROM pipeline_jobs")

    def test_failures(self) -> pd.DataFrame:
        return self._query("SELECT * FROM test_failures")

    def teams(self) -> list[Team]:
        """Teams as the platforms define them, synced by the engine."""
        with self._conn() as c:
            teams = c.execute("SELECT platform, team_id, name FROM teams").fetchall()
            members = c.execute("SELECT platform, team_id, identity FROM team_members").fetchall()
            repos = c.execute("SELECT platform, team_id, repo_id FROM team_repos").fetchall()
        return [
            Team(
                f"{p}:{t}",
                name,
                frozenset(m for mp, mt, m in members if (mp, mt) == (p, t)),
                frozenset(f"{p}:{r}" for rp, rt, r in repos if (rp, rt) == (p, t)),
            )
            for p, t, name in teams
        ]

    def me(self) -> dict[str, str]:
        """Platform -> who its credentials belong to, as PR records name people."""
        with self._conn() as c:
            return dict(c.execute("SELECT platform, identity FROM me"))

    def repositories(self) -> pd.DataFrame:
        """Every repository the last sync listed: platform, repo_id, name, owner, is_archived
        and is_fork. Empty until the engine that writes it has synced."""
        return self._query("SELECT * FROM repositories")

    def _query(self, sql: str) -> pd.DataFrame:
        with self._conn() as c:
            return pd.read_sql_query(sql, c)

    def people(self) -> dict[str, str]:
        with self._conn() as c:
            return dict(c.execute("SELECT id, name FROM people"))

    def history(self, platform: str) -> tuple[int, int]:
        """How many of a platform's repositories have been read back two years, of how many.
        Short of all while a large organisation's first syncs fill in its history."""
        with self._conn() as c:
            done, total = c.execute(
                "SELECT COUNT(s.repo_id) FILTER (WHERE s.cursor IS NULL), COUNT(*) "
                "FROM repositories r LEFT JOIN repo_sync s USING (platform, repo_id) "
                "WHERE r.platform = ?",
                (platform,),
            ).fetchone()
        return int(done), int(total)

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

    def version(self) -> int:
        """Increases on every write; used as a dashboard cache key."""
        with self._conn() as c:
            (revision,) = c.execute("SELECT revision FROM meta").fetchone()
        return int(revision)
