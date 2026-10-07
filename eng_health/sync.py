"""Run the Rust sync engine (`sync/`, binary `eng-health`) and read its progress.

It writes one JSON object per line on stdout: `progress` events while it
runs, then a `report` per platform. Logs go to stderr.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings

log = logging.getLogger("eng-health")

EXIT_CONFIG = 2
EXIT_INTERRUPTED = 130

_LOCAL_BUILD = Path(__file__).resolve().parent.parent / "sync" / "target" / "release" / "eng-health"


@dataclass
class Report:
    platform: str
    module: str = "prs"
    repositories: int = 0
    listed: int = 0
    saved: int = 0
    incomplete: int = 0
    requests: int = 0
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> Report:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in event.items() if k in known})


@dataclass
class Result:
    exit_code: int
    reports: list[Report]
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def find_binary() -> str | None:
    """ENG_HEALTH_BIN, then eng-health on PATH, then a local release build."""
    configured = os.environ.get("ENG_HEALTH_BIN", "").strip()
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("eng-health") or (str(_LOCAL_BUILD) if _LOCAL_BUILD.is_file() else None)


def run(
    binary: str,
    settings: Settings,
    *,
    full: bool = False,
    reset: bool = False,
    on_progress: Callable[[float, str], None] | None = None,
) -> Result:
    args = [binary, "sync", "--progress", "json"]
    if reset:
        args.append("--reset")
    elif full:
        args.append("--full")
    # NO_COLOR keeps terminal colour codes out of the forwarded log lines.
    env = {**os.environ, "DATA_DIR": str(settings.data_dir), "NO_COLOR": "1"}
    log.info("running %s", " ".join(args[1:]))
    started = time.monotonic()

    reports: list[Report] = []
    # stderr goes to a file: if it were a pipe nobody reads until the end, a
    # chatty run could fill it and block eng-health.
    with tempfile.TemporaryFile("w+") as err:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err, text=True, env=env)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "progress" and on_progress:
                    on_progress(float(event.get("fraction", 0)), str(event.get("message", "")))
                elif event.get("type") == "report":
                    reports.append(Report.from_event(event))
            code = proc.wait()
        finally:
            if proc.poll() is None:
                # The page was stopped mid-sync: let eng-health finish its batch.
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
        err.seek(0)
        stderr = err.read()
    for line in stderr.splitlines():
        log.info("%s", line)
    level = logging.INFO if code == 0 else logging.WARNING
    log.log(level, "eng-health exited with %d after %.1fs", code, time.monotonic() - started)
    return Result(code, reports, stderr)
