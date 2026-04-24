"""HTML message builders for Telegram messages (§11).

Every data display follows the same visual grammar:

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Header      <b>{emoji} {title}</b>         ← theme-neutral pigment
   Subtitle    <i>{scope · count · hint}</i>  ← italic, theme-adapted
   Body        either a numbered list, a card stack, or a <pre> table
   Footer tip  <i>Tip: …</i>                  ← only when actionable
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Rationale:
  * <pre> blocks render monospace with a theme-adapted grey background —
    that's the best "table" we can get in Telegram.
  * Card-style items (bold title + indented italic metadata) scale better
    than multi-column tables on narrow screens.
  * Every empty-state explains WHY the list is empty and WHAT to do next.
"""

from __future__ import annotations

from html import escape
from typing import Any

from tabulate import tabulate

from config.settings import settings
from telegram_bot.colors import Colors
from telegram_bot.formatters import time_ago

# Page sizes per paginated command. Tuned so each page fits comfortably
# on a phone screen without cropping.
REPOS_PER_PAGE = 20
BRANCHES_PER_PAGE = 30
USERS_PER_PAGE = 15
PRS_PER_PAGE = 10


def _paginate(items: list[Any], page: int, per_page: int) -> tuple[list[Any], int, int]:
    """Return (slice, clamped_page, total_pages) for 1-indexed page numbers."""
    total = len(items)
    if total == 0:
        return [], 1, 1
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return items[start : start + per_page], page, total_pages


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
    rows = [
        ("Telegram", f"@{tg_handle}"),
        ("User ID", str(user["_id"])),
        ("GitHub", user.get("github_username", "—")),
        ("Role", user.get("role", "member")),
    ]
    width = max(len(k) for k, _ in rows)
    body = "\n".join(f"{k.ljust(width)}   {v}" for k, v in rows)
    return (
        "<b>🆕 New user enrolled</b>\n"
        "<i>GitHub org membership verified.</i>\n\n"
        f"<pre>{escape(body)}</pre>"
    )


# ────────── help / whoami / users ──────────


def build_help_message(role: str) -> str:
    brand = escape(settings.display_name())
    github_cmds = [
        ("/repos", f"list every repo in {brand}"),
        ("/branches &lt;repo&gt;", "branches on a repo"),
        ("/commits &lt;repo&gt; &lt;branch&gt;", "recent commits"),
        ("/prs &lt;repo&gt;", "open pull requests"),
        ("/files &lt;repo&gt; [path] [branch]", "deploy-readiness for a repo / folder"),
        ("/services &lt;repo&gt;", "find deployable services (single or monorepo)"),
        ("/refresh", "pull the latest from GitHub right now"),
    ]
    server_cmds = [
        ("/servers", "list deployment targets"),
        ("/status [server]", "running containers per server"),
        ("/disk &lt;server&gt;", "docker disk usage for a server"),
    ]
    account_cmds = [
        ("/whoami", "show your enrollment info"),
        ("/users", "who's on the team"),
    ]
    admin_cmds = [
        ("/users pending", "anyone mid-enrollment"),
        ("/users revoke &lt;handle&gt;", "remove someone's access"),
        ("/users promote &lt;handle&gt;", "make someone an admin"),
        ("/users reverify", "re-check every user's org membership now"),
    ]
    role_badge = "🟣 admin" if role == "admin" else "🔵 member"
    lines: list[str] = [
        "<b>📖 What I can do</b>",
        f"<i>You're signed in as {role_badge}.</i>",
        "",
        "<b>📦 GitHub</b>",
    ]
    for cmd, desc in github_cmds:
        lines.append(f"  <code>{cmd}</code> — {desc}")
    lines.append("")
    lines.append("<b>🖥 Servers &amp; Docker</b>")
    for cmd, desc in server_cmds:
        lines.append(f"  <code>{cmd}</code> — {desc}")
    lines.append("")
    lines.append("<b>👤 Account</b>")
    for cmd, desc in account_cmds:
        lines.append(f"  <code>{cmd}</code> — {desc}")
    if role == "admin":
        lines.append("")
        lines.append("<b>🛠 Admin</b>")
        for cmd, desc in admin_cmds:
            lines.append(f"  <code>{cmd}</code> — {desc}")
    lines.append("")
    lines.append("<i>Tip: anything empty or confusing usually has a /refresh fix.</i>")
    return "\n".join(lines)


