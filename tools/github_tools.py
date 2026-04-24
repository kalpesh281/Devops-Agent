"""GitHub query tools — all read-only, tier=auto, 0 LLM tokens.

- `list_repos` / `list_branches` serve from the in-memory cache (§10.2).
- `list_commits` / `list_prs` / `list_files` hit the live API (PyGithub).
- `refresh_cache` forces a cache rebuild and returns timing.

Every function is registered via `@tool` (§7.3) so the LangGraph graph
(Phase 6) can dispatch by name.
"""

from __future__ import annotations

from time import monotonic
from typing import Any

from github import Github, GithubException

from config.settings import settings
from tools.registry import tool
from utils.github_cache import cache
from utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_FILE_PATTERNS: tuple[str, ...] = (
    "Dockerfile",
    "docker-compose.yml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "deploy.config.yml",
    "Makefile",
    ".dockerignore",
    ".env.example",
    "README.md",
)

_gh_client: Github | None = None


def _gh() -> Github:
    global _gh_client
    if _gh_client is None:
        _gh_client = Github(settings.GITHUB_TOKEN)
    return _gh_client


def _full_name(repo: str) -> str:
    return f"{settings.GITHUB_ORG}/{repo}"


@tool(
    name="list_repos",
    description="List every repository owned by the configured GitHub org/user (cached).",
    schema={"type": "object", "properties": {}, "required": []},
)
async def list_repos() -> dict[str, Any]:
    return {
        "owner": settings.GITHUB_ORG,
        "owner_kind": cache.owner_kind,
        "repos": list(cache.repos),
        "count": len(cache.repos),
        "last_refresh": cache.last_refresh.isoformat() if cache.last_refresh else None,
    }


@tool(
    name="list_branches",
    description="List branches for a repository (cached).",
    schema={
        "type": "object",
        "properties": {"repo": {"type": "string"}},
        "required": ["repo"],
    },
)
async def list_branches(repo: str) -> dict[str, Any]:
    branches = cache.branches.get(repo)
    if branches is None:
        raise ValueError(f"repo not in cache: {repo}")
    return {"repo": repo, "branches": branches, "count": len(branches)}


@tool(
    name="list_commits",
    description="Recent commits on a branch (live API).",
    schema={
        "type": "object",
        "properties": {
            "repo": {"type": "string"},
            "branch": {"type": "string"},
            "limit": {"type": "integer", "default": 10, "maximum": 50},
        },
        "required": ["repo", "branch"],
    },
)
async def list_commits(repo: str, branch: str, limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(limit, 50))
    try:
        r = _gh().get_repo(_full_name(repo))
        out: list[dict[str, Any]] = []
        for i, c in enumerate(r.get_commits(sha=branch)):
            if i >= limit:
                break
            author = c.commit.author
            out.append(
                {
                    "sha": c.sha[:7],
                    "message": (c.commit.message or "").splitlines()[0][:120],
                    "author": author.name if author else "",
                    "date": author.date.isoformat() if author else "",
                }
            )
        return {"repo": repo, "branch": branch, "commits": out, "count": len(out)}
    except GithubException as e:
        raise ValueError(f"GitHub {e.status}: {e.data}") from e


@tool(
    name="list_prs",
    description="List pull requests for a repository.",
    schema={
        "type": "object",
        "properties": {
            "repo": {"type": "string"},
            "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
        },
        "required": ["repo"],
    },
)
async def list_prs(repo: str, state: str = "open") -> dict[str, Any]:
    if state not in {"open", "closed", "all"}:
        raise ValueError(f"invalid state: {state}")
    try:
        r = _gh().get_repo(_full_name(repo))
        prs: list[dict[str, Any]] = []
        for pr in r.get_pulls(state=state):
            prs.append(
                {
                    "number": pr.number,
                    "title": pr.title[:120],
                    "author": pr.user.login if pr.user else "",
                    "branch": pr.head.ref if pr.head else "",
                    "created_at": pr.created_at.isoformat() if pr.created_at else "",
                }
            )
        return {"repo": repo, "state": state, "prs": prs, "count": len(prs)}
    except GithubException as e:
        raise ValueError(f"GitHub {e.status}: {e.data}") from e


@tool(
    name="list_files",
    description="Check which key files (Dockerfile, package.json, etc.) exist in a branch.",
    schema={
        "type": "object",
        "properties": {
            "repo": {"type": "string"},
            "branch": {"type": "string", "default": "main"},
            "patterns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["repo"],
    },
)
async def list_files(
    repo: str,
    branch: str = "main",
    patterns: list[str] | None = None,
) -> dict[str, Any]:
    patterns_list = patterns if patterns else list(DEFAULT_FILE_PATTERNS)
    try:
        r = _gh().get_repo(_full_name(repo))
        present: list[dict[str, Any]] = []
        missing: list[str] = []
        for pat in patterns_list:
            try:
                content = r.get_contents(pat, ref=branch)
            except GithubException as e:
                if e.status == 404:
                    missing.append(pat)
                    continue
                raise
            if isinstance(content, list):
                # path was a directory — skip
                continue
            present.append({"path": content.path, "size": content.size, "sha": content.sha[:7]})
        return {"repo": repo, "branch": branch, "present": present, "missing": missing}
    except GithubException as e:
        raise ValueError(f"GitHub {e.status}: {e.data}") from e


@tool(
    name="refresh_cache",
    description="Force a full refresh of the GitHub repo/branch cache.",
    schema={"type": "object", "properties": {}, "required": []},
)
async def refresh_cache() -> dict[str, Any]:
    t0 = monotonic()
    await cache.refresh()
    elapsed_ms = int((monotonic() - t0) * 1000)
    return {
        "owner": settings.GITHUB_ORG,
        "owner_kind": cache.owner_kind,
        "repo_count": len(cache.repos),
        "elapsed_ms": elapsed_ms,
        "refreshed_at": cache.last_refresh.isoformat() if cache.last_refresh else None,
    }
