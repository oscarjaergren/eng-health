from __future__ import annotations

from pathlib import Path

import pytest

CREDENTIAL_VARS = ["AZURE_DEVOPS_ORGANIZATION", "AZURE_DEVOPS_PAT", "GITHUB_OWNER", "GITHUB_TOKEN"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test gets its own data folder and no credentials from the developer's shell."""
    for var in [*CREDENTIAL_VARS, "MOCK_MODE", "IDENTITY_ALIASES", "PRSYNC_BIN", "FAKE_PRSYNC"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # keep a developer's .env out of the test
