"""Command line: sync PRs into the local store, or export them to CSV."""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from . import metrics
from .clients import make_clients
from .config import ConfigError, Settings
from .store import Store
from .sync import sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="main.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sync", help="fetch new and changed PRs")
    s.add_argument("--full", action="store_true", help="re-read every PR, not just recent ones")
    s.add_argument("--reset", action="store_true", help="delete local data first (implies --full)")
    e = sub.add_parser("export", help="write all stored PRs to a CSV file")
    e.add_argument("path")
    args = parser.parse_args(argv)

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = Settings.from_env()
    except ConfigError as err:
        print(f"Configuration problem: {err}", file=sys.stderr)
        return 2
    store = Store(settings.db_path)

    if args.command == "export":
        df = metrics.to_frame(store.pull_requests(), settings.aliases)
        metrics.export_table(df, store.people()).to_csv(args.path, index=False)
        print(f"Wrote {len(df)} PRs to {args.path}")
        return 0

    if not settings.platforms:
        print("No platform configured. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2
    if args.reset:
        store.clear()
    reports = sync(
        make_clients(settings),
        store,
        full=args.full or args.reset,
        max_workers=settings.max_workers,
    )
    for r in reports:
        for msg in r.errors:
            print(f"{r.platform}: {msg}", file=sys.stderr)
    return 0 if all(r.ok for r in reports) else 1
