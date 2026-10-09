from __future__ import annotations

import os
from pathlib import Path

import pytest

CREDENTIAL_VARS = ["AZURE_DEVOPS_ORGANIZATION", "AZURE_DEVOPS_PAT", "GITHUB_OWNER", "GITHUB_TOKEN"]


def fake_cli(bin_dir: Path, name: str, script: str) -> None:
    """A stand-in for a CLI on PATH, so tests never reach the developer's gh or az logins."""
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{script}\n")
    path.chmod(0o755)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test gets its own data folder, no credentials from the developer's shell, and
    signed-out gh and az CLIs."""
    for var in [*CREDENTIAL_VARS, "MOCK_MODE", "IDENTITY_ALIASES", "ENG_HEALTH_BIN", "FAKE_SYNC"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # keep a developer's .env out of the test
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("gh", "az"):
        fake_cli(bin_dir, name, "exit 1")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