def build_whoami_message(user: dict[str, Any]) -> str:
    tg_handle = user.get("telegram_username") or "—"
    rows = [
        ("Telegram", f"@{tg_handle}"),
        ("User ID", str(user["_id"])),
        ("GitHub", user.get("github_username") or "—"),
        ("Role", user.get("role", "member")),
        ("Status", user.get("status", "active")),
        (
            "Enrolled",
            time_ago(user["enrolled_at"]) if user.get("enrolled_at") else "—",
        ),
        (
            "Last seen",
            time_ago(user["last_seen"]) if user.get("last_seen") else "—",
        ),
    ]
    # Left-align labels to the longest one so values line up in the <pre>.
    width = max(len(k) for k, _ in rows)
    body = "\n".join(f"{k.ljust(width)}   {v}" for k, v in rows)
    role_badge = "🟣 admin" if user.get("role") == "admin" else "🔵 member"
    return f"<b>👤 Your enrollment</b>\n<i>{role_badge}</i>\n\n<pre>{escape(body)}</pre>"


def build_users_list_message(users: list[dict[str, Any]], page: int = 1) -> str:
    if not users:
        return (
            "<b>👥 No users enrolled yet.</b>\n\n"
            "<i>Share this bot with a teammate — they DM it, send their GitHub "
            "username, and get enrolled automatically if they're on the "
            f"{escape(settings.display_name())} GitHub org.</i>"
        )
    page_items, page, total_pages = _paginate(users, page, USERS_PER_PAGE)
    rows: list[list[str]] = []
    for u in page_items:
        tg = ("@" + u["telegram_username"]) if u.get("telegram_username") else str(u["_id"])
        role_icon = "🟣" if u.get("role") == "admin" else "🔵"
        status_icon = "●" if u.get("status") == "active" else "○"
        rows.append(
            [
                f"{role_icon} {tg}",
                u.get("github_username") or "—",
                u.get("role", "member"),
                f"{status_icon} {u.get('status', 'active')}",
                time_ago(u["last_seen"]) if u.get("last_seen") else "—",
            ]
        )
    table = tabulate(
        rows,
        headers=["Telegram", "GitHub", "Role", "Status", "Last seen"],
        tablefmt="simple",
    )
    admin_count = sum(1 for u in users if u.get("role") == "admin")
    scope = f"<i>{len(users)} enrolled · {admin_count} admin · page {page}/{total_pages}</i>"
    footer = "\n\n<i>Use the buttons below to page through the team.</i>" if total_pages > 1 else ""
    return f"<b>👥 Team</b>\n{scope}\n\n<pre>{escape(table)}</pre>{footer}"


# ────────── GitHub data ──────────


