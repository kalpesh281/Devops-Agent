"""Server + status tools — all read-only, tier=auto, 0 LLM tokens (§5, §6).

- ``list_servers`` reads the ``servers`` collection (populated from
  ``secrets/servers.yml`` on startup).
- ``server_status`` asks each server's Docker daemon for its running
  containers, optionally filtered to a single ``server_id``.
- ``disk_usage`` returns the ``docker system df`` equivalent for one
  server via ``DockerClient.df()``.

All three are registered via ``@tool`` so Phase 6 (LangGraph) can call
them by name. Each returns a plain ``dict`` — formatters in
``telegram_bot/messages.py`` render them for chat.
"""

from __future__ import annotations

import asyncio
from typing import Any

from docker.errors import DockerException

from tools.registry import tool
from utils.docker_context import get_docker_client
from utils.logger import get_logger
from utils.mongo import get_db
from utils.server_registry import ServerConfig, get_server, list_servers

log = get_logger(__name__)


# ───────────────────────── /servers ─────────────────────────


@tool(
    name="list_servers",
    description="List every deployment target from secrets/servers.yml (read-only).",
    schema={"type": "object", "properties": {}, "required": []},
)
async def list_servers_tool() -> dict[str, Any]:
    servers = await list_servers(get_db())
    return {
        "count": len(servers),
        "servers": [s.model_dump(mode="json", exclude_none=True) for s in servers],
    }


# ───────────────────────── /status ──────────────────────────


def _summarize_containers(client: Any) -> list[dict[str, Any]]:
    """Pull a compact running-container summary from a Docker client.

    Kept sync because docker-py is sync; callers wrap in ``to_thread``.
    """
    rows: list[dict[str, Any]] = []
    for c in client.containers.list(all=False):
        image_tags = c.image.tags or []
        rows.append(
            {
                "name": c.name,
                "image": image_tags[0] if image_tags else c.image.short_id,
                "status": c.status,
                "id": c.short_id,
            }
        )
    return rows


async def _status_for_server(sc: ServerConfig) -> dict[str, Any]:
    """Get running containers + connection health for a single server."""
    try:
        client = get_docker_client(sc)
        # `.list()` talks to the daemon — push to a thread so we don't block
        # the event loop on slow SSH targets.
        containers = await asyncio.to_thread(_summarize_containers, client)
        return {
            "server_id": sc.id,
            "connection": sc.connection,
            "ok": True,
            "containers": containers,
            "running_count": len(containers),
        }
    except DockerException as e:
        log.warning("server.status.docker_error", server_id=sc.id, error=str(e))
        return {
            "server_id": sc.id,
            "connection": sc.connection,
            "ok": False,
            "error": str(e),
            "containers": [],
            "running_count": 0,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("server.status.error", server_id=sc.id, error=str(e))
        return {
            "server_id": sc.id,
            "connection": sc.connection,
            "ok": False,
            "error": str(e),
            "containers": [],
            "running_count": 0,
        }


@tool(
    name="status",
    description="Show running containers on every server, or a single one if server_id is given.",
    schema={
        "type": "object",
        "properties": {
            "server_id": {
                "type": "string",
                "description": "Optional — filter to a single server id",
            }
        },
        "required": [],
    },
)
async def status_tool(server_id: str | None = None) -> dict[str, Any]:
    db = get_db()
    if server_id is not None:
        sc = await get_server(db, server_id)
        if sc is None:
            raise ValueError(f"unknown server: {server_id}")
        targets = [sc]
    else:
        targets = await list_servers(db)

    # Query each server concurrently — the SSH ones are slowest.
    results = await asyncio.gather(*(_status_for_server(sc) for sc in targets))
    return {
        "server_id": server_id,
        "servers": results,
        "total_running": sum(r["running_count"] for r in results),
    }


# ───────────────────────── /disk ────────────────────────────


def _call_df(client: Any) -> dict[str, Any]:
    """DockerClient.df() — sync wrapper returning the raw dict."""
    return client.df()  # type: ignore[no-any-return]


def _summarize_df(raw: dict[str, Any]) -> dict[str, Any]:
    """Condense docker df output into the fields we show.

    ``docker.df()`` returns keys: ``LayersSize``, ``Images``, ``Containers``,
    ``Volumes``, ``BuilderSize``. We surface total counts + reclaimable bytes.
    """

    def _sum(field: str, key: str) -> int:
        items = raw.get(field) or []
        return sum(int(i.get(key, 0) or 0) for i in items)

    return {
        "images_total": len(raw.get("Images") or []),
        "images_size_bytes": _sum("Images", "Size"),
        "containers_total": len(raw.get("Containers") or []),
        "containers_size_bytes": _sum("Containers", "SizeRw"),
        "volumes_total": len(raw.get("Volumes") or []),
        "volumes_size_bytes": _sum("Volumes", "UsageData.Size"),
        "builder_cache_bytes": int(raw.get("BuilderSize", 0) or 0),
        "layers_size_bytes": int(raw.get("LayersSize", 0) or 0),
    }


@tool(
    name="disk_usage",
    description="docker system df for a server (image/container/volume disk usage).",
    schema={
        "type": "object",
        "properties": {"server_id": {"type": "string"}},
        "required": ["server_id"],
    },
)
async def disk_usage_tool(server_id: str) -> dict[str, Any]:
    db = get_db()
    sc = await get_server(db, server_id)
    if sc is None:
        raise ValueError(f"unknown server: {server_id}")
    try:
        client = get_docker_client(sc)
        raw = await asyncio.to_thread(_call_df, client)
    except DockerException as e:
        raise ValueError(f"docker error on {server_id}: {e}") from e
    summary = _summarize_df(raw)
    return {"server_id": server_id, "connection": sc.connection, **summary}
