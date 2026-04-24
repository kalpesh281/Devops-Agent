"""Build + start the Telegram bot Application.

We use manual `initialize()` / `start()` / `updater.start_polling()` instead of
`Application.run_polling()` so the FastAPI event loop owns the lifespan.
"""

from __future__ import annotations

from typing import Any

from telegram import BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from config.settings import settings
from telegram_bot import handlers
from utils.logger import get_logger

# Shown in Telegram's `/` autocomplete menu. Synced on every bot start.
_COMMAND_MENU: list[BotCommand] = [
    BotCommand("start", "Start or re-enroll"),
    BotCommand("help", "What I can do"),
    BotCommand("whoami", "Your enrollment info"),
    BotCommand("repos", "List all repos"),
    BotCommand("branches", "Branches for a repo"),
    BotCommand("commits", "Recent commits"),
    BotCommand("prs", "Open pull requests"),
    BotCommand("files", "Key files in a repo"),
    BotCommand("refresh", "Force cache refresh"),
    BotCommand("users", "Who's on the team"),
]

log = get_logger(__name__)

# python-telegram-bot's Application is generic over 6 type params we don't care about.
AppType = Application[Any, Any, Any, Any, Any, Any]

_app: AppType | None = None


def _build_application() -> AppType:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("whoami", handlers.cmd_whoami))
    app.add_handler(CommandHandler("repos", handlers.cmd_repos))
    app.add_handler(CommandHandler("branches", handlers.cmd_branches))
    app.add_handler(CommandHandler("commits", handlers.cmd_commits))
    app.add_handler(CommandHandler("prs", handlers.cmd_prs))
    app.add_handler(CommandHandler("files", handlers.cmd_files))
    app.add_handler(CommandHandler("refresh", handlers.cmd_refresh))
    app.add_handler(CommandHandler("users", handlers.cmd_users))

    # Inline-mode fuzzy search
    app.add_handler(InlineQueryHandler(handlers.handle_inline_query))

    # Catch-all for enrollment replies (non-command text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_any_message))
    return app


async def start_bot() -> AppType | None:
    """Start the bot in polling mode. Returns None if no token configured."""
    global _app
    if not settings.TELEGRAM_BOT_TOKEN:
        log.warning("telegram.bot.skipped_no_token")
        return None
    if _app is not None:
        return _app

    _app = _build_application()
    await _app.initialize()
    await _app.start()
    assert _app.updater is not None
    await _app.updater.start_polling(drop_pending_updates=True)
    # Populate Telegram's `/` autocomplete dropdown for every user.
    await _app.bot.set_my_commands(_COMMAND_MENU)
    me = _app.bot
    log.info(
        "telegram.bot.started",
        username=(await me.get_me()).username,
        admin_id=settings.FIRST_ADMIN_TELEGRAM_ID,
        commands_registered=len(_COMMAND_MENU),
    )
    return _app


async def stop_bot() -> None:
    global _app
    if _app is None:
        return
    if _app.updater is not None:
        await _app.updater.stop()
    await _app.stop()
    await _app.shutdown()
    _app = None
    log.info("telegram.bot.stopped")
