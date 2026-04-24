"""Unit tests for utils/server_registry.py (spec §5.1, §20).

Mongo is faked with mongomock-motor so these tests run offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient

from utils.server_registry import (
    ServerConfig,
    ServerConfigError,
    get_server,
    list_servers,
    load_servers_yml,
    sync_to_mongo,
)

# ────────── ServerConfig model ──────────


def test_local_server_needs_no_ssh_fields() -> None:
    sc = ServerConfig(id="physical-main", type="physical", connection="local")
    assert sc.host is None
    assert sc.pem_path() is None
    assert sc.docker_base_url() is None


def test_ssh_server_requires_host_user_pem() -> None:
    with pytest.raises(ValueError, match="connection: ssh requires"):
        ServerConfig(id="x", type="ec2", connection="ssh")


def test_ssh_server_valid() -> None:
    sc = ServerConfig(
        id="acme",
        type="ec2",
        connection="ssh",
        host="example.com",
        ssh_user="ubuntu",
        pem="acme",
    )
    assert sc.docker_base_url() == "ssh://ubuntu@example.com"
    # pem_path composes PEM_DIR + <pem>.pem
    assert sc.pem_path() is not None
    assert str(sc.pem_path()).endswith("/acme.pem")


def test_extra_field_rejected() -> None:
    with pytest.raises(ValueError):
        ServerConfig.model_validate(
            {"id": "x", "type": "physical", "connection": "local", "unknown": 1}
        )


# ────────── load_servers_yml ──────────


def test_load_valid_yaml(tmp_path: Path) -> None:
    yml = tmp_path / "servers.yml"
    yml.write_text(
        """
        servers:
          - id: physical-main
            type: physical
            connection: local
            labels: [default]
          - id: acme
            type: ec2
            connection: ssh
            host: 1.2.3.4
            ssh_user: ubuntu
            pem: acme
        """
    )
    servers = load_servers_yml(yml)
    assert [s.id for s in servers] == ["physical-main", "acme"]


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ServerConfigError, match="not found"):
        load_servers_yml(tmp_path / "does-not-exist.yml")


def test_missing_servers_key(tmp_path: Path) -> None:
    yml = tmp_path / "servers.yml"
    yml.write_text("not_servers: []\n")
    with pytest.raises(ServerConfigError, match="'servers:' key"):
        load_servers_yml(yml)


def test_empty_servers_list(tmp_path: Path) -> None:
    yml = tmp_path / "servers.yml"
    yml.write_text("servers: []\n")
    with pytest.raises(ServerConfigError, match="at least one server"):
        load_servers_yml(yml)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    yml = tmp_path / "servers.yml"
    yml.write_text(
        """
        servers:
          - id: same
            type: physical
            connection: local
          - id: same
            type: physical
            connection: local
        """
    )
    with pytest.raises(ServerConfigError, match="duplicate"):
        load_servers_yml(yml)


def test_invalid_entry_validation_error(tmp_path: Path) -> None:
    yml = tmp_path / "servers.yml"
    yml.write_text(
        """
        servers:
          - id: bad
            type: ec2
            connection: ssh
        """
    )
    with pytest.raises(ServerConfigError, match="failed validation"):
        load_servers_yml(yml)


def test_malformed_yaml(tmp_path: Path) -> None:
    yml = tmp_path / "servers.yml"
    yml.write_text("servers:\n  - id: x\n    type: [unclosed\n")
    with pytest.raises(ServerConfigError, match="YAML parse error"):
        load_servers_yml(yml)


# ────────── Mongo sync ──────────


@pytest.fixture
def fake_db() -> object:
    client: AsyncMongoMockClient = AsyncMongoMockClient()
    return client["test_db"]


async def test_sync_upserts_all_entries(fake_db: object) -> None:
    servers = [
        ServerConfig(id="a", type="physical", connection="local"),
        ServerConfig(id="b", type="physical", connection="local"),
    ]
    result = await sync_to_mongo(fake_db, servers)  # type: ignore[arg-type]
    assert result == {"upserted": 2, "removed": 0}
    all_servers = await list_servers(fake_db)  # type: ignore[arg-type]
    assert {s.id for s in all_servers} == {"a", "b"}


async def test_sync_removes_stale_entries(fake_db: object) -> None:
    # Seed with two.
    await sync_to_mongo(
        fake_db,  # type: ignore[arg-type]
        [
            ServerConfig(id="a", type="physical", connection="local"),
            ServerConfig(id="stale", type="physical", connection="local"),
        ],
    )
    # Second sync drops "stale".
    result = await sync_to_mongo(
        fake_db,  # type: ignore[arg-type]
        [ServerConfig(id="a", type="physical", connection="local")],
    )
    assert result == {"upserted": 1, "removed": 1}
    remaining = await list_servers(fake_db)  # type: ignore[arg-type]
    assert [s.id for s in remaining] == ["a"]


async def test_get_server_found_and_missing(fake_db: object) -> None:
    await sync_to_mongo(
        fake_db,  # type: ignore[arg-type]
        [ServerConfig(id="a", type="physical", connection="local")],
    )
    got = await get_server(fake_db, "a")  # type: ignore[arg-type]
    assert got is not None and got.id == "a"
    assert await get_server(fake_db, "nope") is None  # type: ignore[arg-type]


async def test_sync_updates_changed_fields(fake_db: object) -> None:
    await sync_to_mongo(
        fake_db,  # type: ignore[arg-type]
        [ServerConfig(id="a", type="physical", connection="local", labels=["old"])],
    )
    await sync_to_mongo(
        fake_db,  # type: ignore[arg-type]
        [ServerConfig(id="a", type="physical", connection="local", labels=["new"])],
    )
    got = await get_server(fake_db, "a")  # type: ignore[arg-type]
    assert got is not None
    assert got.labels == ["new"]
