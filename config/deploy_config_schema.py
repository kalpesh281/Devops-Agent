"""Pydantic v2 schema for each repo's ``deploy.config.yml`` (spec §14.4).

Strict validation (``extra = "forbid"``) — unknown fields are errors, so a
typo like ``target_sever:`` won't silently misdeploy. ``validate_yaml()``
returns either the parsed model or a human-friendly Telegram-HTML error
message with rapidfuzz "did you mean" hints for unknown keys.
"""

from __future__ import annotations

from html import escape
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rapidfuzz import process


class DockerHubConfig(BaseModel):
    """Docker Hub image coordinates for this deployment."""

    model_config = ConfigDict(extra="forbid")

    image: str = Field(
        ...,
        description="Docker Hub repo, e.g. kalpesh281/trading-dashboard",
        min_length=1,
    )


class ResourceLimits(BaseModel):
    """Container resource caps applied on every ``docker run`` (§14.5)."""

    model_config = ConfigDict(extra="forbid")

    memory: str = Field("512m", description="e.g. 512m, 1g, 2g")
    cpus: str = Field("1.0", description="e.g. 0.5, 1.0, 2.0")
    pids: int = Field(256, gt=0, description="max processes inside container")


class DeployConfig(BaseModel):
    """Top-level ``deploy.config.yml`` schema (spec §5.3 + §14.4)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Deployment name / container name")
    project: str = Field("internal", description="Used to find /devops_agent/pem/<project>.pem")
    stack: Literal["node", "python", "static", "custom"]
    build: Literal["docker"] = "docker"
    port: int = Field(..., gt=0, lt=65536, description="Container port")
    target_server: str = Field(..., description="Must match an id in secrets/servers.yml")
    docker_hub: DockerHubConfig
    env_required: list[str] = Field(default_factory=list)
    healthcheck: str = Field("/health", description="HTTP path checked after start")
    # All ResourceLimits fields have defaults, so the no-arg call is valid.
    resources: ResourceLimits = Field(default_factory=ResourceLimits)  # type: ignore[arg-type]


# Flattened set of every known field name (top-level + nested). Used by
# rapidfuzz to offer "did you mean <field>?" on ``extra_forbidden`` errors.
_KNOWN_FIELDS: tuple[str, ...] = tuple(
    sorted(
        set(DeployConfig.model_fields)
        | set(DockerHubConfig.model_fields)
        | set(ResourceLimits.model_fields)
    )
)


def _format_validation_error(exc: ValidationError) -> str:
    """Render a ValidationError as Telegram-HTML for the user."""
    lines: list[str] = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "(root)"
        msg = err["msg"]
        if err["type"] == "extra_forbidden":
            leaf = field.rsplit(".", 1)[-1]
            match = process.extractOne(leaf, _KNOWN_FIELDS)
            if match and match[1] > 60 and match[0] != leaf:
                msg += f" (did you mean <code>{escape(match[0])}</code>?)"
        lines.append(f"  • <code>{escape(field)}</code> — {escape(msg)}")
    return (
        "<b>🟡 deploy.config.yml has errors:</b>\n"
        + "\n".join(lines)
        + "\n\n<i>Fix these and retry the deploy.</i>"
    )


def validate_yaml(yaml_text: str) -> tuple[DeployConfig | None, str | None]:
    """Parse and validate a ``deploy.config.yml`` string.

    Returns ``(config, None)`` on success, ``(None, html_error)`` on failure.
    The error is safe to post directly to Telegram with ``parse_mode="HTML"``.
    """
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        return None, f"<b>🟡 Invalid YAML syntax</b>\n<pre>{escape(str(e))}</pre>"

    if not isinstance(data, dict):
        return (
            None,
            "<b>🟡 deploy.config.yml must be a YAML mapping</b> "
            f"(got <code>{escape(type(data).__name__)}</code>).",
        )

    try:
        return DeployConfig.model_validate(data), None
    except ValidationError as e:
        return None, _format_validation_error(e)
