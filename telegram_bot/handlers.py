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
from telegram_bot.keyboards import build_pagination_keyboard, build_services_keyboard
from tools import github_tools, server_tools
from utils.fuzzy_resolver import fuzzy_extract
from utils.github_cache import cache as gh_cache
from utils.logger import get_logger
from utils.mongo import get_db
from utils.server_registry import list_servers as list_servers_registry
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


def _parse_page(args: list[str]) -> tuple[list[str], int]:
    """Peel a trailing integer off args and return (rest, page).

    Lets commands accept ``/repos 2`` or ``/branches foo 3`` without each
    handler having to duplicate the parsing. Non-numeric trailing args are
    left in place. Negative / zero pages clamp to 1.
    """
    if not args:
        return args, 1
    last = args[-1]
    if last.isdigit():
        page = max(1, int(last))
        return args[:-1], page
    return args, 1


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
    _, page = _parse_page(context.args or [])
    result = await github_tools.list_repos()
    result["_page"] = page
    total_pages = max(
        1,
        (len(result.get("repos", [])) + messages.REPOS_PER_PAGE - 1) // messages.REPOS_PER_PAGE,
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_repos_message(result),
        parse_mode="HTML",
        reply_markup=build_pagination_keyboard("repos", min(page, total_pages), total_pages),
    )


async def cmd_branches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args, page = _parse_page(context.args or [])
    if not args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: <code>/branches &lt;repo&gt; [page]</code>",
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
    result["_page"] = page
    total_pages = max(
        1,
        (len(result.get("branches", [])) + messages.BRANCHES_PER_PAGE - 1)
        // messages.BRANCHES_PER_PAGE,
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_branches_message(result),
        parse_mode="HTML",
        reply_markup=build_pagination_keyboard(
            "br", min(page, total_pages), total_pages, extra_arg=repo
        ),
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
    args, page = _parse_page(context.args or [])
    if not args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: <code>/prs &lt;repo&gt; [open|closed|all] [page]</code>",
            parse_mode="HTML",
        )
        return
    repo = args[0]
    state = args[1] if len(args) > 1 else "open"
    try:
        result = await github_tools.list_prs(repo=repo, state=state)
    except ValueError as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.build_error_message(str(e)),
            parse_mode="HTML",
        )
        return
    result["_page"] = page
    total_pages = max(
        1,
        (len(result.get("prs", [])) + messages.PRS_PER_PAGE - 1) // messages.PRS_PER_PAGE,
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_prs_message(result),
        parse_mode="HTML",
        reply_markup=build_pagination_keyboard(
            "prs", min(page, total_pages), total_pages, extra_arg=f"{repo}|{state}"
        ),
    )


async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args = context.args or []
    if not args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "Usage: <code>/files &lt;repo&gt; [path] [branch]</code>\n\n"
                "Examples:\n"
                "  <code>/files trading-dashboard</code> — root of main\n"
                "  <code>/files mymono frontend</code> — frontend folder on main\n"
                "  <code>/files mymono backend develop</code> — backend on develop\n\n"
                "<i>Tip: run <code>/services &lt;repo&gt;</code> first to discover "
                "deployable folders in a monorepo.</i>"
            ),
            parse_mode="HTML",
        )
        return
    repo = args[0]
    path = args[1] if len(args) > 1 else "."
    # None → list_files resolves the repo's actual default branch.
    branch = args[2] if len(args) > 2 else None
    try:
        result = await github_tools.list_files(repo=repo, branch=branch, path=path)
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


async def cmd_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args = context.args or []
    if not args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "Usage: <code>/services &lt;repo&gt; [branch]</code>\n\n"
                "<i>Finds every <code>deploy.config.yml</code> in the repo — "
                "works for both single-service repos and monorepos.</i>"
            ),
            parse_mode="HTML",
        )
        return
    repo = args[0]
    # Branch: use the repo's actual default if not specified (avoids the
    # "main" assumption that breaks on master/develop/feature-branch repos).
    branch = args[1] if len(args) > 1 else None
    try:
        result = await github_tools.list_services(repo=repo, branch=branch)
    except ValueError as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.build_error_message(str(e)),
            parse_mode="HTML",
        )
        return
    # Pass the resolved branch to the keyboard so "tap to check" drills into
    # /files on the SAME branch we just scanned.
    resolved_branch = result.get("branch", "main")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_services_message(result),
        parse_mode="HTML",
        reply_markup=build_services_keyboard(repo, result.get("services", []), resolved_branch),
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


