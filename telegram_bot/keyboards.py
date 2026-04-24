"""InlineKeyboardMarkup builders (§10.4).

Phase 3 added the confirm keyboard. Phase 4+ adds pagination keyboards for
long lists (`/repos`, `/branches`, `/users`). Most other keyboards come
online in Phases 5 (deploy progress), 7 (HITL approvals), and 8
(logs/report navigation).

### Pagination callback-data format

    p:<cmd>:<arg?>:<page>

Examples:
    p:repos:2              → page 2 of /repos
    p:users:3              → page 3 of /users
    p:br:trading-app:2     → page 2 of /branches trading-app

### Service-drill callback-data format

    f:<repo>:<folder>:<branch>

Examples:
    f:GabbyAI:frontend:main     → run /files GabbyAI frontend (main branch)
    f:GabbyAI:.:develop         → run /files GabbyAI on develop (repo root)

Telegram limits ``callback_data`` to 64 bytes. Command + page always fits;
for ``/branches`` we prefix-truncate the repo portion to stay under the cap.
A "noop" data value parks the middle label button so it does nothing when
tapped.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ``callback_data`` max length (bytes) per Telegram Bot API.
_CB_MAX = 64
_NOOP = "noop"


def build_confirm_keyboard(action: str, target: str) -> InlineKeyboardMarkup:
    """Used by `/branches trding` → 'did you mean trading?' flow in later phases."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes", callback_data=f"{action}:{target}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
            ]
        ]
    )


def build_pagination_keyboard(
    cmd: str,
    page: int,
    total_pages: int,
    extra_arg: str | None = None,
) -> InlineKeyboardMarkup | None:
    """« Prev · Page N/M · Next » row for a paginated list.

    Returns None when ``total_pages <= 1`` (nothing to paginate). The label
    button in the middle carries `noop` callback data and acts as a static
    indicator.
    """
    if total_pages <= 1:
        return None

    def _pack(page_num: int) -> str:
        # Pack into p:<cmd>[:<arg>]:<page>, truncating the arg if needed so
        # the total encoding fits in 64 bytes.
        base = f"p:{cmd}::{page_num}" if extra_arg is None else f"p:{cmd}:{extra_arg}:{page_num}"
        if len(base.encode()) <= _CB_MAX:
            return base
        if extra_arg is None:
            # Shouldn't happen — cmd + page is always tiny. Fall back to noop.
            return _NOOP
        # Shorten the arg while keeping the prefix so the router still recognises it.
        budget = _CB_MAX - len(f"p:{cmd}::{page_num}".encode())
        shortened = extra_arg.encode()[: max(0, budget)].decode(errors="ignore")
        return f"p:{cmd}:{shortened}:{page_num}"

    prev_cb = _pack(page - 1) if page > 1 else _NOOP
    next_cb = _pack(page + 1) if page < total_pages else _NOOP

    row = [
        InlineKeyboardButton(
            "‹ Prev" if page > 1 else "·",
            callback_data=prev_cb,
        ),
        InlineKeyboardButton(
            f"Page {page}/{total_pages}",
            callback_data=_NOOP,
        ),
        InlineKeyboardButton(
            "Next ›" if page < total_pages else "·",
            callback_data=next_cb,
        ),
    ]
    return InlineKeyboardMarkup([row])


def build_services_keyboard(
    repo: str, services: list[dict[str, str]], branch: str
) -> InlineKeyboardMarkup | None:
    """One tap-to-check button per discovered service.

    Each button carries ``f:<repo>:<folder>:<branch>`` so the callback
    handler can re-run ``/files`` for that exact path + branch without the
    user typing anything. Buttons are laid out two per row so they fit
    comfortably on a phone screen.
    """
    if not services:
        return None

    buttons: list[InlineKeyboardButton] = []
    for s in services:
        folder = s.get("path", ".")
        name = s.get("name", folder)
        label = f"📁 {name}" if folder == "." else f"📂 {name}"
        data = f"f:{repo}:{folder}:{branch}"
        if len(data.encode()) > _CB_MAX:
            # Too long — skip this button; the user can still type the path.
            continue
        buttons.append(InlineKeyboardButton(label, callback_data=data))

    if not buttons:
        return None

    # Two per row.
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)