def build_repos_message(data: dict[str, Any]) -> str:
    repos: list[str] = data.get("repos", [])
    if not repos:
        return (
            f"<b>{Colors.WARNING} No repos in cache yet.</b>\n\n"
            "<i>I pull the list from GitHub every 5 minutes. If I just started "
            "up, the first fetch can take ~30 seconds. Try this:</i>\n\n"
            "  • <code>/refresh</code> — force a pull right now\n"
            "  • Wait a minute and retry <code>/repos</code>\n\n"
            "<i>Still empty? Double-check your <code>GITHUB_TOKEN</code> has "
            "<code>repo</code> + <code>read:org</code> scopes and SSO is "
            "authorized for the org.</i>"
        )
    page_items, page, total_pages = _paginate(repos, data.get("_page", 1), REPOS_PER_PAGE)
    # Continuous numbering across pages (23, 24, 25… on page 2).
    start_index = (page - 1) * REPOS_PER_PAGE + 1
    num_w = len(str(len(repos)))
    listing = "\n".join(
        f"  <code>{str(start_index + i).zfill(num_w)}</code>  {escape(r)}"
        for i, r in enumerate(page_items)
    )
    brand = escape(settings.display_name())
    scope = f"<i>{brand} · {len(repos)} total · page {page}/{total_pages}</i>"
    footer = (
        "\n\n<i>Tip: <code>/branches &lt;repo&gt;</code> to list branches, "
        "<code>/files &lt;repo&gt;</code> to inspect key files. "
        "Use the buttons below or <code>/repos 2</code> to page.</i>"
        if total_pages > 1
        else "\n\n<i>Tip: <code>/branches &lt;repo&gt;</code> to list branches, "
        "<code>/files &lt;repo&gt;</code> to inspect key files.</i>"
    )
    return f"<b>📚 Repositories</b>\n{scope}\n\n{listing}{footer}"


def build_branches_message(data: dict[str, Any]) -> str:
    repo = data["repo"]
    branches: list[str] = data.get("branches", [])
    if not branches:
        return (
            f"<b>{Colors.WARNING} No branches found for "
            f"<code>{escape(repo)}</code>.</b>\n\n"
            "<i>This usually means one of:</i>\n"
            "  • the repo name has a typo — see <code>/repos</code>\n"
            "  • the repo was just created and my cache is stale — try "
            "<code>/refresh</code>\n"
            "  • the repo is empty (no commits yet)"
        )
    page_items, page, total_pages = _paginate(branches, data.get("_page", 1), BRANCHES_PER_PAGE)
    start_index = (page - 1) * BRANCHES_PER_PAGE + 1
    num_w = len(str(len(branches)))
    listing = "\n".join(
        f"  <code>{str(start_index + i).zfill(num_w)}</code>  {escape(b)}"
        for i, b in enumerate(page_items)
    )
    scope = f"<i>{escape(repo)} · {len(branches)} total · page {page}/{total_pages}</i>"
    footer = (
        f"\n\n<i>Tip: <code>/commits {escape(repo)} &lt;branch&gt;</code> for recent commits. "
        f"Use the buttons below to page.</i>"
        if total_pages > 1
        else (
            f"\n\n<i>Tip: <code>/commits {escape(repo)} &lt;branch&gt;</code> "
            f"for recent commits.</i>"
        )
    )
    return f"<b>🌿 Branches</b>\n{scope}\n\n{listing}{footer}"


def build_commits_message(data: dict[str, Any]) -> str:
    commits = data.get("commits", [])
    repo = data.get("repo", "?")
    branch = data.get("branch", "?")
    if not commits:
        return (
            f"<b>{Colors.WARNING} No commits on "
            f"<code>{escape(repo)}/{escape(branch)}</code>.</b>\n\n"
            "<i>Could be a typo in the branch name. See what branches exist:</i>\n"
            f"  • <code>/branches {escape(repo)}</code>"
        )
    lines = [
        "<b>📜 Recent commits</b>",
        f"<i>{escape(repo)} · {escape(branch)} · {len(commits)} shown</i>",
        "",
    ]
    for c in commits:
        date = (c.get("date") or "")[:10]
        author = c.get("author") or "—"
        lines.append(f"  <code>{escape(c['sha'])}</code>  {escape(c['message'])}")
        lines.append(f"     <i>{escape(author)} · {escape(date)}</i>")
    return "\n".join(lines)


