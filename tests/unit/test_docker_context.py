"""Unit tests for utils/docker_context.py (spec §5, §6).

Real Docker SDK calls are patched — these tests run offline on any machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from utils import docker_context
from utils.docker_context import (
    PemNotFoundError,
    get_docker_client,
    invalidate,
    invalidate_all,
)
from utils.server_registry import ServerConfig


class FakeDockerClient:
    """Stand-in for docker.DockerClient. Tracks how it was built + closed."""

    def __init__(self, base_url: str | None = None, **kwargs: Any) -> None:
        self.base_url = base_url
        self.kwargs = kwargs
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def version(self) -> dict[str, str]:
        return {"Version": "28.0.0", "ApiVersion": "1.45"}


@pytest.fixture(autouse=True)
def _reset_cache() -> Any:
    invalidate_all()
    yield
    invalidate_all()


@pytest.fixture
def patch_docker(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Replace docker.from_env and DockerClient with fakes; record calls."""
    calls: dict[str, list[Any]] = {"from_env": [], "client": []}

    def fake_from_env(**kwargs: Any) -> FakeDockerClient:
        calls["from_env"].append(kwargs)
        return FakeDockerClient()

    class FakeClientCtor(FakeDockerClient):
        def __init__(self, **kwargs: Any) -> None:
            calls["client"].append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(docker_context.docker, "from_env", fake_from_env)
    monkeypatch.setattr(docker_context, "DockerClient", FakeClientCtor)
    return calls


def test_local_uses_from_env(patch_docker: dict[str, list[Any]]) -> None:
    sc = ServerConfig(id="local-1", type="physical", connection="local")
    client = get_docker_client(sc)
    assert isinstance(client, FakeDockerClient)
    assert len(patch_docker["from_env"]) == 1
    assert not patch_docker["client"]  # SSH ctor not called


def test_ssh_uses_ssh_base_url(
    patch_docker: dict[str, list[Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pem = tmp_path / "acme.pem"
    pem.write_text("fake-key")
    # Redirect pem_path() to the temp file so _ensure_pem_exists passes.
    monkeypatch.setattr(ServerConfig, "pem_path", lambda _self: pem)

    sc = ServerConfig(
        id="ec2-1",
        type="ec2",
        connection="ssh",
        host="example.com",
        ssh_user="ubuntu",
        pem="acme",
    )
    client = get_docker_client(sc)
    assert isinstance(client, FakeDockerClient)
    assert patch_docker["client"]
    assert patch_docker["client"][0]["base_url"] == "ssh://ubuntu@example.com"
    assert patch_docker["client"][0]["use_ssh_client"] is True


def test_ssh_missing_pem_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "never-created.pem"
    monkeypatch.setattr(ServerConfig, "pem_path", lambda _self: missing)

    sc = ServerConfig(
        id="broken",
        type="ec2",
        connection="ssh",
        host="example.com",
        ssh_user="ubuntu",
        pem="doesnotexist",
    )
    with pytest.raises(PemNotFoundError):
        get_docker_client(sc)


def test_cached_client_reused(patch_docker: dict[str, list[Any]]) -> None:
    sc = ServerConfig(id="a", type="physical", connection="local")
    c1 = get_docker_client(sc)
    c2 = get_docker_client(sc)
    assert c1 is c2
    assert len(patch_docker["from_env"]) == 1


def test_config_change_invalidates_cache(patch_docker: dict[str, list[Any]]) -> None:
    sc1 = ServerConfig(id="a", type="physical", connection="local", labels=["v1"])
    sc2 = ServerConfig(id="a", type="physical", connection="local", labels=["v2"])
    c1 = get_docker_client(sc1)
    c2 = get_docker_client(sc2)
    assert c1 is not c2
    assert len(patch_docker["from_env"]) == 2
    assert c1.closed is True  # type: ignore[attr-defined]


def test_invalidate_evicts_and_closes(patch_docker: dict[str, list[Any]]) -> None:
    _ = patch_docker  # fixture patches docker.from_env for this test too
    sc = ServerConfig(id="a", type="physical", connection="local")
    c1 = get_docker_client(sc)
    assert invalidate("a") is True
    assert invalidate("a") is False
    assert c1.closed is True  # type: ignore[attr-defined]
