"""Background task: every 24 h, re-verify each active user's org membership.

Also supports lazy rechecks triggered from handlers when a user's
`last_verified` is stale.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

from github import GithubException

from config.settings import settings
from utils.github_cache import cache as gh_cache
from utils.logger import get_logger
from utils.mongo import get_db
from utils.user_registry import revoke_user

log = get_logger(__name__)

REVERIFY_INTERVAL_SECONDS = 24 * 3600
_task: asyncio.Task[None] | None = None


async def _is_org_member(github_username: str) -> bool:
    def _check() -> bool:
        gh = gh_cache._client()
        org = gh.get_organization(settings.GITHUB_ORG)
        try:
            user = gh.get_user(github_username)
            # PyGithub's `get_user(name)` returns NamedUser, but the stub types
            # it as NamedUser | AuthenticatedUser. At runtime either works with
            # has_in_members.
            return bool(org.has_in_members(user))  # type: ignore[arg-type]
        except GithubException:
            return False

    return await asyncio.to_thread(_check)


async def recheck_one(user: dict[str, Any]) -> bool:
    """Return True if still in org (no action); False if revoked."""
    gh_user = user.get("github_username")
    if not gh_user:
        return True
    is_member = await _is_org_member(gh_user)
    now = datetime.now(UTC)
    if is_member:
        await get_db().users.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_verified": now}},
        )
        return True
    await revoke_user(user["_id"], reason="not_in_org")
    log.info("user.reverify_revoked", telegram_id=user["_id"], github_username=gh_user)
    return False


async def sweep() -> int:
    """Check every active user's org membership. Returns count of users checked."""
    db = get_db()
    count = 0
    async for u in db.users.find({"status": "active"}):
        with contextlib.suppress(Exception):
            await recheck_one(u)
        count += 1
    log.info("reverify.sweep_complete", users_checked=count)
    return count


async def _loop() -> None:
    while True:
        with contextlib.suppress(Exception):
            await sweep()
        await asyncio.sleep(REVERIFY_INTERVAL_SECONDS)


def start() -> asyncio.Task[None]:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="user-reverifier")
        log.info("user_reverifier.started", interval_seconds=REVERIFY_INTERVAL_SECONDS)
    return _task


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
        log.info("user_reverifier.stopped")
