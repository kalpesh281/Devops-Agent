"""Tool registry (§7.3).

Every agent-callable function registers itself via the `@tool(...)` decorator.
The LangGraph graph (Phase 6) dispatches by name against this `REGISTRY` — it
NEVER hardcodes a tool list. Add a tool = one decorator.

Tier resolution order (most authoritative first):
    1. `config/tool_tiers.yml` — admins can retier a tool without code change.
    2. `tier=` kwarg passed to the `@tool` decorator.
    3. Default `auto`.

Denylist (`denylist_containers` in the same YAML) is consulted by destructive
tools via `is_denied(target)` before they run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from utils.logger import get_logger

log = get_logger(__name__)

Tier = Literal["auto", "notify", "approval"]
_VALID_TIERS = ("auto", "notify", "approval")

_TIER_CONFIG_PATH = Path("config/tool_tiers.yml")


@dataclass
class ToolSpec:
    name: str
    func: Callable[..., Any]
    tier: Tier
    description: str
    schema: dict[str, Any] = field(default_factory=dict)


REGISTRY: dict[str, ToolSpec] = {}
_TIER_CONFIG: dict[str, Any] | None = None


def _load_tier_config() -> dict[str, Any]:
    global _TIER_CONFIG
    if _TIER_CONFIG is None:
        if _TIER_CONFIG_PATH.exists():
            with _TIER_CONFIG_PATH.open() as f:
                loaded = yaml.safe_load(f) or {}
        else:
            log.warning("tier_config.missing", path=str(_TIER_CONFIG_PATH))
            loaded = {}
        loaded.setdefault("tiers", {})
        loaded.setdefault("denylist_containers", [])
        _TIER_CONFIG = loaded
    return _TIER_CONFIG


def tool(
    name: str,
    description: str,
    tier: Tier = "auto",
    schema: dict[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register `func` in REGISTRY. YAML tier (if set) overrides decorator default."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        yaml_tier = _load_tier_config()["tiers"].get(name)
        if yaml_tier in _VALID_TIERS:
            resolved: Tier = cast(Tier, yaml_tier)
        else:
            resolved = tier
        REGISTRY[name] = ToolSpec(
            name=name,
            func=func,
            tier=resolved,
            description=description,
            schema=schema or {},
        )
        return func

    return decorator


def get_tier(name: str) -> Tier:
    """Return the tier for an already-registered tool. Raises KeyError if unknown."""
    if name not in REGISTRY:
        raise KeyError(f"Unknown tool: {name}")
    return REGISTRY[name].tier


def is_denied(target: str) -> bool:
    """True if `target` is in the denylist — destructive ops must check this."""
    denylist = _load_tier_config()["denylist_containers"]
    return target in denylist


def get_denylist() -> list[str]:
    """Return a copy of the denylist for introspection / UI display."""
    return list(_load_tier_config()["denylist_containers"])


def reset_registry() -> None:
    """Test helper — clear REGISTRY and force tier config reload on next access."""
    global _TIER_CONFIG
    REGISTRY.clear()
    _TIER_CONFIG = None
