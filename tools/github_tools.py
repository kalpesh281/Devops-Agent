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

# The ONLY hard blockers for `/deploy`. ``deploy.config.yml`` is the agent's
# manifest (name, port, target_server, image); ``Dockerfile`` is needed to
# build the image. Everything else is informational.
_CRITICAL_FILES: tuple[str, ...] = ("deploy.config.yml", "Dockerfile")

# Advisory — we don't block deploys on these, but we loudly flag them so
# secret-leakage doesn't creep into images.
_ADVISORY_FILES: tuple[str, ...] = (".dockerignore",)

# Stack detection. Each stack lists every marker file that proves it,
# in *display-priority order* (the first one found becomes ``stack_marker``).
#
# The order of this dict matters — earlier entries win when a repo has
# markers from multiple stacks. Rationale:
#   - ``flutter`` before ``node`` because a Flutter project often contains
#     a ``node_modules/`` helper tree with package.json, but pubspec.yaml is
#     a stronger signal.
#   - ``node`` before ``python`` because some Python repos keep a small
#     package.json for tooling.
_STACK_MARKERS: dict[str, tuple[str, ...]] = {
    "flutter": ("pubspec.yaml",),
    "gradle": ("build.gradle.kts", "build.gradle"),
    "node": ("package.json",),
    "python": ("pyproject.toml", "requirements.txt"),
    "go": ("go.mod",),
    "rust": ("Cargo.toml",),
    "static": ("index.html",),
}

# Sub-stack labels so the UI can say "Python (Poetry)" vs "Python (pip)".
_SUBSTACK_FROM_MARKER: dict[str, str] = {
    "pyproject.toml": "Poetry",
    "requirements.txt": "pip/venv",
    "build.gradle.kts": "Kotlin DSL",
    "build.gradle": "Groovy DSL",
}

# The full candidate set we probe on GitHub — union of everything above.
_CANDIDATES: tuple[str, ...] = tuple(
    dict.fromkeys(  # dedupe while preserving order
        (
            *_CRITICAL_FILES,
            *_ADVISORY_FILES,
            *(m for markers in _STACK_MARKERS.values() for m in markers),
        )
    )
)

# Kept as a public name for backward-compat with earlier callers that passed
# a custom ``patterns`` list. Mirrors the probe set.
DEFAULT_FILE_PATTERNS: tuple[str, ...] = _CANDIDATES

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


def _detect_stack(present_paths: set[str]) -> tuple[str, str | None, str | None]:
    """Identify the stack from which marker files exist.

    Returns ``(stack, marker, substack)``:

        - ``stack``    — canonical key from ``_STACK_MARKERS`` or ``"unknown"``
        - ``marker``   — first file that proved it (e.g. ``pyproject.toml``)
        - ``substack`` — finer label (e.g. ``"Poetry"``) or ``None``
    """
    for stack, markers in _STACK_MARKERS.items():
        for marker in markers:
            if marker in present_paths:
                return stack, marker, _SUBSTACK_FROM_MARKER.get(marker)
    return "unknown", None, None


