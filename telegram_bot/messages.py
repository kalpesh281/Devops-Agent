"""HTML message builders for Telegram messages (§11)."""

from __future__ import annotations

from html import escape
from typing import Any

from tabulate import tabulate

from config.settings import settings
from telegram_bot.colors import Colors
from telegram_bot.formatters import time_ago

# ────────── enrollment ──────────


def build_welcome_new_user(first_name: str | None) -> str:
    name = escape(first_name or "there")
    brand = escape(settings.display_name())
    return (
        f"<b>👋 Hey {name}, nice to meet you!</b>\n\n"
        f"I'm your DevOps buddy for the <b>{brand}</b> team — I handle deploys, "
        f"rollbacks, logs, and all the boring bits so you don't have to SSH around.\n\n"
        f"Before we get going, could you share your <b>GitHub username</b>? "
        f"Just the handle, like <code>alicegithub</code> — the one in your "
        f"<code>github.com/&lt;your-handle&gt;</code> URL.\n\n"
        f"Send it over and I'll make sure you're on the team ✨"
    )


def build_enrollment_success(github_username: str, role: str) -> str:
    brand = escape(settings.display_name())
    role_line = (
        "You're set up as an <b>admin</b>, so you can pretty much do anything."
        if role == "admin"
        else f"You're in as a <b>{escape(role)}</b>. Welcome aboard."
    )
    return (
        f"<b>{Colors.SUCCESS} You're in!</b>\n\n"
        f"Found <code>{escape(github_username)}</code> on the {brand} team. "
        f"{role_line}\n\n"
        f"Try <code>/help</code> to see what I can do, or jump right in with "
        f"<code>/repos</code>."
    )


def build_enrollment_rejected(github_username: str) -> str:
    brand = escape(settings.display_name())
    return (
        f"<b>{Colors.ERROR} Hmm, I couldn't let you in.</b>\n\n"
        f"I don't see <code>{escape(github_username)}</code> on the {brand} "
        f"GitHub org. If you should be on the team, ping an admin to add you — "
        f"then come back and send <code>/start</code> again. I'll be here 👋"
    )


def build_github_user_not_found(github_username: str) -> str:
    return (
        f"<b>{Colors.WARNING} Couldn't find that one.</b>\n\n"
        f"There's no GitHub account called <code>{escape(github_username)}</code>. "
        f"Typo maybe? Double-check and send it again."
    )


def build_claim_conflict() -> str:
    return (
        f"<b>{Colors.ERROR} Wait, something's off.</b>\n\n"
        f"Someone already linked that GitHub account to a different Telegram. "
        f"If that's not supposed to happen, give an admin a heads-up."
    )


def build_revoked_message() -> str:
    return (
        f"<b>{Colors.ERROR} Heads up — your access was revoked.</b>\n\n"
        f"Not sure what happened on your end, but you'll need an admin to bring "
        f"you back in. Reach out to them if you think it's a mistake."
    )


def build_admin_only_message() -> str:
    return (
        f"<b>{Colors.ERROR} Nope — that one's admin-only.</b>\n\n"
        f"You'd need <code>role=admin</code> to run this. Ask an admin if you "
        f"think you should have it."
    )


def build_admin_enroll_notification(user: dict[str, Any]) -> str:
    tg_handle = user.get("telegram_username") or str(user["_id"])
    return (
        f"<b>🆕 New user enrolled</b>\n\n"
        f"Telegram: @{escape(tg_handle)} (<code>{user['_id']}</code>)\n"
        f"GitHub:   <code>{escape(user['github_username'])}</code>\n"
        f"Role:     <code>{escape(user.get('role', 'member'))}</code>"
    )


# ────────── help / whoami / users ──────────


def build_help_message(role: str) -> str:
    brand = escape(settings.display_name())
    user_cmds = [
        ("/repos", f"show you all the repos in {brand}"),
        ("/branches &lt;repo&gt;", "list branches on a repo"),
        ("/commits &lt;repo&gt; &lt;branch&gt;", "show recent commits"),
        ("/prs &lt;repo&gt;", "open pull requests"),
        ("/files &lt;repo&gt; &lt;branch&gt;", "check which key files exist"),
        ("/refresh", "refresh my cache right now"),
        ("/whoami", "show your enrollment info"),
        ("/users", "who's on the team"),
    ]
    admin_cmds = [
        ("/users pending", "anyone mid-enrollment"),
        ("/users revoke &lt;handle&gt;", "remove someone's access"),
        ("/users promote &lt;handle&gt;", "make someone an admin"),
        ("/users reverify", "re-check every user's org membership now"),
    ]
    lines = ["<b>📖 Here's what I can do:</b>"]
    for cmd, desc in user_cmds:
        lines.append(f"  <code>{cmd}</code> — {desc}")
    if role == "admin":
        lines.append("")
        lines.append("<b>🛠 Admin stuff (just for you):</b>")
        for cmd, desc in admin_cmds:
            lines.append(f"  <code>{cmd}</code> — {desc}")
    return "\n".join(lines)


