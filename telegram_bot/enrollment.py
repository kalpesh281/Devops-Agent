"""Enrollment state machine — GitHub-org-gated self-enrollment (§14.2)."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Literal

from github import GithubException
from pymongo.errors import DuplicateKeyError
from telegram import Update
from telegram.ext import ContextTypes

from config.settings import settings
from telegram_bot import messages
from utils.github_cache import cache as gh_cache
from utils.logger import get_logger
from utils.mongo import get_db
from utils.user_registry import admin_telegram_ids, find_by_github_username, upsert_user

Role = Literal["member", "admin"]

log = get_logger(__name__)

# GitHub usernames: alphanumeric + hyphen; 1-39 chars; cannot start or end with hyphen.
_GH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,37}[a-zA-Z0-9]$|^[a-zA-Z0-9]$")


async def is_pending(telegram_id: int) -> bool:
    return (await get_db().pending_enrollments.find_one({"_id": telegram_id})) is not None


async def start_enrollment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return
    now = datetime.now(UTC)
    await get_db().pending_enrollments.update_one(
        {"_id": user.id},
        {
            "$set": {"awaiting": "github_username", "attempts": 0},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    await context.bot.send_message(
        chat_id=chat.id,
        text=messages.build_welcome_new_user(user.first_name),
        parse_mode="HTML",
    )
    log.info("enrollment.started", telegram_id=user.id)


async def _is_org_member(github_username: str) -> tuple[bool, bool]:
    """Returns (user_exists, is_member)."""

    def _check() -> tuple[bool, bool]:
        gh = gh_cache._client()
        org = gh.get_organization(settings.GITHUB_ORG)
        try:
            gh_user = gh.get_user(github_username)
        except GithubException as e:
            if e.status == 404:
                return False, False
            raise
        # PyGithub runtime accepts either user type; stub narrows to NamedUser only.
        return True, bool(org.has_in_members(gh_user))  # type: ignore[arg-type]

    return await asyncio.to_thread(_check)


async def handle_github_username_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user
    msg = update.message
    chat = update.effective_chat
    if user is None or msg is None or msg.text is None or chat is None:
        return

    text = msg.text.strip().lstrip("@")
    db = get_db()

    if not _GH_RE.match(text):
        await context.bot.send_message(
            chat_id=chat.id,
            text=messages.build_github_user_not_found(text),
            parse_mode="HTML",
        )
        await db.pending_enrollments.update_one({"_id": user.id}, {"$inc": {"attempts": 1}})
        return

    try:
        exists, is_member = await _is_org_member(text)
    except GithubException as e:
        log.error("enrollment.github_error", error=str(e))
        await context.bot.send_message(
            chat_id=chat.id,
            text=messages.build_error_message("GitHub API error — try again in a minute."),
            parse_mode="HTML",
        )
        return

    if not exists:
        await context.bot.send_message(
            chat_id=chat.id,
            text=messages.build_github_user_not_found(text),
            parse_mode="HTML",
        )
        await db.pending_enrollments.update_one({"_id": user.id}, {"$inc": {"attempts": 1}})
        return

    if not is_member:
        await context.bot.send_message(
            chat_id=chat.id,
            text=messages.build_enrollment_rejected(text),
            parse_mode="HTML",
        )
        await db.audit_log.insert_one(
            {
                "timestamp": datetime.now(UTC),
                "actor": f"telegram:{user.username or user.id}",
                "action": "enrollment_rejected",
                "target": text,
                "result": "not_in_org",
            }
        )
        await db.pending_enrollments.delete_one({"_id": user.id})
        return

    # Claim-jump check
    existing = await find_by_github_username(text)
    if existing and existing["_id"] != user.id:
        await context.bot.send_message(
            chat_id=chat.id,
            text=messages.build_claim_conflict(),
            parse_mode="HTML",
        )
        log.warning(
            "enrollment.claim_conflict",
            telegram_id=user.id,
            github_username=text,
            existing_telegram_id=existing["_id"],
        )
        return

    # Role decision: bootstrap admin via FIRST_ADMIN_TELEGRAM_ID
    role: Role = "admin" if user.id == settings.FIRST_ADMIN_TELEGRAM_ID else "member"

    try:
        enrolled = await upsert_user(
            telegram_id=user.id,
            telegram_username=user.username,
            telegram_first_name=user.first_name,
            github_username=text,
            role=role,
            enrolled_by="self",
        )
    except DuplicateKeyError:
        await context.bot.send_message(
            chat_id=chat.id,
            text=messages.build_claim_conflict(),
            parse_mode="HTML",
        )
        return

    await db.pending_enrollments.delete_one({"_id": user.id})

    await context.bot.send_message(
        chat_id=chat.id,
        text=messages.build_enrollment_success(text, role),
        parse_mode="HTML",
    )

    await db.audit_log.insert_one(
        {
            "timestamp": datetime.now(UTC),
            "actor": f"telegram:{user.username or user.id}",
            "action": "enrollment_success",
            "target": text,
            "role": role,
            "result": "success",
        }
    )

    # Notify other admins
    notify_text = messages.build_admin_enroll_notification(enrolled)
    for admin_id in admin_telegram_ids():
        if admin_id == user.id:
            continue
        try:
            await context.bot.send_message(chat_id=admin_id, text=notify_text, parse_mode="HTML")
        except Exception as e:
            log.warning("enrollment.admin_notify_failed", admin=admin_id, error=str(e))

    log.info(
        "enrollment.success",
        telegram_id=user.id,
        github_username=text,
        role=role,
    )
