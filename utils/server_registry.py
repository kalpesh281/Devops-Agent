"""Server registry — loads ``secrets/servers.yml`` into the Mongo ``servers``
collection on startup (spec §5.1).

Source of truth is the YAML file. Chat commands cannot add/remove/edit
servers (§5.1). On every boot we:

1. Parse the YAML → list[:class:`ServerConfig`] (strict Pydantic).
2. Upsert each entry into Mongo by ``_id``.
3. Delete any Mongo entry whose ``_id`` is NOT in the YAML — so the file
   stays authoritative.

The motor ``AsyncIOMotorDatabase`` handle is passed in (not imported) so
this module stays testable with ``mongomock-motor``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)

SERVERS_COLLECTION = "servers"


class ServerConfigError(Exception):
    """Raised when ``servers.yml`` is missing, malformed, or invalid."""


class ServerConfig(BaseModel):
    """A single target host declared in ``secrets/servers.yml`` (§5.1, §20)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="Unique string key; stored as Mongo _id")
    type: str = Field(..., description="physical | ec2 | vps | other (informational)")
    connection: Literal["local", "ssh"]

    # SSH-only — required together when connection == "ssh"
    host: str | None = None
    ssh_user: str | None = None
    pem: str | None = Field(
        default=None,
        description="PEM stem (no .pem, no path). Resolved as ${PEM_DIR}/${pem}.pem",
    )

    # Optional metadata
    region: str | None = None
    labels: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ssh_requires_host_user_pem(self) -> ServerConfig:
        if self.connection == "ssh":
            missing = [
                name
                for name, val in (
                    ("host", self.host),
                    ("ssh_user", self.ssh_user),
                    ("pem", self.pem),
                )
                if not val
            ]
            if missing:
                raise ValueError(
                    f"connection: ssh requires {', '.join(missing)} on server {self.id!r}"
                )
        return self

    def pem_path(self) -> Path | None:
        """Full filesystem path to the PEM, or None for ``connection: local``."""
        if self.connection != "ssh" or not self.pem:
            return None
        return Path(settings.PEM_DIR) / f"{self.pem}.pem"

    def docker_base_url(self) -> str | None:
        """Docker SDK ``base_url``. ``None`` → use docker.from_env()."""
        if self.connection == "local":
            return None
        return f"ssh://{self.ssh_user}@{self.host}"

    def to_mongo_doc(self) -> dict[str, Any]:
        """Serialize to the ``servers`` collection shape (spec §20)."""
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        doc["synced_at"] = datetime.now(UTC)
        return doc


def load_servers_yml(path: str | Path | None = None) -> list[ServerConfig]:
    """Parse and validate ``secrets/servers.yml``.

    Raises :class:`ServerConfigError` on any failure — the agent must not
    boot with a broken registry.
    """
    yml_path = Path(path) if path else Path(settings.SERVERS_YML_PATH)
    if not yml_path.exists():
        raise ServerConfigError(
            f"servers.yml not found at {yml_path}. "
            f"Copy config/servers.example.yml → {yml_path} and chmod 600."
        )

    try:
        raw = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ServerConfigError(f"YAML parse error in {yml_path}: {e}") from e

    if not isinstance(raw, dict) or "servers" not in raw:
        raise ServerConfigError(f"{yml_path} must be a mapping with a top-level 'servers:' key.")

    items = raw["servers"]
    if not isinstance(items, list) or not items:
        raise ServerConfigError(f"{yml_path} must list at least one server under 'servers:'.")

    servers: list[ServerConfig] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise ServerConfigError(f"{yml_path} entry #{i} is not a mapping.")
        try:
            sc = ServerConfig.model_validate(entry)
        except ValidationError as e:
            raise ServerConfigError(
                f"{yml_path} entry #{i} ({entry.get('id', '?')!r}) failed validation:\n{e}"
            ) from e
        if sc.id in seen_ids:
            raise ServerConfigError(f"{yml_path}: duplicate server id {sc.id!r}.")
        seen_ids.add(sc.id)
        servers.append(sc)

    log.info("servers.yml.loaded", path=str(yml_path), count=len(servers))
    return servers


async def sync_to_mongo(
    db: AsyncIOMotorDatabase[dict[str, Any]],
    servers: list[ServerConfig],
) -> dict[str, int]:
    """Upsert each server; delete Mongo entries not present in ``servers``.

    Returns ``{"upserted": n, "removed": m}`` so callers / logs know what
    actually changed.
    """
    coll = db[SERVERS_COLLECTION]

    # Upsert current entries.
    for sc in servers:
        doc = sc.to_mongo_doc()
        await coll.replace_one({"_id": sc.id}, doc, upsert=True)

    keep_ids = {sc.id for sc in servers}
    result = await coll.delete_many({"_id": {"$nin": list(keep_ids)}})
    removed = int(result.deleted_count or 0)

    log.info(
        "servers.sync.done",
        upserted=len(servers),
        removed=removed,
        ids=sorted(keep_ids),
    )
    return {"upserted": len(servers), "removed": removed}


async def get_server(
    db: AsyncIOMotorDatabase[dict[str, Any]],
    server_id: str,
) -> ServerConfig | None:
    """Fetch a single server by id, or ``None`` if not present."""
    doc = await db[SERVERS_COLLECTION].find_one({"_id": server_id})
    return _doc_to_model(doc) if doc else None


async def list_servers(
    db: AsyncIOMotorDatabase[dict[str, Any]],
) -> list[ServerConfig]:
    """Return every server in the registry, sorted by id."""
    cursor = db[SERVERS_COLLECTION].find({}).sort("_id", 1)
    return [_doc_to_model(doc) async for doc in cursor]


def _doc_to_model(doc: dict[str, Any]) -> ServerConfig:
    """Convert a Mongo doc (which has ``_id``) back to a ServerConfig."""
    data = {k: v for k, v in doc.items() if k not in ("_id", "synced_at")}
    data["id"] = doc["_id"]
    return ServerConfig.model_validate(data)