def build_prs_message(data: dict[str, Any]) -> str:
    prs = data.get("prs", [])
    repo = data["repo"]
    state = data.get("state", "open")
    if not prs:
        return (
            f"<b>🟢 No {escape(state)} PRs on <code>{escape(repo)}</code>.</b>\n\n"
            "<i>Looking for another state? Try:</i>\n"
            f"  • <code>/prs {escape(repo)} closed</code>\n"
            f"  • <code>/prs {escape(repo)} all</code>"
        )
    page_items, page, total_pages = _paginate(prs, data.get("_page", 1), PRS_PER_PAGE)
    lines = [
        "<b>🔀 Pull requests</b>",
        f"<i>{escape(repo)} · {escape(state)} · {len(prs)} total · page {page}/{total_pages}</i>",
        "",
    ]
    for p in page_items:
        author = p.get("author") or "—"
        branch = p.get("branch") or "—"
        lines.append(f"  <b>#{p['number']}</b>  {escape(p['title'])}")
        lines.append(f"      <i>by {escape(author)} · from {escape(branch)}</i>")
    if total_pages > 1:
        lines.append("")
        lines.append("<i>Use the buttons below to page through.</i>")
    return "\n".join(lines)


# Display labels for detected stacks (richer than the canonical key).
_STACK_LABEL: dict[str, str] = {
    "node": "Node.js",
    "python": "Python",
    "flutter": "Flutter",
    "gradle": "Gradle (Android / JVM)",
    "go": "Go",
    "rust": "Rust",
    "static": "Static site",
    "unknown": "Unknown",
}

# One-line description of what each stack usually deploys as.
_STACK_NOTE: dict[str, str] = {
    "node": "React / Next.js / React Native / Express — served by Docker",
    "python": "Flask / FastAPI / Django — served by Docker",
    "flutter": "mobile app (Docker deploy only if there's a server component)",
    "gradle": "Android / Kotlin / Java — Docker deploy only for backend services",
    "go": "served by Docker",
    "rust": "served by Docker",
    "static": "served by Docker (nginx / caddy)",
    "unknown": "no recognized marker file",
}


def build_files_message(data: dict[str, Any]) -> str:
    repo = escape(data["repo"])
    branch = escape(data["branch"])
    stack = data.get("stack", "unknown")
    marker = data.get("stack_marker")
    substack = data.get("substack")
    required = data.get("required", [])
    advisory = data.get("advisory", [])
    missing_required = data.get("missing_required", [])
    deploy_ready = data.get("deploy_ready", False)

    stack_label = _STACK_LABEL.get(stack, stack.title())
    if substack:
        stack_label = f"{stack_label} ({substack})"
    stack_note = _STACK_NOTE.get(stack, "")

    folder = data.get("path", ".")
    scope = f"{repo} · {branch}"
    if folder and folder != ".":
        scope += f" · <code>{escape(folder)}/</code>"

    lines = [
        "<b>📁 Deploy readiness</b>",
        f"<i>{scope}</i>",
        "",
    ]

    # ── Detected stack (informational, never blocks) ──────────────────
    stack_icon = "🟡" if stack == "unknown" else "🔵"
    lines.append(f"{stack_icon} <b>Stack:</b> {escape(stack_label)}")
    if marker:
        lines.append(f"     <i>via <code>{escape(marker)}</code> — {escape(stack_note)}</i>")
    else:
        lines.append(f"     <i>{escape(stack_note)}</i>")

    # ── Required bucket (only the TRUE blockers — deploy.config + Dockerfile) ──
    lines.append("")
    present_req = sum(1 for e in required if e["present"])
    lines.append(f"<b>🟢 Required ({present_req}/{len(required)})</b>")
    for e in required:
        path = escape(e["path"])
        if e["present"]:
            size = _fmt_bytes(int(e.get("size", 0) or 0))
            lines.append(f"  ✓ <code>{path}</code>  <i>{size}</i>")
        else:
            lines.append(f"  ✗ <code>{path}</code>  <i>{_missing_hint(e['path'])}</i>")

    # ── Advisory bucket ────────────────────────────────────────────────
    if advisory:
        lines.append("")
        present_adv = sum(1 for e in advisory if e["present"])
        lines.append(f"<b>🔘 Recommended ({present_adv}/{len(advisory)})</b>")
        for e in advisory:
            path = escape(e["path"])
            if e["present"]:
                size = _fmt_bytes(int(e.get("size", 0) or 0))
                lines.append(f"  ✓ <code>{path}</code>  <i>{size}</i>")
            else:
                lines.append(f"  ✗ <code>{path}</code>  <i>add to keep secrets out of images</i>")

    # ── Verdict ────────────────────────────────────────────────────────
    lines.append("")
    if deploy_ready:
        lines.append("<b>🟢 Deploy-ready</b>")
        lines.append(
            "<i>Both required files present. Phase 5 will wire up "
            "<code>/deploy &lt;repo&gt;</code>.</i>"
        )
    else:
        # Single-file missing is the headline; everything else is context.
        lines.append("<b>🔴 Not deploy-ready</b>")
        lines.append("<i>Missing:</i>")
        for p in missing_required:
            lines.append(f"  • <code>{escape(p)}</code>")
        if "deploy.config.yml" in missing_required:
            lines.append("")
            lines.append(
                "<i>Add a <code>deploy.config.yml</code> at this folder's "
                "root — see <code>folder_name/deploy.config.example.yml</code> "
                "for a template.</i>"
            )

    return "\n".join(lines)


