"""Command line: export stored PRs to CSV. Syncing is done by `eng-health` (see sync/)."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from . import metrics
from .config import ConfigError, Settings
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="main.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export", help="write all stored PRs to a CSV file")
    e.add_argument("path")
    args = parser.parse_args(argv)

    load_dotenv()
    try:
        settings = Settings.from_env()
    except ConfigError as err:
        print(f"Configuration problem: {err}", file=sys.stderr)
        return 2

    store = Store(settings.db_path)
    df = metrics.to_frame(store.pull_requests(), settings.aliases)
    metrics.export_table(df, store.people()).to_csv(args.path, index=False)
    print(f"Wrote {len(df)} PRs to {args.path}")
    return 0
