"""Unit tests for config/deploy_config_schema.py (spec §14.4)."""

from __future__ import annotations

from pydantic import ValidationError

from config.deploy_config_schema import (
    DeployConfig,
    ResourceLimits,
    validate_yaml,
)

VALID_YAML = """
name: trading-dashboard
project: acme
stack: node
port: 3000
target_server: physical-main
docker_hub:
  image: kalpesh281/trading-dashboard
env_required:
  - API_KEY
  - MONGO_URI
healthcheck: /health
resources:
  memory: 512m
  cpus: "1.0"
"""


def test_valid_yaml_roundtrips() -> None:
    cfg, err = validate_yaml(VALID_YAML)
    assert err is None
    assert cfg is not None
    assert cfg.name == "trading-dashboard"
    assert cfg.stack == "node"
    assert cfg.port == 3000
    assert cfg.docker_hub.image == "kalpesh281/trading-dashboard"
    assert cfg.env_required == ["API_KEY", "MONGO_URI"]
    assert cfg.resources.memory == "512m"


def test_minimal_valid_yaml_uses_defaults() -> None:
    cfg, err = validate_yaml(
        """
        name: x
        stack: python
        port: 8000
        target_server: t
        docker_hub:
          image: me/x
        """
    )
    assert err is None
    assert cfg is not None
    assert cfg.project == "internal"
    assert cfg.build == "docker"
    assert cfg.healthcheck == "/health"
    assert isinstance(cfg.resources, ResourceLimits)


def test_extra_field_rejected_with_did_you_mean() -> None:
    # typo: target_sever (missing "r") — should be target_server.
    _, err = validate_yaml(
        """
        name: x
        stack: node
        port: 3000
        target_sever: physical-main
        docker_hub:
          image: me/x
        """
    )
    assert err is not None
    assert "target_sever" in err
    assert "did you mean" in err
    assert "target_server" in err


def test_missing_required_field() -> None:
    _, err = validate_yaml(
        """
        name: x
        stack: node
        port: 3000
        docker_hub:
          image: me/x
        """
    )
    assert err is not None
    assert "target_server" in err


def test_invalid_stack_literal() -> None:
    _, err = validate_yaml(
        """
        name: x
        stack: ruby
        port: 3000
        target_server: t
        docker_hub:
          image: me/x
        """
    )
    assert err is not None
    assert "stack" in err


def test_port_out_of_range_rejected() -> None:
    _, err = validate_yaml(
        """
        name: x
        stack: node
        port: 99999
        target_server: t
        docker_hub:
          image: me/x
        """
    )
    assert err is not None
    assert "port" in err


def test_yaml_syntax_error_surfaces() -> None:
    _, err = validate_yaml("name: x\n  : : :")
    assert err is not None
    assert "YAML" in err or "yaml" in err.lower()


def test_nested_docker_hub_strict() -> None:
    # Nested DockerHubConfig also forbids unknown fields.
    try:
        DeployConfig.model_validate(
            {
                "name": "x",
                "stack": "node",
                "port": 3000,
                "target_server": "t",
                "docker_hub": {"image": "me/x", "tag": "latest"},  # `tag` is unknown
            }
        )
    except ValidationError as e:
        assert any(err["type"] == "extra_forbidden" for err in e.errors())
    else:
        raise AssertionError("expected extra_forbidden on nested docker_hub.tag")


def test_validate_yaml_rejects_non_mapping_root() -> None:
    _, err = validate_yaml("- just: a list")
    assert err is not None
    assert "mapping" in err.lower()