def _missing_hint(path: str) -> str:
    """One-liner on why a missing blocker matters."""
    if path == "deploy.config.yml":
        return "the deploy manifest — defines name, port, target_server, image"
    if path == "Dockerfile":
        return "needed to build the container image"
    return ""


def build_services_message(data: dict[str, Any]) -> str:
    repo = escape(data["repo"])
    branch = escape(data["branch"])
    services = data.get("services", [])
    root_folders: list[str] = data.get("root_folders", [])
    root_files: list[str] = data.get("root_files", [])
    folders_with_config = set(data.get("folders_with_config", []))
    has_root_config = any(s["path"] == "." for s in services)

    lines = [
        "<b>🧩 Repo layout</b>",
        f"<i>{repo} · {branch} · {len(services)} service(s) found</i>",
        "",
    ]

    # Readiness verdict
    if has_root_config:
        lines.append("<b>🟢 Single-service repo — ready at root</b>")
        lines.append(f"  <i>Check readiness: <code>/files {repo}</code></i>")
    elif services:
        lines.append(f"<b>🟢 Deployable services ({len(services)})</b>")
        for s in services:
            path = s.get("path", ".")
            name = escape(s.get("name", "?"))
            location = "<i>repo root</i>" if path == "." else f"<code>{escape(path)}/</code>"
            lines.append(f"  ✓ <b>{name}</b>  <i>· {location}</i>")
    else:
        lines.append("<b>🔴 No deploy.config.yml found</b>")
        lines.append("<i>Nothing in this repo is deployable yet.</i>")

    # Folder layout — highlights which top-level folders hold a config
    if root_folders:
        lines.append("")
        lines.append("<b>📂 Top-level folders</b>")
        for folder in root_folders:
            if folder in folders_with_config:
                lines.append(f"  🟢 <code>{escape(folder)}/</code>  <i>has deploy.config.yml</i>")
            else:
                lines.append(f"  📁 <code>{escape(folder)}/</code>")

    if root_files:
        lines.append("")
        top = root_files[:10]
        listing = ", ".join(f"<code>{escape(f)}</code>" for f in top)
        extra = f" + {len(root_files) - 10} more" if len(root_files) > 10 else ""
        lines.append(f"<b>📄 Root files</b>  {listing}{extra}")

    lines.append("")
    if has_root_config or services:
        lines.append("<i>Tap a service below — no need to type the folder path.</i>")
    else:
        lines.append("<i>To make this repo deployable, add a <code>deploy.config.yml</code>:</i>")
        lines.append("  • <b>Single service?</b> Put it at the repo root.")
        lines.append(
            "  • <b>Monorepo?</b> Put one inside each deployable folder "
            "(e.g. <code>frontend/</code>, <code>backend/</code>)."
        )
        lines.append("<i>Template: <code>folder_name/deploy.config.example.yml</code></i>")
    return "\n".join(lines)