# ───────────────────── Phase 4: servers + status + disk ─────────────────────


async def _resolve_server_id(query: str) -> tuple[str | None, list[tuple[str, float]]]:
    """Return (exact_id, suggestions). Exactly one is non-empty."""
    known = [s.id for s in await list_servers_registry(get_db())]
    if query in known:
        return query, []
    return None, fuzzy_extract(query, known, limit=5, score_cutoff=50)


async def cmd_servers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    result = await server_tools.list_servers_tool()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=messages.build_servers_message(result),
        parse_mode="HTML",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args = context.args or []
    chat_id = update.effective_chat.id

    server_id: str | None = None
    if args:
        resolved, suggestions = await _resolve_server_id(args[0])
        if resolved is None:
            await context.bot.send_message(
                chat_id=chat_id,
                text=messages.build_did_you_mean_message(args[0], suggestions),
                parse_mode="HTML",
            )
            return
        server_id = resolved

    try:
        result = await server_tools.status_tool(server_id=server_id)
    except ValueError as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=messages.build_error_message(str(e)),
            parse_mode="HTML",
        )
        return
    await context.bot.send_message(
        chat_id=chat_id,
        text=messages.build_status_message(result),
        parse_mode="HTML",
    )


async def cmd_disk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _auth(update, context) is None or update.effective_chat is None:
        return
    args = context.args or []
    chat_id = update.effective_chat.id
    if not args:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Usage: <code>/disk &lt;server&gt;</code> — e.g. <code>/disk physical-main</code>",
            parse_mode="HTML",
        )
        return

    resolved, suggestions = await _resolve_server_id(args[0])
    if resolved is None:
        await context.bot.send_message(
            chat_id=chat_id,
            text=messages.build_did_you_mean_message(args[0], suggestions),
            parse_mode="HTML",
        )
        return

    try:
        result = await server_tools.disk_usage_tool(server_id=resolved)
    except ValueError as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=messages.build_error_message(str(e)),
            parse_mode="HTML",
        )
        return
    await context.bot.send_message(
        chat_id=chat_id,
        text=messages.build_disk_message(result),
        parse_mode="HTML",
    )


