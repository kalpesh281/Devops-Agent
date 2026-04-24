"""Small format helpers — uptime, byte sizes, relative time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def format_uptime(seconds: float) -> str:
    s = int(seconds)
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes, s = divmod(s, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and not days:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def format_size_mb(bytes_value: int) -> str:
    mb = bytes_value / (1024 * 1024)
    if mb < 1:
        return f"{bytes_value / 1024:.1f} KB"
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.1f} GB"


def time_ago(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - dt
    if delta < timedelta(seconds=60):
        return "just now"
    if delta < timedelta(minutes=60):
        return f"{int(delta.total_seconds() // 60)}m ago"
    if delta < timedelta(hours=24):
        return f"{int(delta.total_seconds() // 3600)}h ago"
    if delta < timedelta(days=30):
        return f"{delta.days}d ago"
    return dt.strftime("%Y-%m-%d")
