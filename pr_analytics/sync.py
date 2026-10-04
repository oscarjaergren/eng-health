"""Fetch pull requests from each configured platform into the store.

Used by both the CLI and the dashboard's Sync button.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .clients import ApiError, AuthError, PlatformClient
from .models import PullRequest, Repo
from .store import Store

log = logging.getLogger(__name__)

# Re-read a little before the last sync so PRs that changed while it ran are not missed.
OVERLAP = timedelta(hours=1)
BATCH = 50

Progress = Callable[[float, str], None]


@dataclass
class SyncReport:
    platform: str
    repositories: int = 0
    listed: int = 0
    saved: int = 0
    incomplete: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def sync(
    clients: list[PlatformClient],
    store: Store,
    *,
    full: bool = False,
    max_workers: int = 8,
    progress: Progress | None = None,
) -> list[SyncReport]:
    reports = []
    for client in clients:
        try:
            report = _sync_platform(
                client, store, full=full, max_workers=max_workers, progress=progress
            )
        except AuthError as e:
            report = SyncReport(client.platform, errors=[str(e)])
            store.record_sync(client.platform, datetime.now(UTC), succeeded=False, error=str(e))
        reports.append(report)
    return reports


def _sync_platform(
    client: PlatformClient,
    store: Store,
    *,
    full: bool,
    max_workers: int,
    progress: Progress | None,
) -> SyncReport:
    report = SyncReport(client.platform)
    started = datetime.now(UTC)
    state = store.sync_state(client.platform)
    since = None if full or not state.last_sync else state.last_sync - OVERLAP
    say = progress or (lambda _f, _m: None)

    try:
        repos = client.list_repositories()
    except ApiError as e:
        report.errors.append(str(e))
        store.record_sync(client.platform, started, succeeded=False, error=str(e))
        return report
    report.repositories = len(repos)

    cached = {pr.key: pr for pr in store.pull_requests(client.platform)}

    # Phase 1: list PRs per repository.
    to_fetch: list[tuple[Repo, dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(client.list_pull_requests, r, since): r for r in repos}
        for done, fut in enumerate(as_completed(futures), 1):
            repo = futures[fut]
            say(0.3 * done / max(len(repos), 1), f"{client.platform}: listed {repo.name}")
            try:
                raws = fut.result()
            except AuthError:
                raise
            except ApiError as e:
                report.errors.append(f"{repo.name}: {e}")
                continue
            report.listed += len(raws)
            for raw in raws:
                prev = cached.get(_key(client, repo, raw))
                if prev is None or not client.is_unchanged(raw, prev):
                    to_fetch.append((repo, raw))

    # Phase 2: fetch comments and reviews only for new or changed PRs, saving in
    # batches so an interrupted sync keeps what it already has.
    people: dict[str, str] = {}
    batch: list[PullRequest] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures2 = {
            pool.submit(client.fetch_details, repo, raw): (repo, raw) for repo, raw in to_fetch
        }
        for done, job in enumerate(as_completed(futures2), 1):
            repo, raw = futures2[job]
            job.result()  # re-raises AuthError; other failures leave details unset
            pr = client.to_pull_request(raw, repo, people)
            report.incomplete += not pr.details_complete
            batch.append(pr)
            if len(batch) >= BATCH:
                report.saved += store.upsert(batch, people)
                batch.clear()
            say(0.3 + 0.7 * done / len(to_fetch), f"{client.platform}: {done}/{len(to_fetch)} PRs")
    report.saved += store.upsert(batch, people)

    # Only move the sync window forward if every repository was read; otherwise
    # PRs that closed in a failed repo would never be picked up.
    store.record_sync(
        client.platform,
        started,
        succeeded=report.ok,
        error="; ".join(report.errors[:5]) or None,
    )
    log.info(
        "%s: %d repos, %d PRs listed, %d saved, %d missing review data, %d errors",
        client.platform,
        report.repositories,
        report.listed,
        report.saved,
        report.incomplete,
        len(report.errors),
    )
    return report


def _key(client: PlatformClient, repo: Repo, raw: dict[str, Any]) -> str:
    number = raw.get("pullRequestId", raw.get("number"))
    return f"{client.platform}:{repo.id}:{number}"
