"""Tests for the 6 GitHub tools.

- Registry membership
- Cache-backed tools (list_repos, list_branches) with seeded cache
- Live-API tools (list_commits, list_prs, list_files) with PyGithub mocks
- refresh_cache timing
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from github import GithubException


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_ORG", "TestOrg")
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost")
    monkeypatch.setenv("MONGO_DB_NAME", "d")
    import config.settings

    importlib.reload(config.settings)
    # tool_tiers.yml in tmp for registry
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "tool_tiers.yml").write_text(
        "tiers:\n"
        "  list_repos: auto\n"
        "  list_branches: auto\n"
        "  list_commits: auto\n"
        "  list_prs: auto\n"
        "  list_files: auto\n"
        "  refresh_cache: auto\n"
        "denylist_containers: []\n"
    )
    from tools import registry

    registry.reset_registry()


async def test_all_six_tools_register() -> None:
    import tools.github_tools  # noqa: F401
    from tools.registry import REGISTRY

    for n in (
        "list_repos",
        "list_branches",
        "list_commits",
        "list_prs",
        "list_files",
        "refresh_cache",
    ):
        assert n in REGISTRY, f"missing tool: {n}"
        assert REGISTRY[n].tier == "auto"


async def test_list_repos_returns_cache_contents() -> None:
    import tools.github_tools as gt
    from utils.github_cache import cache

    cache.repos = ["alpha", "beta", "gamma"]
    cache.owner_kind = "organization"
    cache.last_refresh = datetime.now(UTC)

    result = await gt.list_repos()
    assert result["repos"] == ["alpha", "beta", "gamma"]
    assert result["count"] == 3
    assert result["owner_kind"] == "organization"
    assert result["last_refresh"] is not None


async def test_list_branches_happy_path() -> None:
    import tools.github_tools as gt
    from utils.github_cache import cache

    cache.branches = {"alpha": ["main", "dev"]}
    result = await gt.list_branches(repo="alpha")
    assert result == {"repo": "alpha", "branches": ["main", "dev"], "count": 2}


async def test_list_branches_unknown_repo_raises() -> None:
    import tools.github_tools as gt
    from utils.github_cache import cache

    cache.branches = {}
    with pytest.raises(ValueError, match="not in cache"):
        await gt.list_branches(repo="nonexistent")


async def test_list_commits_limit_applied() -> None:
    import tools.github_tools as gt

    mock_commit = MagicMock()
    mock_commit.sha = "abcdef1234567890"
    mock_commit.commit.message = "Initial commit\n\nBody here"
    mock_commit.commit.author.name = "Alice"
    mock_commit.commit.author.date = datetime(2026, 1, 1, tzinfo=UTC)

    mock_repo = MagicMock()
    mock_repo.get_commits.return_value = [mock_commit] * 20  # more than limit
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo

    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_commits(repo="alpha", branch="main", limit=5)

    assert result["count"] == 5
    assert result["commits"][0]["sha"] == "abcdef1"
    assert result["commits"][0]["message"] == "Initial commit"
    assert result["commits"][0]["author"] == "Alice"


async def test_list_prs_error_wrapped() -> None:
    import tools.github_tools as gt

    mock_gh = MagicMock()
    mock_gh.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, None)

    with (
        patch.object(gt, "_gh_client", None),
        patch.object(gt, "Github", return_value=mock_gh),
        pytest.raises(ValueError, match="GitHub 404"),
    ):
        await gt.list_prs(repo="missing")


async def test_list_files_present_and_missing() -> None:
    import tools.github_tools as gt

    def _get_contents(path: str, ref: str) -> MagicMock:  # noqa: ARG001
        if path == "Dockerfile":
            m = MagicMock()
            m.path = "Dockerfile"
            m.size = 1234
            m.sha = "f" * 40
            return m
        raise GithubException(404, {"message": "Not Found"}, None)

    mock_repo = MagicMock()
    mock_repo.get_contents.side_effect = _get_contents
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo

    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(
            repo="alpha", branch="main", patterns=["Dockerfile", "Makefile"]
        )

    assert len(result["present"]) == 1
    assert result["present"][0]["path"] == "Dockerfile"
    assert result["missing"] == ["Makefile"]


async def test_refresh_cache_calls_cache_refresh() -> None:
    import tools.github_tools as gt
    from utils.github_cache import cache

    # Replace refresh with an AsyncMock to avoid hitting the network
    with patch.object(cache, "refresh", AsyncMock(return_value=None)):
        cache.repos = ["x", "y"]
        cache.last_refresh = datetime.now(UTC)
        cache.owner_kind = "organization"
        result = await gt.refresh_cache()

    assert result["repo_count"] == 2
    assert result["owner"] == "TestOrg"
    assert "elapsed_ms" in result
