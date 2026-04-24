"""`users` collection CRUD + in-memory cache (§14.2, §20).

Cache is refreshed from Mongo every 60 s; per-message auth is a dict lookup.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pymongo import ASCENDING, DESCENDING

from config.settings import settings
from utils.logger import get_logger
from utils.mongo import get_db

log = get_logger(__name__)

Status = Literal["active", "revoked", "suspended"]
Role = Literal["member", "admin"]


_cache: dict[int, dict[str, Any]] = {}
_cache_lock = asyncio.Lock()
_cache_last_refresh: datetime | None = None
_CACHE_TTL = timedelta(seconds=60)


async def ensure_indexes() -> None:
    """Create unique + compound indexes + TTL on pending_enrollments. Idempotent."""
    db = get_db()
    await db.users.create_index(
        "github_username",
        unique=True,
        sparse=True,
        name="github_username_unique",
    )
    await db.users.create_index(
        [("status", ASCENDING), ("last_verified", ASCENDING)],
        name="status_lastverified",
    )
    await db.pending_enrollments.create_index(
        "created_at",
        expireAfterSeconds=86400,
        name="ttl_created_at",
    )
    log.info("user_registry.indexes_ensured")


async def refresh_cache() -> None:
    global _cache_last_refresh
    async with _cache_lock:
        db = get_db()
        rows: dict[int, dict[str, Any]] = {}
        async for u in db.users.find({}):
            rows[u["_id"]] = u
        _cache.clear()
        _cache.update(rows)
        _cache_last_refresh = datetime.now(UTC)
        log.info("user_cache.refreshed", count=len(rows))


async def _ensure_fresh() -> None:
    if _cache_last_refresh is None or (datetime.now(UTC) - _cache_last_refresh) > _CACHE_TTL:
        await refresh_cache()


async def get_cached(telegram_id: int) -> dict[str, Any] | None:
    await _ensure_fresh()
    return _cache.get(telegram_id)


async def get_user(telegram_id: int) -> dict[str, Any] | None:
    return await get_db().users.find_one({"_id": telegram_id})


async def upsert_user(
    *,
    telegram_id: int,
    telegram_username: str | None,
    telegram_first_name: str | None,
    github_username: str,
    role: Role = "member",
    enrolled_by: str = "self",
) -> dict[str, Any]:
    now = datetime.now(UTC)
    db = get_db()
    await db.users.update_one(
        {"_id": telegram_id},
        {
            "$set": {
                "telegram_username": telegram_username,
                "telegram_first_name": telegram_first_name,
                "github_username": github_username.lower(),
                "github_org": settings.GITHUB_ORG,
                "status": "active",
                "role": role,
                "enrolled_by": enrolled_by,
                "last_seen": now,
                "last_verified": now,
                "revoked_reason": None,
            },
            "$setOnInsert": {"enrolled_at": now},
        },
        upsert=True,
    )
    full = await db.users.find_one({"_id": telegram_id})
    if full is not None:
        _cache[telegram_id] = full
        return full
    return {"_id": telegram_id, "status": "active", "role": role}


async def revoke_user(telegram_id: int, reason: str) -> bool:
    now = datetime.now(UTC)
    db = get_db()
    result = await db.users.update_one(
        {"_id": telegram_id, "status": "active"},
        {"$set": {"status": "revoked", "revoked_reason": reason, "last_verified": now}},
    )
    if result.matched_count:
        _cache.pop(telegram_id, None)
        log.info("user.revoked", telegram_id=telegram_id, reason=reason)
        return True
    return False


async def promote(telegram_id: int, role: Role) -> bool:
    db = get_db()
    result = await db.users.update_one(
        {"_id": telegram_id},
        {"$set": {"role": role}},
    )
    if result.matched_count:
        full = await db.users.find_one({"_id": telegram_id})
        if full:
            _cache[telegram_id] = full
        log.info("user.promoted", telegram_id=telegram_id, role=role)
        return True
    return False


async def update_last_seen(telegram_id: int) -> None:
    now = datetime.now(UTC)
    await get_db().users.update_one({"_id": telegram_id}, {"$set": {"last_seen": now}})
    if telegram_id in _cache:
        _cache[telegram_id]["last_seen"] = now


async def list_users(status: Status | None = None) -> list[dict[str, Any]]:
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    return [u async for u in get_db().users.find(q).sort("enrolled_at", DESCENDING)]


async def find_by_github_username(github_username: str) -> dict[str, Any] | None:
    return await get_db().users.find_one({"github_username": github_username.lower()})


async def find_by_telegram_username(username: str) -> dict[str, Any] | None:
    return await get_db().users.find_one({"telegram_username": username.lstrip("@")})


def admin_telegram_ids() -> list[int]:
    """Sync — returns admin IDs from current cache snapshot."""
    return [
        uid for uid, u in _cache.items() if u.get("role") == "admin" and u.get("status") == "active"
    ]