# ───────────────────── /users (admin subcommands) ─────────────────────


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _auth(update, context)
    if user is None or update.effective_chat is None:
        return
    raw_args = context.args or []
    args, page = _parse_page(raw_args)
    chat_id = update.effective_chat.id

    if not args:
        users = await list_users()
        total_pages = max(
            1,
            (len(users) + messages.USERS_PER_PAGE - 1) // messages.USERS_PER_PAGE,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=messages.build_users_list_message(users, page=page),
            parse_mode="HTML",
            reply_markup=build_pagination_keyboard("users", min(page, total_pages), total_pages),
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


# ───────────────────── pagination callback router ─────────────────────


async def handle_callback_query(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route inline-keyboard button taps.

    Only pagination callbacks (``p:<cmd>[:<arg>]:<page>``) are handled for
    now; ``noop`` is used by disabled/indicator buttons. Destructive
    approval callbacks land in Phase 7.
    """
    q = update.callback_query
    if q is None or q.data is None or q.message is None:
        return
    data = q.data

    # Disabled / indicator button — ack silently so Telegram clears the spinner.
    if data == "noop":
        await q.answer()
        return

    # Auth check up front — applies to every callback type below.
    tg = update.effective_user
    if tg is None:
        await q.answer()
        return
    user = await get_cached(tg.id)
    if not user or user.get("status") != "active":
        await q.answer("Not authorized.", show_alert=True)
        return
    await update_last_seen(tg.id)

    # Route: pagination (p:*)
    if data.startswith("p:"):
        await _handle_pagination_callback(q, data)
        return

    # Route: drill into a service discovered by /services (f:<repo>:<folder>)
    if data.startswith("f:"):
        await _handle_service_drill_callback(q, data)
        return

    # Unknown prefix — just dismiss the spinner.
    await q.answer()


async def _handle_pagination_callback(q: Any, data: str) -> None:
    parts = data.split(":", 3)
    if len(parts) != 4:
        await q.answer()
        return
    _, cmd, arg, page_str = parts
    try:
        page = max(1, int(page_str))
    except ValueError:
        await q.answer()
        return
    try:
        new_text, new_markup = await _render_page(cmd, arg, page)
    except Exception as e:  # noqa: BLE001
        log.warning("pagination.render_failed", cmd=cmd, arg=arg, page=page, error=str(e))
        await q.answer("Failed to render page.", show_alert=True)
        return
    if new_text is None:
        await q.answer("Nothing to show.")
        return
    await q.answer()
    try:
        await q.edit_message_text(text=new_text, parse_mode="HTML", reply_markup=new_markup)
    except Exception as e:  # noqa: BLE001
        log.debug("pagination.edit_noop", error=str(e))


async def _handle_service_drill_callback(q: Any, data: str) -> None:
    """Tap on a service button in /services → send /files output as a reply."""
    parts = data.split(":", 3)
    # Accept both the old 3-part (no branch) and new 4-part (with branch) forms
    # so in-flight keyboards from before this upgrade don't silently break.
    if len(parts) == 4:
        _, repo, folder, branch = parts
    elif len(parts) == 3:
        _, repo, folder = parts
        branch = None  # list_files will resolve the default branch
    else:
        await q.answer()
        return
    await q.answer(f"Checking {folder} ({branch or 'default'})…")
    try:
        result = await github_tools.list_files(repo=repo, branch=branch, path=folder)
    except ValueError as e:
        await q.message.reply_text(
            text=messages.build_error_message(str(e)),
            parse_mode="HTML",
        )
        return
    await q.message.reply_text(
        text=messages.build_files_message(result),
        parse_mode="HTML",
    )


async def _render_page(cmd: str, arg: str, page: int) -> tuple[str | None, Any | None]:
    """Re-fetch data for the paginated command and render the new page."""
    if cmd == "repos":
        result = await github_tools.list_repos()
        result["_page"] = page
        total_pages = max(
            1,
            (len(result.get("repos", [])) + messages.REPOS_PER_PAGE - 1) // messages.REPOS_PER_PAGE,
        )
        return (
            messages.build_repos_message(result),
            build_pagination_keyboard("repos", min(page, total_pages), total_pages),
        )

    if cmd == "br":
        # arg is the repo name
        try:
            result = await github_tools.list_branches(repo=arg)
        except ValueError:
            return None, None
        result["_page"] = page
        total_pages = max(
            1,
            (len(result.get("branches", [])) + messages.BRANCHES_PER_PAGE - 1)
            // messages.BRANCHES_PER_PAGE,
        )
        return (
            messages.build_branches_message(result),
            build_pagination_keyboard("br", min(page, total_pages), total_pages, extra_arg=arg),
        )

    if cmd == "users":
        users = await list_users()
        total_pages = max(
            1,
            (len(users) + messages.USERS_PER_PAGE - 1) // messages.USERS_PER_PAGE,
        )
        return (
            messages.build_users_list_message(users, page=page),
            build_pagination_keyboard("users", min(page, total_pages), total_pages),
        )

    if cmd == "prs":
        # arg is "repo|state"
        repo, _, state = arg.partition("|")
        state = state or "open"
        try:
            result = await github_tools.list_prs(repo=repo, state=state)
        except ValueError:
            return None, None
        result["_page"] = page
        total_pages = max(
            1,
            (len(result.get("prs", [])) + messages.PRS_PER_PAGE - 1) // messages.PRS_PER_PAGE,
        )
        return (
            messages.build_prs_message(result),
            build_pagination_keyboard("prs", min(page, total_pages), total_pages, extra_arg=arg),
        )

    # Unknown command code — ignore.
    return None, None


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
