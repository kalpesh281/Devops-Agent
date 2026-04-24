# Phase 2 — GitHub Layer (Cache + Tool Registry)

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 1 |
| **Blocks** | Phase 3 (commands need tools), Phase 6 (graph needs registry) |
| **Spec references** | `docs/PROJECT_V2.md` §7.3 (tool registry), §8 (GitHub commands), §10.2 (GitHub cache), §10.5 (fuzzy resolver), §14.2 (allow/denylists) |

---

## Objective

Deliver the zero-LLM GitHub layer: a `@tool` registry, a 5-minute background-refreshed repo/branch cache, a rapidfuzz resolver, and six GitHub tools (`list_repos`, `list_branches`, `list_commits`, `list_prs`, `list_files`, `refresh_cache`). All callable via Python — no Telegram wiring yet.

## Design choices

| Choice | Why |
|---|---|
| **`@tool(name, tier, description, schema)` decorator into a single `REGISTRY` dict** | §7.3 — adding a tool is one decorator; the LangGraph graph never changes. |
| **`GitHubCache` accepts either an org OR a personal user account** | `GITHUB_ORG=GradScalerTeam` (confirmed) — but the loader auto-detects and falls back to `get_user(name)` if `get_organization(name)` 404s, so the same code works for later personal-account use. |
| **Background refresh is an asyncio task started in FastAPI lifespan** | §10.2 — polling, not webhooks (webhooks are a v3 optimization per §25). |
| **Cache kept in-memory, mirrored opportunistically to `github_cache` collection** | §20 — Mongo mirror is optional; primary path is in-memory for speed. Mongo mirror is only written, never read (except on cold-start fallback). |
| **`fuzzy_resolve` wraps `rapidfuzz.process.extractOne` with a cutoff** | §10.5 — cutoff 60 by default; return `None` if nothing hits, caller formats the "no match" message. |
| **`config/tool_tiers.yml` is loaded at `REGISTRY` init time** | §7.3 + §14.1 — tier assignments are data, not hardcoded. Denylist (`mongo`, `agent`, `traefik`) lives in the same file. |
| **Tools return plain dicts, not HTML** | Formatting is Phase 3's job (`telegram_bot/messages.py`). Tools are transport-agnostic. |

## Deliverables

### Files created

- `tools/registry.py` — `ToolSpec` dataclass, `@tool` decorator, `REGISTRY: dict[str, ToolSpec]`, `load_tier_config()`, `get_tier(name)`, `is_denied(target)`.
- `config/tool_tiers.yml` — `tiers:` map (tool → auto/notify/approval) and `denylist_containers:` list (`mongo`, `agent`, `traefik`).
- `utils/github_cache.py` — `GitHubCache` class per §10.2, org-or-user auto-detection, `start_background_refresh()` task.
- `utils/fuzzy_resolver.py` — `fuzzy_resolve(query, choices, cutoff=60)`, `fuzzy_extract(query, choices, limit=10, cutoff=40)`.
- `tools/github_tools.py` — `list_repos`, `list_branches(repo)`, `list_commits(repo, branch, limit=10)`, `list_prs(repo, state="open")`, `list_files(repo, branch, patterns=[...])`, `refresh_cache()`. All registered via `@tool`.
- `tests/unit/test_registry.py` — decorator registration, tier loading, denylist enforcement.
- `tests/unit/test_github_cache.py` — cache refresh with a mocked `github.Github`.
- `tests/unit/test_fuzzy_resolver.py` — resolver hit, miss, cutoff edge cases.
- `tests/unit/test_github_tools.py` — all six tools against a mocked `github.Github`.

### Folder tree delta

```
tools/
├── __init__.py
├── registry.py          ← new
└── github_tools.py      ← new
utils/
├── github_cache.py      ← new
└── fuzzy_resolver.py    ← new
config/
└── tool_tiers.yml       ← new
tests/unit/
├── test_registry.py
├── test_github_cache.py
├── test_fuzzy_resolver.py
└── test_github_tools.py
```

### Tool tiers this phase adds

| Tool name | Tier | Rationale |
|---|---|---|
| `list_repos` | auto | Read-only |
| `list_branches` | auto | Read-only |
| `list_commits` | auto | Read-only |
| `list_prs` | auto | Read-only |
| `list_files` | auto | Read-only |
| `refresh_cache` | auto | Idempotent, read-only side effect |

## Verification

```bash
# 1. Unit tests — everything mocked, no network
make test
# expect: >= 15 tests passing

# 2. Tool registry populated
.venv/bin/python -c "
from tools import github_tools
from tools.registry import REGISTRY
print(list(REGISTRY.keys()))
"
# expect: ['list_repos', 'list_branches', 'list_commits', 'list_prs', 'list_files', 'refresh_cache']

# 3. Tier lookup works
.venv/bin/python -c "
from tools import github_tools
from tools.registry import get_tier
print(get_tier('list_repos'))
"
# expect: 'auto'

# 4. Denylist enforced
.venv/bin/python -c "
from tools.registry import is_denied
print(is_denied('mongo'), is_denied('trading-dashboard'))
"
# expect: True False

# 5. Live cache smoke-test (needs real GITHUB_TOKEN + GITHUB_ORG)
.venv/bin/python -c "
import asyncio
from utils.github_cache import cache
asyncio.run(cache.refresh())
print(f'repos: {len(cache.repos)}')
print(f'first 3: {cache.repos[:3]}')
"
# expect: repos: 42 (matches GradScalerTeam screenshot)

# 6. Fuzzy resolver smoke
.venv/bin/python -c "
from utils.fuzzy_resolver import fuzzy_resolve
print(fuzzy_resolve('trding', ['trading-dashboard', 'portfolio-site']))
"
# expect: ('trading-dashboard', <score>)

# 7. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [ ] All 15+ unit tests green
- [ ] `REGISTRY` contains all six tools after `import tools.github_tools`
- [ ] Tier lookup returns correct tier for every tool (no `KeyError`)
- [ ] Denylist rejects `mongo`, `agent`, `traefik`; accepts anything else
- [ ] Live `cache.refresh()` populates `cache.repos` from `GradScalerTeam`
- [ ] Background refresh task starts on app lifespan (logs `cache.refreshed`)
- [ ] `fuzzy_resolve` returns `None` on empty choices, tuple on hit, `None` below cutoff
- [ ] `make lint` + `make typecheck` clean

## What this phase does NOT do

- No Telegram command wiring (Phase 3)
- No LangGraph integration (Phase 6)
- No write-side GitHub operations (the spec is deploy-oriented; we don't edit repos)
- No cache invalidation via webhooks (v3 per §25)

## Rollback

```bash
rm -rf tools/registry.py tools/github_tools.py \
       utils/github_cache.py utils/fuzzy_resolver.py \
       config/tool_tiers.yml \
       tests/unit/test_registry.py tests/unit/test_github_cache.py \
       tests/unit/test_fuzzy_resolver.py tests/unit/test_github_tools.py
```

## Open questions

- None. `GradScalerTeam` is the org; fallback-to-user is belt-and-suspenders for future repos.
