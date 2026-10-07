"""Settings the dashboard needs, from environment variables (and `.env`).

The sync engine (`eng-health`, in sync/) reads the same variables and validates the
ones only it uses.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """Raised when the environment describes an incomplete or invalid setup."""


@dataclass(frozen=True)
class Settings:
    # Organisation and owner names, set only when the platform is fully configured.
    azure_organization: str | None
    github_owner: str | None
    data_dir: Path
    mock: bool
    # Maps one identity onto another, e.g. a GitHub login onto an Azure DevOps email.
    aliases: dict[str, str] = field(default_factory=dict)

    @property
    def platforms(self) -> list[str]:
        owners = (("azure_devops", self.azure_organization), ("github", self.github_owner))
        return [name for name, owner in owners if owner]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "eng_health.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        def pair(a: str, b: str) -> str | None:
            va, vb = env.get(a, "").strip(), env.get(b, "").strip()
            if va and vb:
                return va
            if va or vb:
                # Half a config is almost always a typo; failing loudly beats
                # silently ignoring a platform the user meant to enable.
                missing = b if va else a
                raise ConfigError(f"{missing} is not set (needed alongside {a if va else b})")
            return None

        return cls(
            azure_organization=pair("AZURE_DEVOPS_ORGANIZATION", "AZURE_DEVOPS_PAT"),
            github_owner=pair("GITHUB_OWNER", "GITHUB_TOKEN"),
            data_dir=Path(env.get("DATA_DIR", "data")),
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
