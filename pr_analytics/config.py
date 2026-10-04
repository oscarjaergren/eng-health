"""Settings loaded from environment variables (and `.env`)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


class ConfigError(ValueError):
    """Raised when the environment describes an incomplete or invalid setup."""


@dataclass(frozen=True)
class AzureDevOpsSettings:
    organization: str
    token: str


@dataclass(frozen=True)
class GitHubSettings:
    owner: str
    token: str
    owner_type: Literal["org", "user"] = "org"


@dataclass(frozen=True)
class Settings:
    azure: AzureDevOpsSettings | None
    github: GitHubSettings | None
    data_dir: Path
    max_workers: int
    mock: bool
    # Maps one identity onto another, e.g. a GitHub login onto an Azure DevOps email.
    aliases: dict[str, str] = field(default_factory=dict)

    @property
    def platforms(self) -> list[str]:
        return [
            name for name, conf in (("azure_devops", self.azure), ("github", self.github)) if conf
        ]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pr_analytics.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        def pair(a: str, b: str) -> tuple[str, str] | None:
            va, vb = env.get(a, "").strip(), env.get(b, "").strip()
            if va and vb:
                return va, vb
            if va or vb:
                # Half a config is almost always a typo; failing loudly beats
                # silently ignoring a platform the user meant to enable.
                missing = b if va else a
                raise ConfigError(f"{missing} is not set (needed alongside {a if va else b})")
            return None

        azure = pair("AZURE_DEVOPS_ORGANIZATION", "AZURE_DEVOPS_PAT")
        github = pair("GITHUB_OWNER", "GITHUB_TOKEN")

        owner_type = env.get("GITHUB_TYPE", "org").strip().lower()
        if owner_type not in ("org", "user"):
            raise ConfigError(f"GITHUB_TYPE must be 'org' or 'user', got {owner_type!r}")

        try:
            max_workers = int(env.get("MAX_PARALLEL_WORKERS", "8"))
        except ValueError as e:
            raise ConfigError("MAX_PARALLEL_WORKERS must be an integer") from e

        return cls(
            azure=AzureDevOpsSettings(*azure) if azure else None,
            github=GitHubSettings(github[0], github[1], owner_type) if github else None,  # type: ignore[arg-type]
            data_dir=Path(env.get("DATA_DIR", "data")),
            max_workers=max(1, max_workers),
            mock=env.get("MOCK_MODE", "").strip().lower() in ("1", "true", "yes", "on"),
            aliases=_parse_aliases(env.get("IDENTITY_ALIASES", "")),
        )


def _parse_aliases(value: str) -> dict[str, str]:
    aliases = {}
    for item in filter(None, (p.strip() for p in value.split(","))):
        src, sep, dst = item.partition("=")
        if not sep or not src.strip() or not dst.strip():
            raise ConfigError(f"IDENTITY_ALIASES entry {item!r} should look like login=email")
        aliases[src.strip().lower()] = dst.strip().lower()
    return aliases
