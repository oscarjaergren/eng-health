"""Running the sync engine as a subprocess, against a fake binary."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

from eng_health import sync
from eng_health.config import Settings
from eng_health.store import Store

FAKE = Path(__file__).parent / "fake_sync.py"


def fake_binary(tmp_path: Path) -> str:
    """A wrapper script, because sync.run executes a single binary path."""
    wrapper = tmp_path / "eng-health"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    wrapper.chmod(0o755)
    return str(wrapper)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env({"DATA_DIR": str(tmp_path / "data")})


def test_progress_reports_and_data(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    args_file = tmp_path / "args"
    monkeypatch.setenv("FAKE_SYNC_ARGS_FILE", str(args_file))
    seen: list[tuple[float, str]] = []
    result = sync.run(fake_binary(tmp_path), settings, on_progress=lambda f, m: seen.append((f, m)))
    assert result.ok
    assert seen == [(0.3, "github: listed web"), (1.0, "github: 2/2 PRs")]
    assert [(r.platform, r.saved, r.requests) for r in result.reports] == [("github", 2, 2)]
    assert len(Store(settings.db_path).pull_requests()) == 2
    assert args_file.read_text() == "sync --progress json"


@pytest.mark.parametrize(
    ("kwargs", "flag"), [({"full": True}, "--full"), ({"reset": True}, "--reset")]
)
def test_full_and_reset_flags(
    tmp_path: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    flag: str,
) -> None:
    args_file = tmp_path / "args"
    monkeypatch.setenv("FAKE_SYNC_ARGS_FILE", str(args_file))
    sync.run(fake_binary(tmp_path), settings, **kwargs)
    assert args_file.read_text().endswith(flag)


def test_errors_and_config_problems(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_SYNC", "errors")
    result = sync.run(fake_binary(tmp_path), settings)
    assert result.exit_code == 1
    assert "502" in result.reports[0].errors[0]

    monkeypatch.setenv("FAKE_SYNC", "config")
    result = sync.run(fake_binary(tmp_path), settings)
    assert result.exit_code == sync.EXIT_CONFIG
    assert result.reports == []
    assert "GITHUB_OWNER" in result.stderr


def test_heavy_logging_does_not_block_and_is_forwarded(
    tmp_path: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("FAKE_SYNC", "noisy")
    with caplog.at_level("INFO", logger="eng-health"):
        result = sync.run(fake_binary(tmp_path), settings)
    assert result.ok
    assert result.stderr.count("log line") == 20000
    messages = [r.getMessage() for r in caplog.records]
    assert messages.count("log line") == 20000
    assert messages[0] == "running sync --progress json"
    assert messages[-1].startswith("eng-health exited with 0 after")


def test_stopping_the_page_interrupts_the_sync(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Streamlit stops a script by raising inside it; eng-health must get SIGINT."""
    monkeypatch.setenv("FAKE_SYNC", "wait_for_interrupt")

    def stop(_f: float, _m: str) -> None:
        raise KeyboardInterrupt

    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        sync.run(fake_binary(tmp_path), settings, on_progress=stop)
    # Well under the 15 s kill fallback, so SIGINT is what ended it.
    assert time.monotonic() - started < 10


def test_find_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENG_HEALTH_BIN", str(tmp_path / "missing"))
    assert sync.find_binary() is None
    monkeypatch.setenv("ENG_HEALTH_BIN", fake_binary(tmp_path))
    assert sync.find_binary() == str(tmp_path / "eng-health")
    monkeypatch.delenv("ENG_HEALTH_BIN")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert sync.find_binary() == str(tmp_path / "eng-health")