def build_refresh_result(data: dict[str, Any]) -> str:
    elapsed_ms = int(data.get("elapsed_ms", 0) or 0)
    took = f"{elapsed_ms / 1000:.1f}s" if elapsed_ms >= 1000 else f"{elapsed_ms} ms"
    rows = [
        ("Owner", data.get("owner", "—")),
        ("Kind", data.get("owner_kind") or "—"),
        ("Repo count", str(data.get("repo_count", 0))),
        ("Took", took),
    ]
    width = max(len(k) for k, _ in rows)
    body = "\n".join(f"{k.ljust(width)}   {v}" for k, v in rows)
    return (
        f"<b>🔄 Cache refreshed</b>\n"
        f"<i>You can now run /repos, /branches, etc. with fresh data.</i>\n\n"
        f"<pre>{escape(body)}</pre>"
    )


# ────────── servers / status / disk (Phase 4) ──────────


def build_servers_message(data: dict[str, Any]) -> str:
    servers = data.get("servers", [])
    if not servers:
        return (
            f"<b>{Colors.WARNING} No servers registered yet.</b>\n\n"
            "<i>Server registry is file-only — chat commands can't add servers "
            "(by design).</i>\n\n"
            "  1. Edit <code>secrets/servers.yml</code> (mode 600)\n"
            "  2. Restart the bot: <code>make dev</code>\n\n"
            "<i>See <code>config/servers.example.yml</code> for a template.</i>"
        )

    lines = [
        "<b>🖥 Deployment servers</b>",
        f"<i>{len(servers)} registered</i>",
        "",
    ]
    for s in servers:
        sid = s.get("id", "?")
        stype = s.get("type", "?")
        conn = s.get("connection", "?")
        host = s.get("host") or "local socket"
        labels = s.get("labels") or []

        conn_icon = "🔵" if conn == "local" else "🟣"
        lines.append(f"{conn_icon} <b>{escape(sid)}</b>")
        lines.append(f"     <i>{escape(stype)} · {escape(conn)} · {escape(host)}</i>")
        if labels:
            lines.append(f"     <i>labels: {escape(', '.join(labels))}</i>")
        lines.append("")
    lines.append(
        "<i>Tip: <code>/status</code> shows running containers, "
        "<code>/disk &lt;server&gt;</code> shows disk usage.</i>"
    )
    return "\n".join(lines).rstrip()


def build_status_message(data: dict[str, Any]) -> str:
    results = data.get("servers", [])
    if not results:
        return (
            f"<b>{Colors.WARNING} No servers to query.</b>\n\n"
            "<i>Register a server in <code>secrets/servers.yml</code>, then try "
            "<code>/servers</code> to confirm.</i>"
        )

    total = data.get("total_running", 0)
    scope_line = (
        f"<i>Server: <code>{escape(data['server_id'])}</code> · {total} running</i>"
        if data.get("server_id")
        else f"<i>{len(results)} server(s) · {total} running total</i>"
    )
    lines: list[str] = [
        "<b>📊 Status overview</b>",
        scope_line,
        "",
    ]

    for srv in results:
        sid = srv.get("server_id", "?")
        conn = srv.get("connection", "?")

        if not srv.get("ok"):
            err_short = (srv.get("error") or "unknown error")[:160]
            lines.append(f"{Colors.ERROR} <b>{escape(sid)}</b>  <i>· {escape(conn)}</i>")
            lines.append(f"     <i>daemon unreachable — {escape(err_short)}</i>")
            lines.append("     <i>Is Docker running? (<code>docker info</code> to check)</i>")
            lines.append("")
            continue

        containers = srv.get("containers", [])
        header_icon = Colors.SUCCESS if containers else Colors.MUTED
        lines.append(
            f"{header_icon} <b>{escape(sid)}</b>  "
            f"<i>· {escape(conn)} · {len(containers)} running</i>"
        )
        if not containers:
            lines.append(
                "     <i>No containers running. Phase 5 adds "
                "<code>/deploy</code> to put something up.</i>"
            )
            lines.append("")
            continue

        rows = [
            [
                _container_status_icon(c.get("status", "")) + " " + c.get("name", ""),
                c.get("status", ""),
                c.get("image", ""),
            ]
            for c in containers
        ]
        table = tabulate(
            rows,
            headers=["Name", "Status", "Image"],
            tablefmt="simple",
        )
        lines.append(f"<pre>{escape(table)}</pre>")
    return "\n".join(lines).rstrip()


