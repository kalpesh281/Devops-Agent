"""Tests for the `@tool` decorator, tier resolution, and denylist."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Each test gets its own cwd + its own tool_tiers.yml."""
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "tool_tiers.yml").write_text(
        yaml.safe_dump(
            {
                "tiers": {
                    "cache_tool": "auto",
                    "deploy_tool": "notify",
                    "stop_tool": "approval",
                },
                "denylist_containers": ["mongo", "agent", "traefik"],
            }
        )
    )
    from tools import registry

    registry.reset_registry()
    yield tmp_path
    registry.reset_registry()


def test_decorator_registers_with_explicit_tier() -> None:
    from tools.registry import REGISTRY, tool

    @tool(name="foo", tier="auto", description="d", schema={"type": "object"})
    def f() -> None: ...

    assert "foo" in REGISTRY
    assert REGISTRY["foo"].tier == "auto"
    assert REGISTRY["foo"].description == "d"


def test_yaml_tier_overrides_decorator() -> None:
    from tools.registry import get_tier, tool

    # YAML says cache_tool is auto. If code passes tier="approval",
    # the YAML value wins.
    @tool(name="cache_tool", tier="approval", description="d", schema={})
    def f() -> None: ...

    assert get_tier("cache_tool") == "auto"


def test_get_tier_falls_back_to_registry_when_yaml_silent() -> None:
    from tools.registry import get_tier, tool

    @tool(name="only_in_code", tier="notify", description="d", schema={})
    def f() -> None: ...

    assert get_tier("only_in_code") == "notify"


def test_unknown_tool_raises() -> None:
    from tools.registry import get_tier

    with pytest.raises(KeyError):
        get_tier("nonexistent_tool")


def test_denylist_enforced() -> None:
    from tools.registry import get_denylist, is_denied

    assert is_denied("mongo")
    assert is_denied("agent")
    assert is_denied("traefik")
    assert not is_denied("trading-dashboard")
    assert set(get_denylist()) == {"mongo", "agent", "traefik"}


def test_registry_survives_reset() -> None:
    from tools.registry import REGISTRY, reset_registry, tool

    @tool(name="foo", tier="auto", description="d", schema={})
    def f() -> None: ...

    assert "foo" in REGISTRY
    reset_registry()
    assert "foo" not in REGISTRY
