"""Stands in for the eng-health binary in Python tests.

Speaks the same protocol (JSON lines on stdout, logs on stderr, the same exit
codes) and writes real records to the store. FAKE_SYNC picks a scenario.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import make_pr
from tests.seed import WritableStore


def emit(event: dict[str, Any]) -> None:
    print(json.dumps(event), flush=True)


def report(**fields: object) -> dict[str, Any]:
    base = {"type": "report", "platform": "github", "repositories": 1, "listed": 2, "saved": 2}
    return {**base, "incomplete": 0, "requests": 2, "interrupted": False, "errors": [], **fields}


def main() -> int:
    scenario = os.environ.get("FAKE_SYNC", "ok")
    Path(os.environ.get("FAKE_SYNC_ARGS_FILE", os.devnull)).write_text(" ".join(sys.argv[1:]))

    if scenario == "config":
        print("Configuration problem: GITHUB_OWNER is not set", file=sys.stderr)
        return 2

    if scenario == "wait_for_interrupt":

        def interrupted(*_: object) -> None:
            emit(report(interrupted=True))
            sys.exit(130)

        signal.signal(signal.SIGINT, interrupted)
        emit({"type": "progress", "platform": "github", "fraction": 0.1, "message": "listing"})
        time.sleep(30)
        return 1

    if scenario == "noisy":
        # More than a pipe buffer of log output; must not block.
        sys.stderr.write("log line\n" * 20000)

    emit(
        {"type": "progress", "platform": "github", "fraction": 0.3, "message": "github: listed web"}
    )
    store = WritableStore(Path(os.environ["DATA_DIR"]) / "eng_health.db")
    if "--reset" in sys.argv:
        store.clear()
    store.upsert(
        [make_pr(1), make_pr(2, title="Bump Terraform provider", is_infrastructure=True)],
        {"alice": "Alice"},
    )
    emit({"type": "progress", "platform": "github", "fraction": 1.0, "message": "github: 2/2 PRs"})

    now = datetime.now(UTC)
    if scenario == "errors":
        error = "api: github: 502 from https://api.github.com/graphql"
        store.record_sync("github", now, succeeded=False, error=error)
        emit(report(errors=[error]))
        return 1
    store.record_sync("github", now, succeeded=True)
    emit(report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
