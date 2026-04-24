"""Theme-safe styling for Telegram bot messages (§11.1).

Telegram HTML has NO color attribute, and the Bot API does not expose the
user's theme. So we cannot ship separate dark/light palettes or color any
tag. Every client renders tags using its own theme. The best we can do is:

  1. Pick glyphs/tags that stay readable on BOTH dark and light themes.
  2. Use them consistently so the bot looks polished on any theme, any client.

This module is the single source of truth for both. It exports:

  * ``Colors`` — emoji palette (theme-independent pigment).
  * Style helpers (``h``, ``dim``, ``kbd``, ``block``, ``quote``, ``ok``,
    ``warn``, ``err``, ``info``) — wrap text in the right HTML tag for its
    role, so every message follows the same visual grammar.

─────────────────────────── Style guide ───────────────────────────

Headers (primary)        →  <b>🎯 Title</b>              use  h(text, emoji)
Section / sub-header     →  <b>Subtitle</b>               use  h(text)
Muted / secondary text   →  <i>last seen 5m ago</i>       use  dim(text)
Identifier / command     →  <code>repo-name</code>        use  kbd(text)
Multi-line block (table, →  <pre>…</pre>                  use  block(text)
    log, tree)
Quoted reference         →  <blockquote>…</blockquote>    use  quote(text)
Success status line      →  🟢 <b>Deployed</b>            use  ok(text)
Warning status line      →  🟡 <b>Stale cache</b>         use  warn(text)
Error status line        →  🔴 <b>Failed</b>              use  err(text)
Info status line         →  🔵 <b>Heads up</b>            use  info(text)

Rules enforced by this module:

  * NEVER use ⚪ (invisible on light theme) or ⚫ (invisible on dark theme)
    as a status glyph.
  * Use <code> for SHORT identifiers only (repo, handle, sha, path). For
    multi-line output use <pre>; for prose emphasis use <b>/<i>.
  * Status cues are carried by colored emoji, not by text color — we can't
    set text color, but emoji pigment survives every theme.
  * Don't nest <code> inside <b> — Telegram renders it inconsistently across
    clients. Pick one.
  * All caller-supplied content going into any helper MUST already be HTML-
    escaped (``html.escape``). These helpers do NOT escape for you, so that
    callers can intentionally nest tags (e.g. kbd inside a sentence).
"""

from __future__ import annotations


class Colors:
    """Emoji pigments — each renders with its own color on every theme.

    Avoid ⚪ / ⚫ — they disappear on matching backgrounds. Use ``MUTED``
    (🔘, dark ring) or ``BULLET`` (•, inherits theme text color) instead.
    """

    SUCCESS = "🟢"
    WARNING = "🟡"
    ORANGE = "🟠"
    ERROR = "🔴"
    INFO = "🔵"
    AI = "🟣"
    MUTED = "🔘"
    BULLET = "•"


# ────────── Tag helpers (theme-safe HTML wrappers) ──────────


def h(text: str, emoji: str | None = None) -> str:
    """Header / section title. Bold, optionally prefixed with a colored emoji.

    Emoji pigment gives the header its visual weight on both themes (the
    <b> tag only changes weight, not color).
    """
    return f"<b>{emoji} {text}</b>" if emoji else f"<b>{text}</b>"


def dim(text: str) -> str:
    """Secondary / muted text. Italic — the client dims italic automatically
    on whichever theme is active, so readability stays intact on both.
    """
    return f"<i>{text}</i>"


def kbd(text: str) -> str:
    """Short inline identifier (repo, handle, sha, path, command).

    Rendered as monospace with a subtle grey background. Telegram adjusts
    the background shade per theme, so contrast stays clean on dark + light.
    Keep content SHORT — long inline <code> wraps awkwardly on narrow screens.
    """
    return f"<code>{text}</code>"


def block(text: str) -> str:
    """Multi-line code / table / log block. Monospace, theme-aware background.

    Prefer this over long <code> when the content spans multiple lines.
    """
    return f"<pre>{text}</pre>"


def quote(text: str) -> str:
    """Quoted reference block — renders with a theme-aware grey left bar.

    Good for echoing a user's input, a tool's output snippet, or a warning
    you want visually separated from the rest of the message.
    """
    return f"<blockquote>{text}</blockquote>"


# ────────── Status-line helpers (emoji + bold) ──────────


def ok(text: str) -> str:
    """Success line — green circle + bold. Theme-neutral."""
    return f"{Colors.SUCCESS} <b>{text}</b>"


def warn(text: str) -> str:
    """Warning line — yellow circle + bold. Theme-neutral."""
    return f"{Colors.WARNING} <b>{text}</b>"


def err(text: str) -> str:
    """Error line — red circle + bold. Theme-neutral."""
    return f"{Colors.ERROR} <b>{text}</b>"


def info(text: str) -> str:
    """Info line — blue circle + bold. Theme-neutral."""
    return f"{Colors.INFO} <b>{text}</b>"


__all__ = [
    "Colors",
    "h",
    "dim",
    "kbd",
    "block",
    "quote",
    "ok",
    "warn",
    "err",
    "info",
]
