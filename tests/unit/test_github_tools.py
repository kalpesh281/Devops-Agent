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
        "  list_services: auto\n"
        "  refresh_cache: auto\n"
        "denylist_containers: []\n"
    )
    from tools import registry

    registry.reset_registry()


async def test_all_github_tools_register() -> None:
    import tools.github_tools  # noqa: F401
    from tools.registry import REGISTRY

    for n in (
        "list_repos",
        "list_branches",
        "list_commits",
        "list_prs",
        "list_files",
        "list_services",
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


def _stub_github_with_files(present: dict[str, int]) -> MagicMock:
    """Build a mock PyGithub client where only the given paths resolve."""

    def _get_contents(path: str, ref: str) -> MagicMock:  # noqa: ARG001
        if path in present:
            m = MagicMock()
            m.path = path
            m.size = present[path]
            m.sha = "a" * 40
            return m
        raise GithubException(404, {"message": "Not Found"}, None)

    mock_repo = MagicMock()
    mock_repo.get_contents.side_effect = _get_contents
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo
    return mock_gh


async def test_list_files_node_stack_complete() -> None:
    import tools.github_tools as gt

    mock_gh = _stub_github_with_files(
        {
            "Dockerfile": 1234,
            "deploy.config.yml": 340,
            "package.json": 2100,
            ".dockerignore": 150,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="frontend", branch="main")

    assert result["stack"] == "node"
    assert result["stack_marker"] == "package.json"
    assert result["deploy_ready"] is True
    assert result["missing_required"] == []
    # Required bucket now ONLY holds the two universal blockers.
    required_paths = {e["path"] for e in result["required"]}
    assert required_paths == {"Dockerfile", "deploy.config.yml"}


async def test_list_files_python_poetry_detected() -> None:
    import tools.github_tools as gt

    # Poetry project — has pyproject.toml, no requirements.txt. Not flagged.
    mock_gh = _stub_github_with_files(
        {
            "Dockerfile": 800,
            "deploy.config.yml": 340,
            "pyproject.toml": 1800,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="backend", branch="main")

    assert result["stack"] == "python"
    assert result["stack_marker"] == "pyproject.toml"
    assert result["substack"] == "Poetry"
    assert result["deploy_ready"] is True
    assert result["missing_required"] == []
    # requirements.txt should NOT appear in required even though it's absent.
    assert not any(e["path"] == "requirements.txt" for e in result["required"])


async def test_list_files_python_plain_venv_also_works() -> None:
    import tools.github_tools as gt

    # Plain-venv project — has requirements.txt, no pyproject.toml. Not flagged.
    mock_gh = _stub_github_with_files(
        {
            "Dockerfile": 800,
            "deploy.config.yml": 340,
            "requirements.txt": 500,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="legacy-api", branch="main")

    assert result["stack"] == "python"
    assert result["stack_marker"] == "requirements.txt"
    assert result["substack"] == "pip/venv"
    assert result["deploy_ready"] is True
    # pyproject.toml should NOT appear as missing.
    assert not any(e["path"] == "pyproject.toml" for e in result["required"])


async def test_list_files_flutter_detected() -> None:
    import tools.github_tools as gt

    mock_gh = _stub_github_with_files(
        {
            "pubspec.yaml": 400,
            "Dockerfile": 800,
            "deploy.config.yml": 340,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="mobile-app", branch="main")

    assert result["stack"] == "flutter"
    assert result["stack_marker"] == "pubspec.yaml"


async def test_list_files_gradle_detected() -> None:
    import tools.github_tools as gt

    mock_gh = _stub_github_with_files(
        {
            "build.gradle": 1200,
            "Dockerfile": 800,
            "deploy.config.yml": 340,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="android-api", branch="main")

    assert result["stack"] == "gradle"
    assert result["stack_marker"] == "build.gradle"


async def test_list_files_unknown_stack_still_deploy_ready_if_critical_present() -> None:
    import tools.github_tools as gt

    # No stack marker, but Dockerfile + deploy.config.yml exist → deploy-ready.
    # Previously this would have been blocked on "stack unknown" — now stack is
    # informational and the two critical files are the only hard blocker.
    mock_gh = _stub_github_with_files(
        {
            "Dockerfile": 800,
            "deploy.config.yml": 340,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="mystery", branch="main")

    assert result["stack"] == "unknown"
    assert result["deploy_ready"] is True  # critical files present


async def test_list_files_frontend_missing_deploy_config() -> None:
    import tools.github_tools as gt

    # Node repo with everything except deploy.config.yml — not deploy-ready.
    mock_gh = _stub_github_with_files(
        {
            "package.json": 2100,
            "Dockerfile": 1234,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="frontend", branch="main")

    assert result["stack"] == "node"
    assert result["deploy_ready"] is False
    assert result["missing_required"] == ["deploy.config.yml"]


async def test_list_files_flutter_wins_over_nested_package_json() -> None:
    import tools.github_tools as gt

    # Flutter projects sometimes have a package.json tooling helper — pubspec
    # must still win.
    mock_gh = _stub_github_with_files(
        {
            "pubspec.yaml": 400,
            "package.json": 200,
            "Dockerfile": 800,
            "deploy.config.yml": 340,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="flutter-with-tooling", branch="main")

    assert result["stack"] == "flutter"


async def test_list_files_monorepo_frontend_path() -> None:
    import tools.github_tools as gt

    # Monorepo: only frontend/* files exist; root has nothing.
    mock_gh = _stub_github_with_files(
        {
            "frontend/package.json": 2100,
            "frontend/Dockerfile": 1234,
            "frontend/deploy.config.yml": 340,
            "frontend/.dockerignore": 150,
        }
    )
    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_files(repo="mymono", branch="main", path="frontend")

    assert result["path"] == "frontend"
    assert result["stack"] == "node"
    assert result["deploy_ready"] is True


async def test_list_files_rejects_parent_traversal() -> None:
    import tools.github_tools as gt

    mock_gh = _stub_github_with_files({})
    with (
        patch.object(gt, "_gh_client", None),
        patch.object(gt, "Github", return_value=mock_gh),
        pytest.raises(ValueError, match="invalid path"),
    ):
        await gt.list_files(repo="evil", branch="main", path="../etc")


async def test_list_services_finds_monorepo_configs() -> None:
    import tools.github_tools as gt

    # Stub the tree API to return two deploy.config.yml files + top-level entries.
    tree_entries = [
        MagicMock(type="blob", path="frontend/deploy.config.yml"),
        MagicMock(type="blob", path="backend/deploy.config.yml"),
        MagicMock(type="blob", path="README.md"),
        MagicMock(type="blob", path=".gitignore"),
        MagicMock(type="tree", path="frontend"),
        MagicMock(type="tree", path="backend"),
        MagicMock(type="tree", path="shared"),
    ]
    mock_tree = MagicMock()
    mock_tree.tree = tree_entries

    mock_branch = MagicMock()
    mock_branch.commit.sha = "deadbeef"

    mock_repo = MagicMock()
    mock_repo.get_branch.return_value = mock_branch
    mock_repo.get_git_tree.return_value = mock_tree

    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo

    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_services(repo="mymono", branch="main")

    assert result["count"] == 2
    names = {s["name"] for s in result["services"]}
    assert names == {"frontend", "backend"}
    paths = {s["path"] for s in result["services"]}
    assert paths == {"frontend", "backend"}
    # New layout fields:
    assert set(result["root_folders"]) == {"frontend", "backend", "shared"}
    assert "README.md" in result["root_files"]
    assert ".gitignore" in result["root_files"]
    # Only frontend + backend hold configs; shared is a plain folder.
    assert set(result["folders_with_config"]) == {"frontend", "backend"}


async def test_list_services_root_config_uses_repo_name() -> None:
    import tools.github_tools as gt

    tree_entries = [MagicMock(type="blob", path="deploy.config.yml")]
    mock_tree = MagicMock()
    mock_tree.tree = tree_entries
    mock_branch = MagicMock()
    mock_branch.commit.sha = "deadbeef"
    mock_repo = MagicMock()
    mock_repo.get_branch.return_value = mock_branch
    mock_repo.get_git_tree.return_value = mock_tree
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo

    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_services(repo="single-service", branch="main")

    assert result["count"] == 1
    assert result["services"][0]["path"] == "."
    assert result["services"][0]["name"] == "single-service"


async def test_list_services_empty_repo_returns_no_services() -> None:
    import tools.github_tools as gt

    mock_tree = MagicMock()
    mock_tree.tree = [MagicMock(type="blob", path="README.md")]
    mock_branch = MagicMock()
    mock_branch.commit.sha = "deadbeef"
    mock_repo = MagicMock()
    mock_repo.get_branch.return_value = mock_branch
    mock_repo.get_git_tree.return_value = mock_tree
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo

    with patch.object(gt, "_gh_client", None), patch.object(gt, "Github", return_value=mock_gh):
        result = await gt.list_services(repo="empty", branch="main")

    assert result["count"] == 0
    assert result["services"] == []


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
