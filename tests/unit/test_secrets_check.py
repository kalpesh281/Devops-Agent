"""verify_env_security() tests — perm-mode logic."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _reload_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_ORG", "o")
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost")
    monkeypatch.setenv("MONGO_DB_NAME", "d")
    import config.settings

    importlib.reload(config.settings)


def test_env_600_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("X=1")
    env.chmod(0o600)
    monkeypatch.setenv("PEM_DIR", str(tmp_path / "nonexistent_pem"))
    _reload_settings(monkeypatch)

    import utils.secrets_check

    importlib.reload(utils.secrets_check)
    result = utils.secrets_check.verify_env_security()
    assert result["env_exists"] is True
    assert result["env_permissive"] is False
    assert result["env_mode"] == "0o600"


def test_env_644_is_permissive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("X=1")
    env.chmod(0o644)
    monkeypatch.setenv("PEM_DIR", str(tmp_path / "nonexistent_pem"))
    _reload_settings(monkeypatch)

    import utils.secrets_check

    importlib.reload(utils.secrets_check)
    result = utils.secrets_check.verify_env_security()
    assert result["env_exists"] is True
    assert result["env_permissive"] is True


def test_env_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PEM_DIR", str(tmp_path / "nonexistent_pem"))
    _reload_settings(monkeypatch)

    import utils.secrets_check

    importlib.reload(utils.secrets_check)
    result = utils.secrets_check.verify_env_security()
    assert result["env_exists"] is False


def test_pem_dir_700_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    pem = tmp_path / "pem"
    pem.mkdir()
    pem.chmod(0o700)
    monkeypatch.setenv("PEM_DIR", str(pem))
    _reload_settings(monkeypatch)

    import utils.secrets_check

    importlib.reload(utils.secrets_check)
    result = utils.secrets_check.verify_env_security()
    assert result["pem_exists"] is True
    assert result["pem_permissive"] is False
    assert result["pem_mode"] == "0o700"


def test_pem_dir_755_is_permissive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    pem = tmp_path / "pem"
    pem.mkdir()
    pem.chmod(0o755)
    monkeypatch.setenv("PEM_DIR", str(pem))
    _reload_settings(monkeypatch)

    import utils.secrets_check

    importlib.reload(utils.secrets_check)
    result = utils.secrets_check.verify_env_security()
    assert result["pem_exists"] is True
    assert result["pem_permissive"] is True
