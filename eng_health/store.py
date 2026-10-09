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

from .models import PullRequest

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

    def _query(self, sql: str) -> pd.DataFrame:
        with self._conn() as c:
            return pd.read_sql_query(sql, c)

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

    def version(self) -> int:
        """Increases on every write; used as a dashboard cache key."""
        with self._conn() as c:
            (revision,) = c.execute("SELECT revision FROM meta").fetchone()
        return int(revision)
