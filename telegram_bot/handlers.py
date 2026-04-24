"""Command + message + inline-query handlers for the Telegram bot."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.ext import ContextTypes

from config.settings import settings
from telegram_bot import messages
from telegram_bot.enrollment import (
    handle_github_username_reply,
    is_pending,
    start_enrollment,
)
from tools import github_tools
from utils.fuzzy_resolver import fuzzy_extract
from utils.github_cache import cache as gh_cache
from utils.logger import get_logger
from utils.mongo import get_db
from utils.user_registry import (
    find_by_telegram_username,
    get_cached,
    list_users,
    promote,
    revoke_user,
    update_last_seen,
)

log = get_logger(__name__)


def _in_bypass(telegram_id: int) -> bool:
    return telegram_id in settings.ALLOWED_TELEGRAM_USERS


async def _auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    """Return the user doc if allowed. Else trigger enrollment / reject; return None."""
    tg = update.effective_user
    chat = update.effective_chat
    if tg is None or chat is None:
        return None

    user = await get_cached(tg.id)
    if user and user.get("status") == "active":
        await update_last_seen(tg.id)
        return user

    if _in_bypass(tg.id):
        log.warning("auth.bypass_used", telegram_id=tg.id)
        now = datetime.now(UTC)
        return {
            "_id": tg.id,
            "status": "active",
            "role": "admin",
            "github_username": "(bypass)",
            "telegram_username": tg.username,
            "enrolled_at": now,
            "last_seen": now,
        }

    if user and user.get("status") == "revoked":
        await context.bot.send_message(
            chat_id=chat.id,
            text=messages.build_revoked_message(),
            parse_mode="HTML",
        )
        return None

    await start_enrollment(update, context)
    return None


def _require_admin(user: dict[str, Any]) -> bool:
    return user.get("role") == "admin"


# ───────────────────── commands ─────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    chat = update.effective_chat
    if tg is None or chat is None:
        return
    user = await get_cached(tg.id)
    if user and user.get("status") == "active":
        await context.bot.send_message(
            chat_id=chat.id,
            text=messages.build_help_message(user.get("role", "member")),
            parse_mode="HTML",
        )
        return
    await start_enrollment(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _auth(update, context)
    if user is None or update.effective_chat is None:
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_help_message(user.get("role", "member")),
        parse_mode="HTML",
    )


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _auth(update, context)
    if user is None or update.effective_chat is None:
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_whoami_message(user),
        parse_mode="HTML",
    )


async def cmd_repos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    result = await github_tools.list_repos()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_repos_message(result),
        parse_mode="HTML",
    )


async def cmd_branches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args = context.args or []
    if not args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: <code>/branches &lt;repo&gt;</code>",
            parse_mode="HTML",
        )
        return
    repo = args[0]
    try:
        result = await github_tools.list_branches(repo=repo)
    except ValueError:
        suggestions = fuzzy_extract(repo, gh_cache.repos, limit=5, score_cutoff=50)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.build_did_you_mean_message(repo, suggestions),
            parse_mode="HTML",
        )
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_branches_message(result),
        parse_mode="HTML",
    )


async def cmd_commits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args = context.args or []
    if len(args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: <code>/commits &lt;repo&gt; &lt;branch&gt;</code>",
            parse_mode="HTML",
        )
        return
    try:
        result = await github_tools.list_commits(repo=args[0], branch=args[1])
    except ValueError as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.build_error_message(str(e)),
            parse_mode="HTML",
        )
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_commits_message(result),
        parse_mode="HTML",
    )


async def cmd_prs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args = context.args or []
    if not args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: <code>/prs &lt;repo&gt; [open|closed|all]</code>",
            parse_mode="HTML",
        )
        return
    state = args[1] if len(args) > 1 else "open"
    try:
        result = await github_tools.list_prs(repo=args[0], state=state)
    except ValueError as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.build_error_message(str(e)),
            parse_mode="HTML",
        )
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_prs_message(result),
        parse_mode="HTML",
    )


async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args = context.args or []
    if not args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: <code>/files &lt;repo&gt; [branch]</code>",
            parse_mode="HTML",
        )
        return
    branch = args[1] if len(args) > 1 else "main"
    try:
        result = await github_tools.list_files(repo=args[0], branch=branch)
    except ValueError as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.build_error_message(str(e)),
            parse_mode="HTML",
        )
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_files_message(result),
        parse_mode="HTML",
    )


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="<b>🔄 Refreshing cache…</b>",
        parse_mode="HTML",
    )
    result = await github_tools.refresh_cache()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_refresh_result(result),
        parse_mode="HTML",
    )


# ───────────────────── /users (admin subcommands) ─────────────────────


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _auth(update, context)
    if user is None or update.effective_chat is None:
        return
    args = context.args or []
    chat_id = update.effective_chat.id

    if not args:
        users = await list_users()
        await context.bot.send_message(
            chat_id=chat_id,
            text=messages.build_users_list_message(users),
            parse_mode="HTML",
        )
        return

    sub = args[0]
    rest = args[1:]

    if sub == "pending":
        if not _require_admin(user):
            await context.bot.send_message(
                chat_id=chat_id,
                text=messages.build_admin_only_message(),
                parse_mode="HTML",
            )
            return
        rows = [p async for p in get_db().pending_enrollments.find({})]
        if not rows:
            await context.bot.send_message(
                chat_id=chat_id, text="<i>No pending enrollments.</i>", parse_mode="HTML"
            )
            return
        lines = [f"<b>Pending enrollments ({len(rows)})</b>"]
        for p in rows:
            lines.append(
                f"  • <code>{p['_id']}</code>  attempts=<code>{p.get('attempts', 0)}</code>"
            )
        await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="HTML")
        return

    if sub == "revoke":
        if not _require_admin(user):
            await context.bot.send_message(
                chat_id=chat_id,
                text=messages.build_admin_only_message(),
                parse_mode="HTML",
            )
            return
        if not rest:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Usage: <code>/users revoke @handle</code>",
                parse_mode="HTML",
            )
            return
        handle = rest[0].lstrip("@")
        target = await find_by_telegram_username(handle)
        if not target:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"<i>No enrolled user with Telegram @{handle}.</i>",
                parse_mode="HTML",
            )
            return
        ok = await revoke_user(
            target["_id"],
            reason=f"admin:{user.get('telegram_username') or user['_id']}",
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{'✅' if ok else '⚠️'} revoke @{handle}",
        )
        return

    if sub == "promote":
        if not _require_admin(user):
            await context.bot.send_message(
                chat_id=chat_id,
                text=messages.build_admin_only_message(),
                parse_mode="HTML",
            )
            return
        if not rest:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Usage: <code>/users promote @handle</code>",
                parse_mode="HTML",
            )
            return
        handle = rest[0].lstrip("@")
        target = await find_by_telegram_username(handle)
        if not target:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"<i>No enrolled user with Telegram @{handle}.</i>",
                parse_mode="HTML",
            )
            return
        ok = await promote(target["_id"], "admin")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{'✅' if ok else '⚠️'} promote @{handle} → admin",
        )
        return

    if sub == "reverify":
        if not _require_admin(user):
            await context.bot.send_message(
                chat_id=chat_id,
                text=messages.build_admin_only_message(),
                parse_mode="HTML",
            )
            return
        from utils.user_reverifier import sweep

        await context.bot.send_message(
            chat_id=chat_id,
            text="<i>Running full reverify sweep…</i>",
            parse_mode="HTML",
        )
        checked = await sweep()
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"<b>✅ Reverify complete — {checked} users checked.</b>",
            parse_mode="HTML",
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Unknown subcommand: <code>{sub}</code>. Try <code>/users</code>, <code>/users pending</code>, <code>/users revoke</code>, <code>/users promote</code>, <code>/users reverify</code>.",
        parse_mode="HTML",
    )


# ───────────────────── catch-all (enrollment replies) ─────────────────────


async def handle_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    if tg is None:
        return
    if await is_pending(tg.id):
        await handle_github_username_reply(update, context)


# ───────────────────── inline query ─────────────────────


async def handle_inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,  # noqa: ARG001 — signature required by PTB
) -> None:
    if update.inline_query is None:
        return
    query = update.inline_query.query.strip()
    repos = gh_cache.repos
    if query:
        matches = fuzzy_extract(query, repos, limit=25, score_cutoff=40)
        items = [m[0] for m in matches]
    else:
        items = list(repos[:25])

    brand = settings.display_name()
    results = [
        InlineQueryResultArticle(
            id=r,
            title=r,
            description=f"Repo in {brand}",
            input_message_content=InputTextMessageContent(f"/branches {r}"),
        )
        for r in items
    ]
    await update.inline_query.answer(results, cache_time=60, is_personal=False)
