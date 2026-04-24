"""Settings load + parse tests."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test from tmp_path so the real .env doesn't leak in."""
    monkeypatch.chdir(tmp_path)


def _minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("GITHUB_ORG", "TestOrg")
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    monkeypatch.setenv("MONGO_DB_NAME", "testdb")


def _fresh_settings():
    """Reload the settings module so env changes take effect."""
    import config.settings

    return importlib.reload(config.settings).Settings()


def test_minimal_settings_load(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env(monkeypatch)
    s = _fresh_settings()
    assert s.GITHUB_TOKEN == "ghp_test"
    assert s.GITHUB_ORG == "TestOrg"
    assert s.MONGO_URL == "mongodb://localhost:27017"
    assert s.MONGO_DB_NAME == "testdb"


def test_defaults_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env(monkeypatch)
    s = _fresh_settings()
    assert s.AGENT_PORT == 8100
    assert s.OPENAI_MODEL == "gpt-4o-mini"
    assert s.ENABLE_FREE_TEXT_CHAT is True
    assert s.ENABLE_PREDEPLOY_ANALYSIS is True
    assert s.ENABLE_EXPLAIN_COMMAND is True
    assert s.ENABLE_LOG_ALERTS is True
    assert s.LOG_LEVEL == "INFO"
    assert s.PEM_DIR == "/devops_agent/pem"
    assert s.SERVERS_YML_PATH == "secrets/servers.yml"
    assert s.ALLOWED_TELEGRAM_USERS == []


def test_allowed_users_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env(monkeypatch)
    monkeypatch.setenv("ALLOWED_TELEGRAM_USERS", "123,456,789")
    s = _fresh_settings()
    assert s.ALLOWED_TELEGRAM_USERS == [123, 456, 789]


def test_allowed_users_handles_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env(monkeypatch)
    monkeypatch.setenv("ALLOWED_TELEGRAM_USERS", " 1 , 2,3 ")
    s = _fresh_settings()
    assert s.ALLOWED_TELEGRAM_USERS == [1, 2, 3]


def test_allowed_users_skips_non_numeric(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env(monkeypatch)
    monkeypatch.setenv("ALLOWED_TELEGRAM_USERS", "123,abc,456")
    s = _fresh_settings()
    assert s.ALLOWED_TELEGRAM_USERS == [123, 456]


def test_log_level_uppercased(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env(monkeypatch)
    monkeypatch.setenv("LOG_LEVEL", "debug")
    s = _fresh_settings()
    assert s.LOG_LEVEL == "DEBUG"


def test_required_field_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GITHUB_TOKEN", "GITHUB_ORG", "MONGO_URL", "MONGO_DB_NAME"):
        monkeypatch.delenv(var, raising=False)

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        import config.settings as cs

        importlib.reload(cs)
