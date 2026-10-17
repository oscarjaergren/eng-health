"""Choices the dashboard remembers between visits, such as the scope, in dashboard.json in the
data folder. Shared by everyone using the same data folder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FILE = "dashboard.json"


def load(data_dir: Path) -> dict[str, Any]:
    try:
        saved = json.loads((data_dir / FILE).read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return {}
    return saved if isinstance(saved, dict) else {}


def save(data_dir: Path, **values: object) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / FILE).write_text(json.dumps(load(data_dir) | values, indent=2) + "\n")
