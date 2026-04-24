"""Tests for GitHubCache — org and user detection, refresh."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def _branch(name: str) -> MagicMock:
    b = MagicMock()
    b.name = name
    return b


def _repo(name: str, branches: list[str]) -> MagicMock:
    r = MagicMock()
    r.name = name
    r.get_branches.return_value = [_branch(b) for b in branches]
    return r


def _entity_with_repos(repos: list[MagicMock], login: str = "TestOrg") -> MagicMock:
    e = MagicMock()
    e.login = login
    e.get_repos.return_value = repos
    return e


async def test_refresh_org_happy_path() -> None:
    from utils import github_cache

    importlib.reload(github_cache)
    repos = [_repo("repo-a", ["main"]), _repo("repo-b", ["dev", "main"])]

    mock_gh = MagicMock()
    mock_gh.get_organization.return_value = _entity_with_repos(repos)

    with patch.object(github_cache, "Github", return_value=mock_gh):
        c = github_cache.GitHubCache()
        await c.refresh()

    assert c.owner_kind == "organization"
    assert c.repos == ["repo-a", "repo-b"]
    assert c.branches["repo-a"] == ["main"]
    assert c.branches["repo-b"] == ["dev", "main"]
    assert c.last_refresh is not None


async def test_refresh_falls_back_to_user_on_404() -> None:
    from utils import github_cache

    importlib.reload(github_cache)
    repos = [_repo("solo-repo", ["main"])]

    mock_gh = MagicMock()
    mock_gh.get_organization.side_effect = GithubException(404, {"message": "Not Found"}, None)
    mock_gh.get_user.return_value = _entity_with_repos(repos, login="personal")

    with patch.object(github_cache, "Github", return_value=mock_gh):
        c = github_cache.GitHubCache()
        await c.refresh()

    assert c.owner_kind == "user"
    assert c.repos == ["solo-repo"]


async def test_refresh_raises_on_non_404_github_error() -> None:
    from utils import github_cache

    importlib.reload(github_cache)

    mock_gh = MagicMock()
    mock_gh.get_organization.side_effect = GithubException(500, {"message": "Server Error"}, None)

    with patch.object(github_cache, "Github", return_value=mock_gh):
        c = github_cache.GitHubCache()
        with pytest.raises(GithubException):
            await c.refresh()


async def test_branch_fetch_failure_does_not_abort_whole_refresh() -> None:
    from utils import github_cache

    importlib.reload(github_cache)

    good = _repo("good", ["main"])
    bad = MagicMock()
    bad.name = "bad"
    bad.get_branches.side_effect = GithubException(403, {"message": "Forbidden"}, None)

    mock_gh = MagicMock()
    mock_gh.get_organization.return_value = _entity_with_repos([good, bad])

    with patch.object(github_cache, "Github", return_value=mock_gh):
        c = github_cache.GitHubCache()
        await c.refresh()

    assert c.repos == ["good", "bad"]
    assert c.branches["good"] == ["main"]
    assert c.branches["bad"] == []  # failed fetch ends up as empty list