def _container_status_icon(status: str) -> str:
    """Map a docker container status to a theme-safe emoji."""
    s = (status or "").lower()
    if s == "running":
        return "🟢"
    if s in ("paused", "restarting"):
        return "🟡"
    if s in ("exited", "dead"):
        return "🔴"
    return "🔘"


def _fmt_bytes(n: int) -> str:
    """Human-friendly byte count (binary units — matches docker's own output)."""
    x = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if x < 1024:
            return f"{x:.1f} {unit}"
        x /= 1024
    return f"{x:.1f} PiB"


def build_disk_message(data: dict[str, Any]) -> str:
    sid = data.get("server_id", "?")
    conn = data.get("connection", "?")

    images_sz = int(data.get("images_size_bytes", 0) or 0)
    containers_sz = int(data.get("containers_size_bytes", 0) or 0)
    volumes_sz = int(data.get("volumes_size_bytes", 0) or 0)
    builder_sz = int(data.get("builder_cache_bytes", 0) or 0)
    layers_sz = int(data.get("layers_size_bytes", 0) or 0)
    total_sz = images_sz + containers_sz + volumes_sz + builder_sz

    rows: list[list[str]] = [
        [
            "🖼  Images",
            str(data.get("images_total", 0)),
            _fmt_bytes(images_sz),
        ],
        [
            "📦 Containers",
            str(data.get("containers_total", 0)),
            _fmt_bytes(containers_sz),
        ],
        [
            "💽 Volumes",
            str(data.get("volumes_total", 0)),
            _fmt_bytes(volumes_sz),
        ],
        ["🧱 Build cache", "—", _fmt_bytes(builder_sz)],
        ["📚 Layers total", "—", _fmt_bytes(layers_sz)],
    ]
    table = tabulate(rows, headers=["Kind", "Count", "Size"], tablefmt="simple")
    return (
        f"<b>💾 Docker disk usage</b>\n"
        f"<i>Server: <code>{escape(sid)}</code> · {escape(conn)} · "
        f"~{_fmt_bytes(total_sz)} total</i>\n\n"
        f"<pre>{escape(table)}</pre>\n"
        f"<i>Tip: Phase 7 will add <code>/cleanup &lt;server&gt;</code> to "
        f"reclaim unused image space.</i>"
    )


def build_error_message(err: str) -> str:
    return f"<b>{Colors.ERROR} Error</b>\n\n<code>{escape(err)}</code>"


def build_did_you_mean_message(query: str, suggestions: list[tuple[str, float]]) -> str:
    if not suggestions:
        return (
            f"<b>{Colors.WARNING} No match for <code>{escape(query)}</code>.</b>\n\n"
            "<i>Try one of:</i>\n"
            "  • <code>/repos</code> — see every repo\n"
            "  • <code>/servers</code> — see every deployment target\n"
            "  • <code>/refresh</code> — re-fetch from GitHub"
        )
    items = "\n".join(f"  • <code>{escape(m)}</code>" for m, _ in suggestions)
    return (
        f"<b>{Colors.WARNING} No exact match for <code>{escape(query)}</code>.</b>\n"
        f"<i>Closest matches I know of:</i>\n\n"
        f"{items}"
    )