@tool(
    name="list_files",
    description="Check deploy-critical files on a branch, stack-aware (node/python/unknown).",
    schema={
        "type": "object",
        "properties": {
            "repo": {"type": "string"},
            "branch": {"type": "string", "default": "main"},
            "path": {
                "type": "string",
                "default": ".",
                "description": "Subfolder to check (monorepo support). Default '.' = repo root.",
            },
        },
        "required": ["repo"],
    },
)
async def list_files(
    repo: str,
    branch: str | None = None,
    path: str = ".",
) -> dict[str, Any]:
    """Probe the candidate files on GitHub, detect stack, return per-bucket status.

    Return shape::

        {
          "repo": "trading-dashboard",
          "branch": "main",
          "stack": "node" | "python" | "unknown",
          "required": [{"path", "present", "size"}],   # stack-specific + critical
          "advisory": [{"path", "present", "size"}],   # .dockerignore etc.
          "deploy_ready": bool,
          "missing_required": ["deploy.config.yml", ...],
        }

    A Python repo missing ``package.json`` is NOT flagged — only files that
    matter for the detected stack are ever called missing.
    """
    # Normalise the subfolder path. Reject ".." BEFORE any stripping so the
    # user can't smuggle it in as "./../etc" or similar.
    raw = path.strip()
    if ".." in raw.replace("\\", "/").split("/"):
        raise ValueError(f"invalid path: {path!r} (no ..)")
    folder = raw.strip("/")
    if folder.startswith("./"):
        folder = folder[2:]
    folder = folder or "."

    def _full(pat: str) -> str:
        return pat if folder == "." else f"{folder}/{pat}"

    try:
        r = _gh().get_repo(_full_name(repo))
        # Fall back to the repo's actual default branch (might be "main",
        # "master", "develop", or a per-team convention like "new-backend").
        if not branch:
            branch = r.default_branch
        # Probe every candidate once. Store size + presence for each.
        probe: dict[str, dict[str, Any] | None] = {}
        for pat in _CANDIDATES:
            try:
                content = r.get_contents(_full(pat), ref=branch)
            except GithubException as e:
                if e.status == 404:
                    probe[pat] = None
                    continue
                raise
            if isinstance(content, list):
                # Path resolved to a directory — treat as not-a-file.
                probe[pat] = None
                continue
            probe[pat] = {"size": content.size, "sha": content.sha[:7]}

        present_paths: set[str] = {p for p, v in probe.items() if v is not None}
        stack, stack_marker, substack = _detect_stack(present_paths)

        def _entry(path: str) -> dict[str, Any]:
            v = probe.get(path)
            return {
                "path": path,
                "present": v is not None,
                "size": (v or {}).get("size", 0),
            }

        # Hard blockers only — deploy.config.yml + Dockerfile. Stack markers
        # are informational (reported separately below), never required.
        required = [_entry(p) for p in _CRITICAL_FILES]
        advisory = [_entry(p) for p in _ADVISORY_FILES]

        missing_required = [item["path"] for item in required if not item["present"]]
        deploy_ready = not missing_required

        return {
            "repo": repo,
            "branch": branch,
            "path": folder,
            "stack": stack,
            "stack_marker": stack_marker,
            "substack": substack,
            "required": required,
            "advisory": advisory,
            "deploy_ready": deploy_ready,
            "missing_required": missing_required,
        }
    except GithubException as e:
        raise ValueError(f"GitHub {e.status}: {e.data}") from e


@tool(
    name="list_services",
    description=(
        "Discover every deployable service in a repo by scanning for deploy.config.yml files. "
        "Works for both single-service repos and monorepos."
    ),
    schema={
        "type": "object",
        "properties": {
            "repo": {"type": "string"},
            "branch": {"type": "string", "default": "main"},
        },
        "required": ["repo"],
    },
)
async def list_services(repo: str, branch: str | None = None) -> dict[str, Any]:
    """Walk the repo tree; report services + top-level layout.

    Returns a single payload covering both:

    * ``services``   — every ``deploy.config.yml`` discovered in the tree
      (``path``, ``name``, ``config_path``).
    * ``root_folders`` / ``root_files`` — what's at the top level of the
      repo, so the caller can render a "directory preview" without showing
      a full tree.
    * ``folders_with_config`` — the subset of top-level folders whose
      subtree contains a ``deploy.config.yml``. Used to highlight which
      folders are deploy-ready in the message.
    """
    try:
        r = _gh().get_repo(_full_name(repo))
        if not branch:
            branch = r.default_branch
        branch_obj = r.get_branch(branch)
        tree = r.get_git_tree(branch_obj.commit.sha, recursive=True)

        services: list[dict[str, Any]] = []
        root_folders_set: set[str] = set()
        root_files: list[str] = []
        folders_with_config: set[str] = set()

        for entry in tree.tree:
            path = entry.path
            if not path:
                continue

            # Top-level entries (no "/" in the path)
            if "/" not in path:
                if entry.type == "tree":
                    root_folders_set.add(path)
                elif entry.type == "blob":
                    root_files.append(path)

            # Find every deploy.config.yml anywhere in the repo
            if entry.type == "blob" and path.endswith("deploy.config.yml"):
                if "/" not in path:
                    folder = "."
                    name = repo
                else:
                    folder = path.rsplit("/", 1)[0]
                    name = folder.rsplit("/", 1)[-1]
                    # Which top-level folder contains this service?
                    folders_with_config.add(path.split("/", 1)[0])
                services.append(
                    {
                        "path": folder,
                        "name": name,
                        "config_path": path,
                    }
                )

        services.sort(key=lambda s: (s["path"] != ".", s["path"]))
        return {
            "repo": repo,
            "branch": branch,
            "services": services,
            "count": len(services),
            "root_folders": sorted(root_folders_set),
            "root_files": sorted(root_files),
            "folders_with_config": sorted(folders_with_config),
        }
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
