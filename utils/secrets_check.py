"""Startup security check for `.env` and PEM folder permissions (§14.3).

Warns (structlog WARNING) but does not refuse boot — spec calls for a loud
warning, not a hard failure. Returns a dict summarising what was checked so
tests can assert without parsing logs.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import TypedDict

from utils.logger import get_logger

log = get_logger(__name__)


class SecurityCheckResult(TypedDict):
    env_exists: bool
    env_permissive: bool
    env_mode: str | None
    pem_exists: bool
    pem_permissive: bool
    pem_mode: str | None


def _is_group_or_other_accessible(mode: int) -> bool:
    """True if mode grants any rwx bit to group or other."""
    return bool(mode & (stat.S_IRWXG | stat.S_IRWXO))


def verify_env_security() -> SecurityCheckResult:
    """Check `.env` and `settings.PEM_DIR` permissions. Warns on issues."""
    from config.settings import settings  # lazy — avoids circular imports in tests

    result: SecurityCheckResult = {
        "env_exists": False,
        "env_permissive": False,
        "env_mode": None,
        "pem_exists": False,
        "pem_permissive": False,
        "pem_mode": None,
    }

    env_path = Path(".env")
    if env_path.exists():
        mode = env_path.stat().st_mode
        perm = oct(mode & 0o777)
        result["env_exists"] = True
        result["env_mode"] = perm
        if _is_group_or_other_accessible(mode):
            result["env_permissive"] = True
            log.warning(
                ".env has permissive permissions — fix with: chmod 600 .env",
                path=str(env_path),
                mode=perm,
            )
        else:
            log.info("env.permissions_ok", path=str(env_path), mode=perm)
    else:
        log.warning("env.missing", path=str(env_path))

    pem_dir = Path(settings.PEM_DIR)
    if pem_dir.exists():
        mode = pem_dir.stat().st_mode
        perm = oct(mode & 0o777)
        result["pem_exists"] = True
        result["pem_mode"] = perm
        if _is_group_or_other_accessible(mode):
            result["pem_permissive"] = True
            log.warning(
                "PEM dir has permissive permissions — fix with: chmod 700",
                path=str(pem_dir),
                mode=perm,
            )
        else:
            log.info("pem.permissions_ok", path=str(pem_dir), mode=perm)
    else:
        log.info("pem.absent_expected_pre_phase_5", path=str(pem_dir))

    return result
