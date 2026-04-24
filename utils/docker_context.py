"""Docker client factory with per-server caching (spec §5, §6).

Returns the right Docker SDK client for a ``server_id`` by inspecting the
registry entry's ``connection`` field:

* ``connection: local`` → ``docker.from_env()`` (talks to the local daemon).
* ``connection: ssh``   → ``DockerClient(base_url="ssh://user@host")``
  (docker-py invokes the ``docker`` CLI over SSH via paramiko).

Clients are cached per ``server_id`` so we don't pay the SSH-connect cost
on every command. The cache is keyed by ``(server_id, config_hash)``;
changing the registry entry invalidates the cached client automatically
on next lookup. Use :func:`invalidate` to force a rebuild.

**SSH auth note:** docker-py's ``ssh://`` scheme uses your system SSH
configuration — it does *not* accept a key-file argument. For a PEM in
``${PEM_DIR}``, add it to ``~/.ssh/config`` for the target host (or load
it into your ssh-agent) before the first call. See
``config/servers.example.yml`` for the exact snippet.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import docker
from docker import DockerClient

from utils.logger import get_logger
from utils.server_registry import ServerConfig

log = get_logger(__name__)


class PemNotFoundError(Exception):
    """PEM file referenced by a server entry does not exist on disk."""


class ServerNotFoundError(Exception):
    """Asked for a Docker client for a server id that isn't in the cache."""


_clients: dict[str, tuple[str, DockerClient]] = {}
_lock = threading.Lock()


def _hash_config(sc: ServerConfig) -> str:
    """Stable hash of the server config — changes invalidate the cache."""
    payload = sc.model_dump(mode="json", exclude_none=True)
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _ensure_pem_exists(sc: ServerConfig) -> None:
    """Fail fast if an SSH server's PEM is missing (§5.2)."""
    if sc.connection != "ssh":
        return
    pem = sc.pem_path()
    if pem is None or not Path(pem).exists():
        raise PemNotFoundError(
            f"server {sc.id!r} expects PEM at {pem} but it's missing. "
            "Create /devops_agent/pem/<project>.pem (mode 600) and retry."
        )


def _build_client(sc: ServerConfig) -> DockerClient:
    """Build a fresh DockerClient for this server config."""
    if sc.connection == "local":
        log.info("docker.client.local", server_id=sc.id)
        client: DockerClient = docker.from_env(timeout=30)
        return client

    _ensure_pem_exists(sc)
    base_url = sc.docker_base_url()
    log.info("docker.client.ssh", server_id=sc.id, base_url=base_url)
    # use_ssh_client=True → invoke the system `ssh` binary (reads ~/.ssh/config).
    return DockerClient(base_url=base_url, use_ssh_client=True, timeout=30)


def get_docker_client(sc: ServerConfig) -> DockerClient:
    """Return a cached DockerClient for this server, rebuilding on config change.

    Takes the :class:`ServerConfig` directly (not just the id) so callers
    that already loaded it don't pay for a second Mongo round-trip. The
    cache key is ``sc.id``; the cached value is ``(config_hash, client)``.
    """
    digest = _hash_config(sc)
    with _lock:
        cached = _clients.get(sc.id)
        if cached is not None and cached[0] == digest:
            return cached[1]
        # Config changed (or first call) — build a fresh client.
        if cached is not None:
            _safe_close(cached[1])
        client = _build_client(sc)
        _clients[sc.id] = (digest, client)
        return client


def invalidate(server_id: str) -> bool:
    """Drop the cached client for ``server_id``. Returns True if evicted."""
    with _lock:
        cached = _clients.pop(server_id, None)
    if cached is None:
        return False
    _safe_close(cached[1])
    log.info("docker.client.invalidated", server_id=server_id)
    return True


def invalidate_all() -> None:
    """Close and drop every cached client. Called on shutdown."""
    with _lock:
        items = list(_clients.items())
        _clients.clear()
    for server_id, (_, client) in items:
        _safe_close(client)
        log.info("docker.client.closed", server_id=server_id)


def _safe_close(client: DockerClient) -> None:
    try:
        client.close()
    except Exception as e:  # noqa: BLE001 - close is best-effort
        log.warning("docker.client.close_failed", error=str(e))


def ping(sc: ServerConfig) -> dict[str, Any]:
    """Ping a server's Docker daemon. Returns a small status dict.

    On any error the exception is caught and returned as ``{"ok": False,
    "error": ...}`` — callers decide whether to surface it.
    """
    try:
        client = get_docker_client(sc)
        version = client.version()
        return {
            "ok": True,
            "server_id": sc.id,
            "docker_version": version.get("Version"),
            "api_version": version.get("ApiVersion"),
        }
    except Exception as e:  # noqa: BLE001 - surface any error to the caller
        return {"ok": False, "server_id": sc.id, "error": str(e)}
