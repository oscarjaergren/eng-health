"""Connect GitHub and Azure DevOps through the `gh` and `az` CLIs instead of tokens in `.env`.

The dashboard lists what the signed-in CLI account can see and saves the choice in
`connections.json` in the data folder. No token is stored: the sync engine asks the CLI for a
fresh one at the start of every sync (`sync/src/config.rs`), and the CLI keeps it refreshed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

FILE = "connections.json"
# The Azure DevOps resource id, which Microsoft Entra tokens for it are issued against.
AZURE_DEVOPS = "499b84ac-1321-427f-aa17-267ca6975798"
_PROFILES = "https://app.vssps.visualstudio.com/_apis"


def load(data_dir: Path) -> dict[str, Any]:
    try:
        saved = json.loads((data_dir / FILE).read_text())
    except FileNotFoundError:
        return {}
    return saved if isinstance(saved, dict) else {}


def save(data_dir: Path, platform: str, value: dict[str, str] | None) -> None:
    """Set or, with None, remove one platform's connection."""
    saved = load(data_dir)
    if value is None:
        saved.pop(platform, None)
    else:
        saved[platform] = value
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / FILE).write_text(json.dumps(saved, indent=2) + "\n")


def _run(*args: str) -> str | None:
    """A CLI's stdout, or None when it is missing, not signed in or fails."""
    exe = shutil.which(args[0])
    if exe is None:
        return None
    try:
        done = subprocess.run(
            [exe, *args[1:]], capture_output=True, text=True, timeout=60, check=False
        )
    except subprocess.TimeoutExpired:
        return None
    return done.stdout if done.returncode == 0 else None


def github_accounts() -> list[tuple[str, str]] | None:
    """(owner, "user" or "org") for the signed-in gh account and its organisations."""
    user = _run("gh", "api", "user", "--jq", ".login")
    if not user:
        return None
    orgs = _run("gh", "api", "user/orgs", "--paginate", "--jq", ".[].login") or ""
    return [(user.strip(), "user"), *((o, "org") for o in orgs.split())]


def azure_organizations() -> list[str] | None:
    """Organisations the signed-in az account is a member of."""

    def get(url: str) -> Any:
        out = _run("az", "rest", "--method", "get", "--resource", AZURE_DEVOPS, "--url", url)
        return json.loads(out) if out else None

    me = get(f"{_PROFILES}/profile/profiles/me?api-version=7.1")
    if not me:
        return None
    accounts = get(f"{_PROFILES}/accounts?memberId={me['id']}&api-version=7.1") or {}
    return sorted(a["accountName"] for a in accounts.get("value", []))
