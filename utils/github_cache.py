"""In-memory GitHub repo/branch cache with periodic refresh (§10.2).

The cache is populated from either a GitHub **organization** or a **user**
account — it auto-detects which form `GITHUB_ORG` refers to at refresh time.
This lets the same code work against `GradScalerTeam` (org) or a personal
account without config changes.

- `cache.refresh()` pulls fresh data (blocking PyGithub calls run in a
  threadpool via `asyncio.to_thread`, so FastAPI stays responsive).
- `cache.spawn(interval_seconds=300)` starts a background task that loops
  forever. Cancel via `cache.stop()`.
- The cache is a module-level singleton — every consumer imports `cache`.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

from github import Github, GithubException

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)


class GitHubCache:
    def __init__(self) -> None:
        self._gh: Github | None = None
        self.repos: list[str] = []
        self.branches: dict[str, list[str]] = {}
        self.last_refresh: datetime | None = None
        self.owner_kind: str | None = None  # "organization" | "user" | None
        self._refresh_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def _client(self) -> Github:
        if self._gh is None:
            self._gh = Github(settings.GITHUB_TOKEN)
        return self._gh

    def _resolve_owner(self) -> tuple[str, Any]:
        """Return ('organization' | 'user', entity). Raises on total failure."""
        gh = self._client()
        try:
            org = gh.get_organization(settings.GITHUB_ORG)
            # touch the entity to force a 404 on missing orgs
            _ = org.login
            return "organization", org
        except GithubException as e:
            if e.status != 404:
                raise
        user = gh.get_user(settings.GITHUB_ORG)
        _ = user.login
        return "user", user

    def _fetch_blocking(self) -> tuple[str, list[str], dict[str, list[str]]]:
        """Synchronous fetch — runs in a thread via to_thread()."""
        kind, entity = self._resolve_owner()
        new_repos: list[str] = []
        new_branches: dict[str, list[str]] = {}
        for repo in entity.get_repos():
            new_repos.append(repo.name)
            try:
                new_branches[repo.name] = [b.name for b in repo.get_branches()]
            except GithubException as e:
                log.warning("cache.branches_failed", repo=repo.name, error=str(e))
                new_branches[repo.name] = []
        return kind, new_repos, new_branches

    async def refresh(self) -> None:
        """One-shot refresh. Safe to call concurrently — second caller waits."""
        async with self._lock:
            t0 = datetime.now(UTC)
            try:
                kind, new_repos, new_branches = await asyncio.to_thread(self._fetch_blocking)
            except Exception as e:
                log.error("cache.refresh_failed", error=str(e))
                raise
            self.owner_kind = kind
            self.repos = new_repos
            self.branches = new_branches
            self.last_refresh = datetime.now(UTC)
            elapsed_ms = int((self.last_refresh - t0).total_seconds() * 1000)
            log.info(
                "cache.refreshed",
                owner_kind=kind,
                repo_count=len(self.repos),
                elapsed_ms=elapsed_ms,
            )

    async def _loop(self, interval_seconds: int) -> None:
        while True:
            # refresh() already logs on error; swallow so the loop continues.
            with contextlib.suppress(Exception):
                await self.refresh()
            await asyncio.sleep(interval_seconds)

    def spawn(self, interval_seconds: int = 300) -> asyncio.Task[None]:
        """Start the background refresh task. Idempotent."""
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(
                self._loop(interval_seconds),
                name="github-cache-refresh",
            )
        return self._refresh_task

    async def stop(self) -> None:
        """Cancel the background task; wait for it to unwind."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._refresh_task
            self._refresh_task = None


cache = GitHubCache()
