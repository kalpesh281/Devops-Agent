"""Async MongoDB handle + TTL index management.

One `motor` client for the whole app (checkpointer, audit log, cache,
scraper all share it — §7.4). Collections use the canonical names from
spec §20 and are accessed directly via `get_db().<collection>`.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)

_client: AsyncIOMotorClient[dict[str, Any]] | None = None
_db: AsyncIOMotorDatabase[dict[str, Any]] | None = None


def get_client() -> AsyncIOMotorClient[dict[str, Any]]:
    """Return the shared motor client, creating it on first access."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.MONGO_URL,
            serverSelectionTimeoutMS=5000,
        )
    return _client


def get_db() -> AsyncIOMotorDatabase[dict[str, Any]]:
    """Return the database handle for MONGO_DB_NAME."""
    global _db
    if _db is None:
        _db = get_client()[settings.MONGO_DB_NAME]
    return _db


async def ping() -> bool:
    """Cheap liveness probe against the admin DB."""
    try:
        await get_client().admin.command("ping")
        return True
    except PyMongoError as e:
        log.warning("mongo.ping_failed", error=str(e))
        return False


async def ensure_indexes() -> None:
    """Create TTL + query indexes idempotently. §20 spec.

    - checkpoints         → 7-day TTL on `created_at`
    - container_logs      → 7-day TTL on `created_at` + `(deployment, timestamp desc)`
    - diagnostic_events   → 30-day TTL on `created_at` + `(deployment, triggered_at desc)`
    """
    db = get_db()

    # checkpoints (LangGraph)
    await db.checkpoints.create_index(
        "created_at",
        expireAfterSeconds=7 * 24 * 3600,
        name="ttl_created_at",
    )

    # container_logs
    await db.container_logs.create_index(
        "created_at",
        expireAfterSeconds=7 * 24 * 3600,
        name="ttl_created_at",
    )
    await db.container_logs.create_index(
        [("deployment", 1), ("timestamp", -1)],
        name="deployment_timestamp_desc",
    )

    # diagnostic_events
    await db.diagnostic_events.create_index(
        "created_at",
        expireAfterSeconds=30 * 24 * 3600,
        name="ttl_created_at",
    )
    await db.diagnostic_events.create_index(
        [("deployment", 1), ("triggered_at", -1)],
        name="deployment_triggered_desc",
    )

    log.info(
        "mongo.indexes_ensured",
        collections=["checkpoints", "container_logs", "diagnostic_events"],
    )


async def close() -> None:
    """Close the shared client. Safe to call multiple times."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        log.info("mongo.closed")
