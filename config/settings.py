"""Application settings loaded from .env + environment variables.

Single source of truth for every configuration value in the codebase.
Import `settings` from this module; do not read `os.environ` directly.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Type-safe configuration object."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- Stage 1: GitHub ----
    GITHUB_TOKEN: str
    GITHUB_ORG: str
    # User-facing project/brand name shown in Telegram messages. Defaults to the
    # GitHub org if not set. Set this to a friendly product name like "CIChakra"
    # so enrollment messages read naturally, while GITHUB_ORG stays the technical
    # identifier for API calls.
    PROJECT_DISPLAY_NAME: str = ""

    # ---- Stage 1: OpenAI ----
    # Defaults to empty — Phase 10 (`utils/llm.py`) validates when the LLM is
    # actually needed. This keeps Phase 1-9 runnable without an OpenAI key.
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # ---- Stage 1: MongoDB ----
    MONGO_URL: str
    MONGO_DB_NAME: str

    # ---- Stage 1: Docker Hub ----
    DOCKER_HUB_USER: str = ""
    DOCKER_HUB_TOKEN: str = ""

    # ---- Runtime ----
    AGENT_PORT: int = 8100

    # ---- Feature toggles (§13) ----
    ENABLE_FREE_TEXT_CHAT: bool = True
    ENABLE_PREDEPLOY_ANALYSIS: bool = True
    ENABLE_EXPLAIN_COMMAND: bool = True
    ENABLE_LOG_ALERTS: bool = True

    # ---- Logging ----
    LOG_LEVEL: str = "INFO"

    # ---- Stage 2: Telegram ----
    TELEGRAM_BOT_TOKEN: str = ""
    # Bootstrap admin — the Telegram user ID that gets role=admin on first enrollment.
    # After that, admins promote others via `/users promote @handle`.
    FIRST_ADMIN_TELEGRAM_ID: int | None = None
    # NoDecode: pydantic-settings tries JSON-parsing lists by default; our
    # validator below handles the comma-separated string form instead.
    # Emergency bypass list — skips the users-collection check. Log warning on use.
    ALLOWED_TELEGRAM_USERS: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # ---- Stage 3: Paths ----
    PEM_DIR: str = "/devops_agent/pem"
    SERVERS_YML_PATH: str = "secrets/servers.yml"

    @field_validator("ALLOWED_TELEGRAM_USERS", mode="before")
    @classmethod
    def _parse_allowed_users(cls, v: object) -> object:
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",")]
            return [int(p) for p in parts if p and p.lstrip("-").isdigit()]
        return v

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _upper_log_level(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v

    def display_name(self) -> str:
        """User-facing brand name — falls back to GITHUB_ORG if unset."""
        return self.PROJECT_DISPLAY_NAME or self.GITHUB_ORG


settings = Settings()  # type: ignore[call-arg]