def build_whoami_message(user: dict[str, Any]) -> str:
    tg = user.get("telegram_username") or "-"
    return (
        f"<b>👤 Your enrollment</b>\n\n"
        f"Telegram: @{escape(tg)} (<code>{user['_id']}</code>)\n"
        f"GitHub:   <code>{escape(user.get('github_username') or '-')}</code>\n"
        f"Role:     <code>{escape(user.get('role', 'member'))}</code>\n"
        f"Status:   <code>{escape(user.get('status', 'active'))}</code>\n"
        f"Enrolled: {time_ago(user['enrolled_at']) if user.get('enrolled_at') else '-'}\n"
        f"Last seen: {time_ago(user['last_seen']) if user.get('last_seen') else '-'}"
    )


def build_users_list_message(users: list[dict[str, Any]]) -> str:
    if not users:
        return "<i>No users enrolled yet.</i>"
    rows: list[list[str]] = []
    for u in users:
        tg = ("@" + u["telegram_username"]) if u.get("telegram_username") else str(u["_id"])
        rows.append(
            [
                tg,
                u.get("github_username") or "-",
                u.get("role", "member"),
                u.get("status", "active"),
                time_ago(u["last_seen"]) if u.get("last_seen") else "—",
            ]
        )
    table = tabulate(
        rows,
        headers=["Telegram", "GitHub", "Role", "Status", "Last seen"],
        tablefmt="simple",
    )
    return f"<b>Users ({len(users)})</b>\n<pre>{escape(table)}</pre>"


# ────────── GitHub data ──────────


def build_repos_message(data: dict[str, Any]) -> str:
    repos: list[str] = data.get("repos", [])
    if not repos:
        return f"{Colors.WARNING} No repos in cache yet. Try /refresh in a moment."
    top = repos[:20]
    listing = "\n".join(f"  • <code>{escape(r)}</code>" for r in top)
    more = f"\n<i>… and {len(repos) - 20} more</i>" if len(repos) > 20 else ""
    brand = escape(settings.display_name())
    return f"<b>📚 Repos in {brand}</b> (<code>{len(repos)}</code> total)\n\n{listing}{more}"


def build_branches_message(data: dict[str, Any]) -> str:
    repo = data["repo"]
    branches: list[str] = data.get("branches", [])
    if not branches:
        return f"{Colors.WARNING} No branches for <code>{escape(repo)}</code>."
    listing = "\n".join(f"  • <code>{escape(b)}</code>" for b in branches[:30])
    more = f"\n<i>… and {len(branches) - 30} more</i>" if len(branches) > 30 else ""
    return f"<b>🌿 Branches of {escape(repo)}</b> ({len(branches)})\n\n{listing}{more}"


def build_commits_message(data: dict[str, Any]) -> str:
    commits = data.get("commits", [])
    if not commits:
        return f"{Colors.WARNING} No commits found."
    lines = [f"<b>📜 Commits — {escape(data['repo'])}/{escape(data['branch'])}</b>", ""]
    for c in commits:
        date = (c.get("date") or "")[:10]
        lines.append(f"  <code>{escape(c['sha'])}</code>  {escape(c['message'])}")
        lines.append(f"    <i>{escape(c.get('author') or '')} · {escape(date)}</i>")
    return "\n".join(lines)


def build_prs_message(data: dict[str, Any]) -> str:
    prs = data.get("prs", [])
    repo = data["repo"]
    if not prs:
        return f"<i>No {escape(data.get('state', 'open'))} PRs on <code>{escape(repo)}</code>.</i>"
    lines = [f"<b>🔀 PRs — {escape(repo)}</b> ({data.get('state')}, {len(prs)})", ""]
    for p in prs:
        lines.append(f"  #{p['number']}  {escape(p['title'])}")
        lines.append(
            f"    <i>by {escape(p.get('author') or '')} · {escape(p.get('branch') or '')}</i>"
        )
    return "\n".join(lines)


def build_files_message(data: dict[str, Any]) -> str:
    repo = data["repo"]
    branch = data["branch"]
    present = data.get("present", [])
    missing = data.get("missing", [])
    lines = [f"<b>📁 Key files — {escape(repo)}/{escape(branch)}</b>", ""]
    if present:
        lines.append(f"<b>{Colors.SUCCESS} Present</b>")
        for f in present:
            lines.append(f"  • <code>{escape(f['path'])}</code> ({f.get('size', 0)} B)")
    if missing:
        lines.append(f"\n<b>{Colors.MUTED} Missing</b>")
        for p in missing:
            lines.append(f"  • <code>{escape(p)}</code>")
    return "\n".join(lines)


def build_refresh_result(data: dict[str, Any]) -> str:
    return (
        f"<b>🔄 Cache refreshed</b>\n\n"
        f"Owner:      <code>{escape(data.get('owner', ''))}</code>\n"
        f"Kind:       <code>{escape(data.get('owner_kind') or '-')}</code>\n"
        f"Repo count: <b>{data.get('repo_count', 0)}</b>\n"
        f"Took:       <code>{data.get('elapsed_ms', 0)} ms</code>"
    )


def build_error_message(err: str) -> str:
    return f"<b>{Colors.ERROR} Error</b>\n\n<code>{escape(err)}</code>"


def build_did_you_mean_message(query: str, suggestions: list[tuple[str, float]]) -> str:
    if not suggestions:
        return f"{Colors.WARNING} No match for <code>{escape(query)}</code>."
    items = "\n".join(f"  • <code>{escape(m)}</code>" for m, _ in suggestions)
    return (
        f"<b>{Colors.WARNING} No exact match for <code>{escape(query)}</code>.</b>\n"
        f"Did you mean:\n{items}"
    )
