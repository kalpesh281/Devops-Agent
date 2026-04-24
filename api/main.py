"""FastAPI application entry point.

Lifespan sequence on startup:
    1. Configure structlog (JSON output)
    2. Run `verify_env_security()` — warns on permissive .env / PEM modes
    3. Ping Mongo (logs connected / unreachable)
    4. Create TTL + query indexes (idempotent)
    5. Yield

On shutdown: close the Mongo client.

Routes registered: `/health`, `/metrics`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Importing tools.github_tools populates the tool REGISTRY at startup.
import tools.github_tools  # noqa: F401  # side-effect: @tool decorators register
from api.routes import health, metrics
from config.settings import settings
from telegram_bot.bot import start_bot, stop_bot
from utils import user_reverifier
from utils.github_cache import cache as github_cache
from utils.logger import configure_logging, get_logger
from utils.mongo import close as close_mongo
from utils.mongo import ensure_indexes
from utils.mongo import ping as mongo_ping
from utils.secrets_check import verify_env_security
from utils.user_registry import ensure_indexes as ensure_user_indexes
from utils.user_registry import refresh_cache as refresh_user_cache

configure_logging(settings.LOG_LEVEL)
log = get_logger(__name__)

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log.info(
        "startup.begin",
        version=VERSION,
        agent_port=settings.AGENT_PORT,
        mongo_db=settings.MONGO_DB_NAME,
        github_org=settings.GITHUB_ORG,
    )

    verify_env_security()

    if await mongo_ping():
        log.info("mongo.connected", db=settings.MONGO_DB_NAME)
        try:
            await ensure_indexes()
            await ensure_user_indexes()
            await refresh_user_cache()
        except Exception as e:  # noqa: BLE001 — log and continue; /health reports status
            log.error("mongo.index_ensure_failed", error=str(e))
    else:
        log.error("mongo.unreachable")

    # Phase 2 — kick off the GitHub cache background refresh (5 min interval).
    github_cache.spawn(interval_seconds=300)
    log.info("github_cache.spawned", interval_seconds=300)

    # Phase 3 — Telegram bot + 24h user reverifier.
    await start_bot()
    user_reverifier.start()

    log.info("startup.complete")
    try:
        yield
    finally:
        log.info("shutdown.begin")
        await stop_bot()
        await user_reverifier.stop()
        await github_cache.stop()
        await close_mongo()
        log.info("shutdown.complete")


app = FastAPI(
    title="DevOps Agent",
    version=VERSION,
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(metrics.router)
