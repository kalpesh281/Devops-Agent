# DevOps AI Agent — v2 (Production-Hardened)

A conversational AI agent (Discord bot) that manages GitHub repositories and Docker deployments across multiple servers — your physical server plus client-specific AWS EC2 instances. Built with LangGraph, FastAPI, OpenAI GPT-5.4-nano, and the Docker SDK.

**Design philosophy:** AI-enabled, not AI-dependent. Core features (listing, deploying, logs, diagnostics, rollback) use zero LLM calls. AI is a set of opt-in features layered on top — free-text chat, pre-deploy config analysis, and on-demand root-cause hypothesis. You can disable all AI with config flags and the tool still works end-to-end.

This document supersedes `PROJECT_V1.md`.

---

## 1. What this is

You chat with the bot. It does the DevOps.

```
You: /deploy repo:trading-dashboard branch:main
Bot: 🚀 Deploying trading-dashboard:main
     ✅ Cloned (1s)
     ✅ Built (12s)
     ✅ Pushed to Docker Hub (4s)
     ✅ Pulled on physical-main (2s)
     ✅ Running → http://your-server:4001
     ✅ Cleaned up 3 old images (1.2 GB freed)
     Total: 22s

You: /report trading-dashboard
Bot: 🟡 trading-dashboard — Running with errors
     Uptime: 2h 14m    Restarts: 0    Memory: 340/512 MB
     ⚠️ 47 errors (42x MongoDB timeout, 3x unhandled rejection)
     Issues: MongoDB timeouts detected — check mongo health
     [Explain with AI] [View raw logs] [Restart]

You: click "Explain with AI"
Bot: 🤖 AI Analysis — trading-dashboard
     The container is running but experiencing frequent MongoDB timeouts.
     The pattern suggests the mongo container is unhealthy.
     Recommended: /report mongo → if unhealthy, /restart mongo
     GPT-5.4-nano • 247 tokens • ~$0.0001
```

---

## 2. Goals & Non-Goals

### Goals (v2)
- Single-user (you) personal DevOps agent, controlled via Discord
- **Multi-target deployment**: physical server + N client AWS EC2 instances
- Slash commands with fuzzy-matched autocomplete over a cached repo/branch list (0 tokens)
- Build → Push → Pull → Run pipeline using Docker Hub
- `/rollback`, `/images`, `/remove-images` — full image lifecycle management
- Layer 1 diagnostics: `docker inspect` + `docker logs` → structured markdown reports (0 tokens)
- Layer 2 on-demand AI hypothesis via `/explain` (~250 tokens/call)
- Free-text chat as optional fallback (~230 tokens/call)
- Pre-deploy Dockerfile + config check (optional, ~550 tokens/deploy)
- Tiered authorization: auto / notify / approval
- LangGraph human-in-the-loop interrupts for destructive operations
- Structured audit log in Mongo (actor, action, tier, result, duration)
- LangGraph Mongo checkpointing (resume across restarts)
- Auto-cleanup of unused Docker images after every deploy
- Container hardening defaults (read-only FS, cap-drop, resource limits)
- Discord UI layer: color-coded Embeds, paginated logs, button interactions
- `deploy.config.yml` schema validation with friendly error messages
- `.env` startup security check
- Tests + CI + docs + demo asset

### Non-Goals (v3+)
- Multi-user / multi-tenant
- Web dashboard (Discord-only for v2)
- Custom domains + SSL automation
- Kubernetes
- Auto-scaling
- Multi-region failover
- Encrypted PEM at rest (plaintext-in-folder is the v2 model)

---

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Fits FastAPI + LangGraph |
| API framework | **FastAPI** | Async, exposes `/health` and `/metrics` |
| Environment | **Plain `venv`** | `python -m venv .venv` — no Poetry/uv/Pipenv |
| Dep mgmt | **`pyproject.toml`** (PEP 621) | Used with plain `pip install -e .` |
| Agent framework | **LangGraph 1.0+** | Multi-node graph, tool calling, HITL, Mongo checkpointing |
| LLM | **OpenAI GPT-5.4-nano** | Cheap intent parsing + pre-deploy review + `/explain` |
| GitHub client | **PyGithub** | Covers all read endpoints |
| Docker client | **`docker` SDK for Python** | Native Docker context support |
| Discord client | **discord.py 2.x** | Slash commands + autocomplete + buttons + Embeds |
| Fuzzy matching | **rapidfuzz** | C-accelerated fuzzy matching for autocomplete |
| UI helpers | **tabulate**, **rich** | ASCII tables + rich text rendering |
| Database | **MongoDB** + `motor` | State, audit log, checkpoints |
| Tests | **pytest** + `pytest-asyncio` | Unit + integration + eval |
| Lint/Format | **ruff** | Single tool, fast |
| Type check | **mypy** | Enforced in CI |
| Image registry | **Docker Hub** | One auth, works from any target |
| Image build | **BuildKit** (`DOCKER_BUILDKIT=1`) | Cache reuse across deploys |

---

## 4. Architecture

```
                    ┌─────────────┐
                    │  Discord    │
                    │  (you chat) │
                    └──────┬──────┘
                           │
                           ▼
                  ┌──────────────────┐         ┌──────────────────┐
                  │  Discord bot     │────────▶│  GitHub API      │
                  │  discord.py      │  cache  │  (PyGithub)      │
                  │                  │         └──────────────────┘
                  │  • Slash cmds    │
                  │    (autocomplete)│         ┌──────────────────┐
                  │  • Buttons       │────────▶│  OpenAI          │
                  │  • Embeds        │ opt-in  │  GPT-5.4-nano    │
                  │  • Paginators    │         └──────────────────┘
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  LangGraph       │
                  │  agent           │
                  │                  │
                  │  Tools (tiered): │
                  │  • github_*      │
                  │  • docker_*      │
                  │  • server_*      │
                  │  • diagnose_*    │
                  │  • image_*       │
                  └────────┬─────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
   ┌──────────────┐ ┌────────────┐ ┌──────────────┐
   │ MongoDB      │ │ Docker Hub │ │ FastAPI      │
   │ - servers    │ │ (registry) │ │ - /health    │
   │ - deployments│ └─────┬──────┘ │ - /metrics   │
   │ - audit_log  │       │        └──────────────┘
   │ - checkpoints│       │
   │ - diagnostics│       │ pull (by target)
   │ - github_    │       │
   │   cache      │       ▼
   └──────────────┘  ┌─────────────────────────────────────────────┐
                     │ Target servers (resolved per deploy):       │
                     │  ┌─────────────────┐  ┌─────────────────┐   │
                     │  │ physical-main   │  │ client-acme-prod│   │
                     │  │ (your server)   │  │ (AWS EC2)       │   │
                     │  │ Docker daemon   │  │ Docker daemon   │   │
                     │  └─────────────────┘  └─────────────────┘   │
                     └─────────────────────────────────────────────┘
```

---

## 5. Multi-Target Deployment Model

### 5.1 Server registry

A YAML file `secrets/servers.yml` (gitignored, mode 600) declares every target host. On agent startup it's loaded and upserted into the Mongo `servers` collection.

```yaml
servers:
  - id: physical-main
    type: physical
    connection: ssh           # "ssh" in dev, "local" in prod
    host: 122.172.241.96
    ssh_user: server
    pem: physical             # → /devops_agent/pem/physical.pem
    labels: [internal, default]

  - id: client-acme-prod
    type: ec2
    connection: ssh
    host: ec2-x.compute.amazonaws.com
    ssh_user: ubuntu
    pem: acme                 # → /devops_agent/pem/acme.pem
    region: ap-south-1
    labels: [client:acme, prod]
```

**No chat command can add or remove servers.** Server registry edits are file-only.

### 5.2 PEM file convention

All SSH keys live in **one fixed folder** on the agent host:

```
/devops_agent/pem/
├── physical.pem         (only needed during local dev)
├── acme.pem
└── foobar.pem
```

Permissions: folder `chmod 700`, files `chmod 600`, owned by the agent user. Gitignored. Each repo's config declares its `project` field; the agent resolves the PEM by lookup: `/devops_agent/pem/<project>.pem`. Missing PEM → fail fast with a clear error.

### 5.3 `deploy.config.yml` (lives in each deployable repo)

```yaml
name: trading-dashboard
project: acme                       # used to find /devops_agent/pem/acme.pem
stack: node                          # node | python | static | custom
build: docker                        # docker | buildpack
port: 3000
target_server: client-acme-prod      # references servers.id
docker_hub:
  image: kalpesh281/trading-dashboard
env_required:
  - API_KEY
  - MONGO_URI
healthcheck: /health
resources:
  memory: 512m
  cpus: "1.0"
```

### 5.4 Build → Push → Pull → Run pipeline

```
[Agent host]                          [Target server]
  git clone --depth 1
  docker build (BuildKit cache) ──► local image
  docker tag (commit-sha + latest)
  docker push ──► Docker Hub  ◄──── docker pull
                                    docker stop + rm old
                                    docker run (with env, ports, limits)
                                    healthcheck
                                    cleanup old images (keep history)
```

### 5.5 Auto-cleanup of unused images

After every successful deploy:

- **Always keep the currently-running image**
- **Always keep everything in `deployments.image_history`** (last 5 tags)
- **Delete older tagged images for the same repo**
- **Prune dangling layers older than 7 days** (`docker image prune --filter "until=168h"`)
- **Never touch images from other repos** — scope is always per-repo
- **Audit-log every deletion**

Manual commands:
- `/cleanup <server>` — manual cleanup pass
- `/disk <server>` — show `docker system df`

---

## 6. Dev vs Prod — same code, two environments

### Phase 1 — Local development on your Mac (weeks 1-3)

Generate an SSH key pair once for your physical server:

```bash
ssh-keygen -t ed25519 -f ./devops-agent-physical -N ""
ssh-copy-id -i ./devops-agent-physical.pub server@122.172.241.96
mkdir -p /devops_agent/pem
mv ./devops-agent-physical /devops_agent/pem/physical.pem
chmod 600 /devops_agent/pem/physical.pem
```

`secrets/servers.yml` uses `connection: ssh` with `pem: physical`.

**Even simpler dev mode:** point `physical-main` at your Mac's Docker Desktop:

```yaml
- id: physical-main
  type: physical
  connection: local
  labels: [dev, internal]
```

### Phase 2 — Production on the physical server (week 4+)

1. SCP / git-clone the agent code onto the physical server
2. SCP each client PEM into `/devops_agent/pem/`
3. **Don't copy `physical.pem`** — agent runs locally on the server now
4. Edit `secrets/servers.yml`: change `physical-main` to `connection: local`
5. Fill `.env` with real tokens
6. `docker compose up -d`

**The only file change between dev and prod:** the `connection` line for `physical-main`. Code, tools, and command structure are unchanged.

---

## 7. LangGraph Agent

### 7.1 Graph diagram

```
         ┌──────────┐
         │  START   │
         └─────┬────┘
               │
               ▼
       ┌───────────────┐
       │ validate_auth │
       └───────┬───────┘
               │
               ▼
       ┌───────────────┐
       │ route_input   │  ← slash command vs free-text
       └───┬───────┬───┘
           │       │
   slash   │       │  free-text
           │       ▼
           │  ┌───────────────┐
           │  │ parse_intent  │  ← LLM call #1 (~230 tokens)
           │  └───────┬───────┘
           │          │
           └──────────┤
                      ▼
              ┌───────────────┐
              │ classify_tier │
              └───────┬───────┘
                      │
                 ┌────┴─────┐
                 ▼          ▼
          ┌───────────┐  ┌──────────────────┐
          │ approval  │  │ pre_deploy_check │  ← LLM call #2 (only for /deploy, ~550)
          │ interrupt │  └─────────┬────────┘
          └─────┬─────┘            │
                │                  │
                └──────────┬───────┘
                           ▼
                  ┌────────────────┐
                  │ execute_tool   │
                  └────────┬───────┘
                           │
                           ▼
                  ┌────────────────┐
                  │ format_response│  ← Discord Embed / templated, no LLM
                  └────────┬───────┘
                           │
                           ▼
                  ┌────────────────┐
                  │ audit_log      │  ← always runs, even on errors
                  └────────┬───────┘
                           │
                           ▼
                        ┌─────┐
                        │ END │
                        └─────┘
```

### 7.2 State

```python
# agents/state.py
from typing import TypedDict, Optional, Literal, Any
from datetime import datetime

class AgentState(TypedDict):
    user_message: str
    discord_user_id: str
    discord_channel_id: str
    trace_id: str

    input_mode: Literal["slash", "free_text"]
    intent: Optional[str]
    intent_args: dict[str, Any]
    tool_name: Optional[str]
    tool_tier: Optional[Literal["auto", "notify", "approval"]]

    pending_approval: bool
    approved: Optional[bool]

    target_server: Optional[str]
    tool_results: list[dict]
    predeploy_warnings: list[str]

    final_response: Optional[str]
    error: Optional[str]

    started_at: datetime
    completed_at: Optional[datetime]
```

### 7.3 Tool registry pattern

```python
# tools/registry.py
from typing import Callable, Literal
from dataclasses import dataclass

Tier = Literal["auto", "notify", "approval"]

@dataclass
class ToolSpec:
    name: str
    func: Callable
    tier: Tier
    description: str
    schema: dict

REGISTRY: dict[str, ToolSpec] = {}

def tool(name: str, tier: Tier, description: str, schema: dict):
    def decorator(func):
        REGISTRY[name] = ToolSpec(name, func, tier, description, schema)
        return func
    return decorator
```

Adding a new tool is one decorator — the graph never changes.

### 7.4 Checkpointer (Mongo-backed, resumable)

```python
# agents/checkpointer.py
from langgraph.checkpoint.mongodb import MongoDBSaver
from utils.mongo import client

def get_checkpointer():
    return MongoDBSaver(
        client=client,
        db_name="devops_agent",
        collection_name="checkpoints",
    )
```

**Memory usage:** each checkpoint ~2-5 KB serialized state. ~8 checkpoints per deploy. ~9 MB/month for 10 deploys/day. Negligible.

**Connection:** reuses the same `motor` client as everything else. No separate connection pool.

**Auto-cleanup:** TTL index purges checkpoints older than 7 days:

```python
# utils/mongo.py (on startup)
await db.checkpoints.create_index("created_at", expireAfterSeconds=604800)
```

**Value for single-user:** deploys are 20-60s. Agent crashes happen (OOM, power, self-redeploy). Checkpointer lets the graph resume from the last completed node after a restart. It's also required for HITL interrupts (`/stop`, `/rollback`, `/remove-images`) to survive agent restarts while waiting for approval.

---

## 8. Commands

### GitHub queries (auto tier, 0 tokens)

| Command | Autocomplete | Action |
|---|---|---|
| `/repos` | — | List repos in org (from cache) |
| `/branches <repo>` | repo | List branches for a repo |
| `/commits <repo> <branch>` | repo, branch | Recent commits (default 10) |
| `/prs <repo>` | repo | Open pull requests |
| `/files <repo> <branch>` | repo, branch | Show key files (Dockerfile, package.json, etc.) |
| `/refresh` | — | Force-refresh the GitHub cache |

### Deployment (notify tier)

| Command | Autocomplete | Action |
|---|---|---|
| `/deploy <repo> <branch>` | repo, branch | Build → push → pull → run → cleanup |
| `/redeploy <name>` | name | Pull latest + restart |
| `/restart <name>` | name | Restart container |
| `/status` | — | Grouped deployments by target server (ASCII table Embed) |
| `/status <server>` | server | Filter by one server |
| `/servers` | — | List registered target servers |
| `/disk <server>` | server | `docker system df` on a target |

### Destructive (approval tier, HITL button)

| Command | Autocomplete | Action |
|---|---|---|
| `/stop <name>` | name | Stop deployment |
| `/rollback <name>` | name | Roll back to previous image (5-6s) |
| `/remove-images <name>` | name | Remove all images except current + previous 1 |
| `/cleanup <server>` | server | Manual image cleanup pass |
| `/delete-deployment <name>` | name | Stop + remove deployment record |

### Diagnostics (auto tier, 0 tokens)

| Command | Autocomplete | Action |
|---|---|---|
| `/logs <name>` | name | Paginated raw logs with ◀️▶️ buttons |
| `/inspect <name>` | name | Parsed `docker inspect` Embed |
| `/health <name>` | name | Uptime + restart count + health status |
| `/report <name>` | name | Full Layer 1 diagnostic Embed (inspect + logs + rules) |
| `/images <name>` | name | List last 5 image versions with buttons |

### AI-powered (opt-in, tokens used)

| Command | Autocomplete | Tokens | Action |
|---|---|---|---|
| `/explain <name>` | name | ~250 | Layer 1 report + LLM hypothesis |

### Identifier resolution (for any `<name>` arg)

Accepts container name, repo name, or project tag. Resolution order:
1. Exact match on `deployments._id` (container name)
2. Exact match on `deployments.repo`
3. Exact match on `deployments.project`
4. Fuzzy substring match → disambiguation picker if multiple hits

---

## 9. Diagnostics (replaces old log summarization)

Two layers — Layer 1 does 90%+ of the work with zero LLM calls. Layer 2 is opt-in.

### 9.1 Layer 1 — Pure code, offline-capable, 0 tokens

Runs on every `/logs`, `/inspect`, `/health`, `/report`. Sub-second, works when OpenAI is down.

**From `docker inspect`** — parsed to structured data:

```python
# utils/docker_diagnostics.py
EXIT_CODE_MEANINGS = {
    0:   "clean exit",
    1:   "application error",
    125: "docker daemon error",
    126: "command not executable",
    127: "command not found",
    137: "SIGKILL (OOM or manual kill)",
    139: "segfault",
    143: "SIGTERM (graceful shutdown)",
}

def inspect_diagnose(inspect_data: dict) -> dict:
    state = inspect_data["State"]
    return {
        "running": state["Running"],
        "exit_code": state["ExitCode"],
        "exit_reason": EXIT_CODE_MEANINGS.get(state["ExitCode"], "unknown"),
        "restart_count": inspect_data["RestartCount"],
        "health_status": state.get("Health", {}).get("Status"),
        "health_failing_streak": state.get("Health", {}).get("FailingStreak", 0),
        "started_at": state["StartedAt"],
        "uptime_seconds": compute_uptime(state["StartedAt"]),
        "oom_killed": state.get("OOMKilled", False),
        "memory_limit_mb": inspect_data["HostConfig"]["Memory"] / 1024 / 1024,
    }
```

**From `docker logs`** — regex + clustering + pattern detection:

```python
# utils/log_analyzer.py
import re
from collections import Counter

ERROR_RE = re.compile(r"(ERROR|FATAL|Exception|Traceback|panic|PANIC)", re.I)
WARN_RE  = re.compile(r"(WARN|WARNING)", re.I)

def analyze_logs(log_text: str) -> dict:
    lines = log_text.splitlines()
    errors = [l for l in lines if ERROR_RE.search(l)]
    warns  = [l for l in lines if WARN_RE.search(l)]
    error_types = Counter(_normalize(l) for l in errors)
    return {
        "total_lines": len(lines),
        "error_count": len(errors),
        "warn_count": len(warns),
        "top_errors": error_types.most_common(5),
        "last_error": errors[-1] if errors else None,
        "has_traceback": any("Traceback" in l for l in lines),
        "has_oom": any("out of memory" in l.lower() for l in lines),
        "has_mongo_timeout": any("mongo" in l.lower() and "timeout" in l.lower() for l in lines),
    }

def _normalize(line: str) -> str:
    line = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S*", "<TS>", line)
    line = re.sub(r"\b\d+\.\d+\.\d+\.\d+\b", "<IP>", line)
    line = re.sub(r"\b[0-9a-f]{8,}\b", "<ID>", line)
    return line[:200]
```

**Rule engine** — maps signals to diagnoses:

```python
# utils/report_builder.py
def diagnose(inspect: dict, logs: dict) -> list[str]:
    issues = []
    if inspect["oom_killed"]:
        issues.append("🔴 OOM killed — increase memory limit or fix leak")
    if inspect["restart_count"] > 5:
        issues.append(f"🔴 Restart loop ({inspect['restart_count']} restarts)")
    if inspect["exit_code"] == 137:
        issues.append("🔴 Killed by SIGKILL (likely OOM or manual)")
    if logs["error_count"] > 50:
        issues.append(f"🟡 High error rate: {logs['error_count']} errors")
    if logs["has_mongo_timeout"]:
        issues.append("🟡 MongoDB timeouts — check mongo container")
    if logs["has_traceback"]:
        issues.append("🟡 Unhandled exceptions (tracebacks) in logs")
    return issues
```

### 9.2 Layer 2 — Opt-in LLM hypothesis (`/explain`)

Triggered ONLY when user explicitly runs `/explain <name>`. The LLM receives the **Layer 1 structured summary**, not raw logs — keeping input tokens ~150 instead of ~6000.

```python
# tools/explain_tool.py
async def explain(name: str) -> str:
    # Layer 1 first (free)
    report = build_report(inspect, logs)

    prompt = f"""Given this container diagnostic report, suggest the most likely
root cause and next action. Be specific. No fluff.

{report}"""

    response = await openai.chat.completions.create(
        model="gpt-5.4-nano",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
    )
    return response.choices[0].message.content
```

**Tokens:** ~150 input + ~100 output = ~250 total per call.

---

## 10. Slash Command Autocomplete + Fuzzy Resolution

### 10.1 The insight

Discord slash commands support **live autocomplete** per argument. As you type, the bot returns matching suggestions. Zero LLM calls. Everything is fuzzy-matched against an in-memory cache.

### 10.2 GitHub cache (background-refreshed every 5 min)

```python
# utils/github_cache.py
class GitHubCache:
    def __init__(self):
        self.gh = Github(settings.GITHUB_TOKEN)
        self.repos: list[str] = []
        self.branches: dict[str, list[str]] = {}
        self.last_refresh: datetime | None = None

    async def refresh(self):
        org = self.gh.get_organization(settings.GITHUB_ORG)
        new_repos, new_branches = [], {}
        for repo in org.get_repos():
            new_repos.append(repo.name)
            new_branches[repo.name] = [b.name for b in repo.get_branches()]
        self.repos = new_repos
        self.branches = new_branches
        self.last_refresh = datetime.utcnow()

    async def start_background_refresh(self, interval_seconds: int = 300):
        while True:
            try:
                await self.refresh()
            except Exception as e:
                logger.error(f"Cache refresh failed: {e}")
            await asyncio.sleep(interval_seconds)

cache = GitHubCache()
```

### 10.3 Fuzzy autocomplete handlers

```python
# discord_bot/commands.py
from rapidfuzz import process
from utils.github_cache import cache

@deploy_cmd.autocomplete("repo")
async def repo_autocomplete(interaction, current: str):
    if not current:
        return [app_commands.Choice(name=r, value=r) for r in cache.repos[:25]]
    matches = process.extract(current, cache.repos, limit=25)
    return [
        app_commands.Choice(name=name, value=name)
        for name, score, _ in matches if score > 40
    ]

@deploy_cmd.autocomplete("branch")
async def branch_autocomplete(interaction, current: str):
    repo = interaction.namespace.repo
    if not repo or repo not in cache.branches:
        return []
    branches = cache.branches[repo]
    if not current:
        return [app_commands.Choice(name=b, value=b) for b in branches[:25]]
    matches = process.extract(current, branches, limit=25)
    return [
        app_commands.Choice(name=name, value=name)
        for name, score, _ in matches if score > 40
    ]
```

**All entity arguments get autocomplete:** repo, branch, deployment name, server, PEM project. Everything reads from cached data + rapidfuzz.

### 10.4 Three input modes (all coexist)

| Mode | Trigger | Tokens | Latency |
|---|---|---|---|
| **Slash + autocomplete** | `/deploy repo:tra...` | 0 | ~instant |
| **Slash typed fast** | `/deploy trading-dashboard main` | 0 | ~instant |
| **Free-text chat** | "deploy the trading dashboard" | ~230 | ~1-2s |

---

## 11. Discord UI Layer

Pure `discord.py 2.x` components + `tabulate` for tables. No extra Discord UI libraries.

### 11.1 Color palette (consistent across the bot)

```python
# discord_bot/colors.py
class Colors:
    SUCCESS = 0x34C759   # green
    WARNING = 0xFFCC00   # yellow
    ORANGE  = 0xFF9500   # orange
    ERROR   = 0xFF3B30   # red
    INFO    = 0x5865F2   # Discord blurple
    AI      = 0x9B59B6   # purple (LLM output)
    MUTED   = 0x8E8E93   # grey
```

### 11.2 `/report` — color-coded diagnostic Embed

```python
# discord_bot/embeds.py
def build_report_embed(inspect: dict, logs: dict, name: str) -> discord.Embed:
    if not inspect["running"]:
        color, icon, status = Colors.ERROR, "🔴", f"Stopped (exit {inspect['exit_code']})"
    elif inspect["restart_count"] > 5:
        color, icon, status = Colors.ORANGE, "🟠", f"Unstable ({inspect['restart_count']} restarts)"
    elif logs["error_count"] > 10:
        color, icon, status = Colors.WARNING, "🟡", "Running with errors"
    else:
        color, icon, status = Colors.SUCCESS, "🟢", "Healthy"

    embed = discord.Embed(title=f"{icon} {name}", description=f"**Status:** {status}", color=color)
    embed.add_field(name="Target", value=f"`{inspect['target_server']}`", inline=True)
    embed.add_field(name="Uptime", value=format_uptime(inspect["uptime_seconds"]), inline=True)
    embed.add_field(name="Restarts", value=str(inspect["restart_count"]), inline=True)
    embed.add_field(name="Memory", value=f"{inspect['memory_mb']}/{inspect['memory_limit_mb']} MB", inline=True)
    embed.add_field(name="CPU", value=f"{inspect['cpu_pct']:.1f}%", inline=True)
    embed.add_field(name="Health", value=inspect.get("health_status", "—"), inline=True)

    if logs["error_count"] > 0:
        top = "\n".join(f"• **{c}x** `{e[:80]}`" for e, c in logs["top_errors"][:3])
        embed.add_field(name=f"⚠️ Errors ({logs['error_count']})", value=top, inline=False)

    embed.set_footer(text=f"Layer 1 • {inspect['duration_ms']}ms • 0 tokens")
    return embed
```

Buttons at the bottom: `[Explain with AI]`, `[View raw logs]`, `[Restart]`.

### 11.3 `/logs` — paginated with button navigation

```python
# discord_bot/views.py
class LogsPaginator(discord.ui.View):
    def __init__(self, log_lines: list[str], name: str, page_size: int = 40):
        super().__init__(timeout=300)
        self.pages = [log_lines[i:i+page_size] for i in range(0, len(log_lines), page_size)]
        self.current = 0
        self.name = name
        self._update_buttons()

    def render(self) -> str:
        page = self.pages[self.current]
        return (
            f"**Logs — {self.name}** (page {self.current+1}/{len(self.pages)})\n"
            f"```log\n" + "\n".join(page) + "\n```"
        )

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def first(self, interaction, button):
        self.current = 0
        self._update_buttons()
        await interaction.response.edit_message(content=self.render(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def prev(self, interaction, button):
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(content=self.render(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def next(self, interaction, button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(content=self.render(), view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def last(self, interaction, button):
        self.current = len(self.pages) - 1
        self._update_buttons()
        await interaction.response.edit_message(content=self.render(), view=self)
```

### 11.4 `/status` — ASCII table via `tabulate`

```python
from tabulate import tabulate

def build_status_message(deployments: list[dict]) -> str:
    rows = [[
        d["name"],
        d["target_server"],
        "🟢" if d["running"] else "🔴",
        format_uptime(d["uptime_seconds"]),
        str(d["restart_count"]),
        d["image"].split(":")[-1][:8],
    ] for d in deployments]
    headers = ["Name", "Server", "Status", "Uptime", "⟳", "Image"]
    table = tabulate(rows, headers=headers, tablefmt="simple")
    return f"**Deployments ({len(deployments)})**\n```\n{table}\n```"
```

### 11.5 `/images` — Embed + management buttons

```python
def build_images_embed(images: list[dict], name: str):
    embed = discord.Embed(title=f"📦 Images for {name}", color=Colors.INFO)
    for i, img in enumerate(images):
        marker = "▸ **current**" if i == 0 else "  previous" if i == 1 else "  old"
        embed.add_field(
            name=img["tag"][:12],
            value=f"{marker}\nDeployed {time_ago(img['deployed_at'])}\nSize: {img['size_mb']} MB",
            inline=True,
        )
    return embed, ImageManagementView(name, images)


class ImageManagementView(discord.ui.View):
    def __init__(self, name: str, images: list[dict]):
        super().__init__(timeout=180)
        self.name, self.images = name, images

    @discord.ui.button(label="Remove old", style=discord.ButtonStyle.danger, emoji="🗑")
    async def remove_old(self, interaction, button):
        # → triggers /remove-images flow with confirmation
        ...

    @discord.ui.button(label="Rollback", style=discord.ButtonStyle.primary, emoji="↩")
    async def rollback(self, interaction, button):
        # → triggers /rollback flow
        ...
```

### 11.6 Deploy — single self-updating message

For long operations, the agent edits one message as each step completes instead of spamming the channel:

```python
async def deploy_with_streaming(interaction, repo, branch):
    msg = await interaction.followup.send(embed=deploy_embed("🔄 Cloning repo...", Colors.INFO))
    await clone(repo, branch)
    await msg.edit(embed=deploy_embed("✅ Cloned\n🔄 Building image...", Colors.INFO))
    await build(...)
    await msg.edit(embed=deploy_embed("✅ Cloned\n✅ Built (12s)\n🔄 Pushing...", Colors.INFO))
    # ... and so on, final edit turns green
    await msg.edit(embed=deploy_embed(
        "✅ Cloned (1s)\n"
        "✅ Built (12s)\n"
        "✅ Pushed (4s)\n"
        "✅ Pulled on physical-main (2s)\n"
        "✅ Running → http://server:4001\n"
        "**Total: 22s**",
        color=Colors.SUCCESS,
    ))
```

### 11.7 `/explain` — purple AI Embed

```python
def build_explain_embed(report: dict, llm_analysis: str, tokens_used: int):
    embed = discord.Embed(
        title=f"🤖 AI Analysis — {report['name']}",
        description=llm_analysis,
        color=Colors.AI,
    )
    embed.add_field(
        name="📊 Diagnostic data",
        value=f"Errors: **{report['error_count']}** • Restarts: **{report['restart_count']}** • Exit: **{report['exit_code']}**",
        inline=False,
    )
    embed.set_footer(text=f"GPT-5.4-nano • {tokens_used} tokens • ~${tokens_used * 0.00005 / 1000:.4f}")
    return embed
```

---

## 12. Token Budget (Profile B — slash-first)

### 12.1 Where tokens are actually used

| Stage | When | In | Out | Total |
|---|---|---|---|---|
| Free-text intent parser | Only if user types in chat (not slash) | ~200 | ~30 | ~230 |
| Pre-deploy config check | Once per `/deploy`, optional flag | ~400 | ~150 | ~550 |
| `/explain` | Only when user runs it, opt-in | ~150 | ~100 | ~250 |

**Everything else uses 0 tokens:** slash commands, autocomplete, status, logs, inspect, report, images, rollback, response formatting, errors, approvals.

### 12.2 Realistic daily usage (Profile B)

| Activity | Count/day | Tokens each | Subtotal |
|---|---|---|---|
| Slash commands (autocompleted) | 30 | 0 | 0 |
| Free-text chat (rare) | 2 | 230 | 460 |
| `/deploy` with pre-check | 5 | 550 | 2,750 |
| `/explain` | 2 | 250 | 500 |
| **Daily total** | | | **~3,700** |
| **Monthly** | | | **~110K** |
| **Cost** (GPT-5.4-nano) | | | **~$0.02/month** |

### 12.3 Bounded input (prevent runaway cost)

```python
# config/token_limits.py
TOKEN_BUDGETS = {
    "intent_parse": 1000,   # hard cap per free-text call
    "predeploy":    2000,   # hard cap on Dockerfile + config check
    "explain":      800,    # hard cap including Layer 1 summary
}
```

If any call's estimated input exceeds its budget, truncate before sending.

---

## 13. Optional AI Toggles

Every AI feature is flag-controlled. Set all three to `False` and the agent runs **completely without an LLM**. Core features still work.

```python
# config/settings.py
class Settings(BaseSettings):
    ENABLE_FREE_TEXT_CHAT: bool = True           # disable → slash-only mode
    ENABLE_PREDEPLOY_ANALYSIS: bool = True       # disable → skip LLM before deploys
    ENABLE_EXPLAIN_COMMAND: bool = True          # disable → remove /explain command
```

```
CORE FEATURES (always-on, 0 tokens)
├── GitHub listing via API + cache
├── Slash command autocomplete (rapidfuzz)
├── Deploy pipeline (build, push, pull, run)
├── Multi-server management
├── Layer 1 diagnostics (inspect + logs + rules)
├── Templated Discord UI (Embeds, tables, paginators)
├── Rollback + image management
├── Audit log + checkpointing
└── Everything else

OPTIONAL AI FEATURES (flag-controlled)
├── Free-text chat intent parsing
├── Pre-deploy Dockerfile analysis
└── /explain root-cause hypothesis
```

---

## 14. Security

### 14.1 Tiered authorization

| Tier | Examples | Behavior |
|---|---|---|
| **auto** | GitHub queries, logs, report, inspect, status, health, images | Execute immediately |
| **notify** | deploy, restart, redeploy | Execute, post notification card |
| **approval** | stop, rollback, remove-images, cleanup, delete-deployment | HITL interrupt → Discord button → resume |

### 14.2 Allow / deny lists

- **Allowlist**: Discord user IDs that may issue commands
- **Allowlist**: GitHub orgs / repos the agent may touch
- **Denylist**: container names that may never be stopped/deleted via chat (`mongo`, `agent`, `traefik`)
- **Denylist**: host paths that may not be mounted into deployed containers

### 14.3 `.env` secrets (confirmed simple approach)

Secrets live in plain `.env` on the agent host alongside the PEM folder:

- `.env` is mode 600, gitignored, never copied to Docker images (`.dockerignore`)
- `.env.example` is committed with placeholder values
- Startup check validates file permissions and warns loudly if too permissive

```python
# utils/secrets_check.py
import os, stat
from pathlib import Path

def verify_env_security():
    env_path = Path(".env")
    if not env_path.exists():
        raise RuntimeError(".env missing — see .env.example")

    mode = env_path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(
            f".env has permissive permissions ({oct(mode)}). "
            "Run: chmod 600 .env"
        )

    # Also check /devops_agent/pem/ permissions
    pem_dir = Path("/devops_agent/pem")
    if pem_dir.exists():
        pem_mode = pem_dir.stat().st_mode
        if pem_mode & (stat.S_IRWXG | stat.S_IRWXO):
            logger.warning(f"/devops_agent/pem has permissive permissions ({oct(pem_mode)}).")
```

### 14.4 `deploy.config.yml` schema validation

Every deploy starts with a strict Pydantic validation pass. Invalid configs fail fast with a friendly Discord message.

```python
# config/deploy_config_schema.py
from pydantic import BaseModel, Field, ValidationError
from typing import Literal

class DockerHubConfig(BaseModel):
    image: str = Field(..., description="Docker Hub repo, e.g. kalpesh281/foo")

class ResourceLimits(BaseModel):
    memory: str = "512m"
    cpus: str = "1.0"

class DeployConfig(BaseModel):
    name: str
    project: str = "internal"
    stack: Literal["node", "python", "static", "custom"]
    build: Literal["docker"] = "docker"
    port: int = Field(gt=0, lt=65536)
    target_server: str
    docker_hub: DockerHubConfig
    env_required: list[str] = []
    healthcheck: str = "/health"
    resources: ResourceLimits = ResourceLimits()

    model_config = {"extra": "forbid"}   # unknown fields = error
```

**Error formatter posts friendly messages to Discord:**

```python
async def validate_deploy_config(yaml_text: str):
    try:
        data = yaml.safe_load(yaml_text)
        return DeployConfig.model_validate(data), None
    except yaml.YAMLError as e:
        return None, f"⚠️ Invalid YAML syntax:\n```\n{e}\n```"
    except ValidationError as e:
        errors = []
        for err in e.errors():
            field = ".".join(str(p) for p in err["loc"])
            msg = err["msg"]
            # "did you mean" via rapidfuzz for unknown fields
            if err["type"] == "extra_forbidden":
                closest = process.extractOne(field, KNOWN_FIELDS)
                if closest and closest[1] > 60:
                    msg += f" (did you mean `{closest[0]}`?)"
            errors.append(f"  • `{field}` — {msg}")
        return None, "⚠️ `deploy.config.yml` has errors:\n" + "\n".join(errors) + \
                     "\n\nFix these and retry the deploy."
```

**Example Discord output:**

```
⚠️ deploy.config.yml has errors:
  • port — Input should be a valid integer, unable to parse 'tree-thousand'
  • target_sever — Extra inputs are not permitted (did you mean `target_server`?)
  • docker_hub.image — Field required

Fix these and retry the deploy.
```

### 14.5 Container hardening defaults

When the agent runs `docker run` it injects:

- `--read-only` root filesystem with writable `tmpfs` at `/tmp`
- `--cap-drop=ALL` then add back only what's needed
- `--security-opt no-new-privileges`
- Resource limits: `--memory`, `--cpus`, `--pids-limit`
- Warns if Dockerfile has no `USER` directive (root container)

### 14.6 Audit log

Every action writes to Mongo `audit_log`:

```json
{
  "timestamp": "2026-04-11T14:22:00Z",
  "actor": "discord:kalpesh#0001",
  "action": "deploy",
  "tool_tier": "notify",
  "target": "trading-dashboard",
  "params": { "branch": "main" },
  "target_server": "physical-main",
  "result": "success",
  "duration_ms": 47000
}
```

---

## 15. Observability

- **Structured audit log** in Mongo (every action: actor, tier, result, duration)
- **Prometheus `/metrics`**: deploys_total, tool_calls_total, llm_tokens_total, container_restarts_total, image_cleanup_total
- **FastAPI `/health`** liveness endpoint
- **Per-deployment healthchecks** after every `docker run`
- **Scheduled health pings** every 5 min, alerts to Discord on red
- **structlog** for JSON-formatted application logs to stdout

---

## 16. Performance & Runtime Timings

### 16.1 Optimization techniques used

| Technique | Speedup |
|---|---|
| **Shallow git clone** (`--depth 1`) | 5-10x faster clones |
| **BuildKit cache mounts** | 3-10x faster builds |
| **Idempotent deploys** (skip build if image exists) | 10x faster no-op redeploys |
| **Skip push for local target** | Saves 30-90s per internal deploy |
| **Alpine / distroless base images** | 5x smaller images = 5x faster push/pull |
| **Layer ordering** (deps before code) | Huge cache hit rate |
| **Streaming Discord updates** | Feels 2x faster |
| **Persistent repo checkout** (git fetch + reset) | Saves clone time |
| **Prompt caching** (stable system prompts ≥1024 tokens) | 50% discount on input tokens |

### 16.2 Runtime timings (daily operations)

**Deploys:**

| Scenario | Duration |
|---|---|
| First deploy ever (cold cache) | 60-80 s |
| Warm deploy, code changed | 20-25 s |
| Idempotent redeploy (no changes) | 6-8 s |
| Rollback | 5-6 s |

**Diagnostic commands:**

| Command | Duration |
|---|---|
| `/logs name` | ~400-800 ms |
| `/inspect name` | ~250-400 ms |
| `/report name` | ~600-800 ms |
| `/health name` | ~200 ms |
| `/explain name` | ~1.5-2.5 s (dominated by LLM) |

**Query commands:**

| Command | Duration |
|---|---|
| `/repos`, `/branches <repo>` | ~100 ms (cached) |
| `/commits`, `/prs` | ~300-500 ms (live GitHub API) |
| `/status` | ~80 ms (Mongo only) |
| `/servers` | ~50 ms |
| `/images <name>` | ~100 ms |
| `/disk <server>` | ~300 ms |

**Autocomplete:** <50 ms per keystroke (in-memory rapidfuzz).

**Background processes:**

| Process | Frequency | Duration |
|---|---|---|
| GitHub cache refresh | Every 5 min | 1-3 s |
| Deployment healthcheck loop | Every 30 s per container | ~200 ms |
| Scheduled disk check | Every 1 hour | ~300 ms |
| LangGraph checkpoint write | Per graph node | ~20 ms |
| Mongo TTL cleanup | Every 60 s (Mongo internal) | Transparent |

### 16.3 Speedup vs manual workflow

| Task | Manual (SSH + docker) | With agent |
|---|---|---|
| Deploy known repo | 5-10 min | **25 s** |
| Diagnose a crashed container | 3-5 min | **0.6 s** (`/report`) |
| Rollback a broken deploy | 3-8 min | **6 s** (`/rollback`) |
| Compare 2 servers' containers | 4-6 min | **0.1 s** (`/status`) |
| Clean up old images | 2-4 min | **3 s** |

**~20x speedup on average.**

---

## 17. Folder Structure

```
devops-agent/
├── .claude/
│   └── agents/                  # Claude Code subagent definitions
│
├── agents/                      # LangGraph agent code
│   ├── __init__.py
│   ├── graph.py
│   ├── state.py
│   ├── checkpointer.py
│   ├── guardrails.py
│   ├── prompts.py
│   └── nodes/
│       ├── validate_auth.py
│       ├── route_input.py
│       ├── parse_intent.py      # free-text mode only
│       ├── classify_tier.py
│       ├── request_approval.py
│       ├── pre_deploy_check.py  # LLM deploy analysis (opt-in)
│       ├── execute_tool.py
│       ├── format_response.py
│       ├── audit_log.py
│       └── error_handler.py
│
├── api/                         # FastAPI app
│   ├── __init__.py
│   ├── main.py
│   └── routes/
│       ├── health.py
│       ├── metrics.py
│       └── webhooks.py
│
├── discord_bot/                 # Discord bot (top-level)
│   ├── __init__.py
│   ├── bot.py
│   ├── commands.py              # slash + autocomplete handlers
│   ├── views.py                 # Button views + paginators
│   ├── embeds.py                # Embed builders
│   ├── colors.py                # Color palette
│   └── formatters.py            # tabulate tables, uptime/size formatters
│
├── config/
│   ├── __init__.py
│   ├── settings.py              # pydantic-settings + AI toggles
│   ├── tool_tiers.yml           # tool name → tier mapping
│   ├── token_limits.py          # per-call token budgets
│   ├── deploy_config_schema.py  # Pydantic DeployConfig model
│   └── servers.example.yml
│
├── tools/
│   ├── __init__.py
│   ├── registry.py              # @tool decorator + REGISTRY
│   ├── github_tools.py
│   ├── docker_tools.py
│   ├── server_tools.py
│   ├── image_tools.py           # rollback, images, remove-images
│   ├── diagnose_tools.py        # wraps Layer 1 utilities
│   └── explain_tool.py          # Layer 2 opt-in LLM
│
├── utils/
│   ├── __init__.py
│   ├── logger.py                # structlog setup
│   ├── mongo.py                 # motor client
│   ├── llm.py                   # OpenAI wrapper + token tracking
│   ├── docker_context.py        # per-target context builder
│   ├── server_registry.py       # load servers.yml → Mongo
│   ├── github_cache.py          # repo/branch cache + bg refresh
│   ├── fuzzy_resolver.py        # rapidfuzz resolvers
│   ├── docker_diagnostics.py    # parse docker inspect
│   ├── log_analyzer.py          # regex + cluster + rules
│   ├── report_builder.py        # templated MD report builder
│   └── secrets_check.py         # .env + PEM permission check
│
├── docs/
│   ├── PROJECT_V2.md            # this file
│   ├── architecture.md
│   ├── security.md              # threat model, hardening checklist
│   ├── runbook.md               # ops guide
│   └── deploy.config.example.yml
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_github_tools.py
│   │   ├── test_docker_tools.py
│   │   ├── test_guardrails.py
│   │   ├── test_log_analyzer.py
│   │   ├── test_docker_diagnostics.py
│   │   ├── test_fuzzy_resolver.py
│   │   ├── test_deploy_config_schema.py
│   │   └── test_report_builder.py
│   ├── integration/
│   │   └── test_deploy_flow.py
│   └── eval/
│       └── agent_eval_set.json
│
├── scripts/
│   ├── setup_dev.sh
│   └── deploy_agent.sh
│
├── secrets/                     # gitignored
│   └── servers.yml
│
├── logs/                        # gitignored, runtime-generated MD reports
│
├── .dockerignore
├── .env.example
├── .gitignore
├── CLAUDE.md
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── MongoDB-Setup.md
├── pyproject.toml
└── README.md
```

---

## 18. `pyproject.toml`

```toml
[project]
name = "devops-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "langgraph>=1.0.0",
    "langgraph-checkpoint-mongodb>=0.1.0",
    "langchain-openai>=0.2.0",
    "openai>=1.50.0",
    "PyGithub>=2.4.0",
    "docker>=7.1.0",
    "discord.py>=2.4.0",
    "motor>=3.6.0",
    "pymongo>=4.10.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "python-dotenv>=1.0.0",
    "PyYAML>=6.0.2",
    "prometheus-client>=0.21.0",
    "structlog>=24.4.0",
    "rapidfuzz>=3.10.0",
    "tabulate>=0.9.0",
    "rich>=13.9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.7.0",
    "mypy>=1.13.0",
]
```

---

## 19. Makefile

```makefile
.PHONY: install dev run test lint type clean

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

dev:
	. .venv/bin/activate && uvicorn api.main:app --reload --port 8000

run:
	. .venv/bin/activate && uvicorn api.main:app --port 8000

test:
	. .venv/bin/activate && pytest tests/

lint:
	. .venv/bin/activate && ruff check . && ruff format --check .

type:
	. .venv/bin/activate && mypy agents/ api/ tools/ utils/ discord_bot/ config/

clean:
	rm -rf .venv __pycache__ .pytest_cache .mypy_cache
```

---

## 20. Data Model (MongoDB)

### `servers`
```json
{
  "_id": "physical-main",
  "type": "physical",
  "connection": "ssh",
  "host": "122.172.241.96",
  "ssh_user": "server",
  "pem": "physical",
  "labels": ["internal", "default"],
  "synced_at": "2026-04-11T14:00:00Z"
}
```

### `deployments` (updated with image_history)
```json
{
  "_id": "trading-dashboard",
  "repo": "kalpesh281/trading-dashboard",
  "branch": "main",
  "project": "internal",
  "target_server": "physical-main",
  "current_image": "kalpesh281/trading-dashboard:a3f21c9",
  "previous_image": "kalpesh281/trading-dashboard:8e2d1b4",
  "image_history": [
    "kalpesh281/trading-dashboard:a3f21c9",
    "kalpesh281/trading-dashboard:8e2d1b4",
    "kalpesh281/trading-dashboard:7c9a3f2",
    "kalpesh281/trading-dashboard:6b2e8d1",
    "kalpesh281/trading-dashboard:4a1f9c2"
  ],
  "container_id": "9f2c...",
  "port": 4001,
  "env": { "API_KEY": "***encrypted***" },
  "status": "running",
  "deployed_at": "2026-04-11T14:22:00Z",
  "deployed_by": "discord:kalpesh#0001"
}
```

### `audit_log`
See §14.6

### `checkpoints`
Managed by `langgraph-checkpoint-mongodb`. TTL index expires entries after 7 days.

### `github_cache` (optional Mongo mirror of in-memory cache)
```json
{
  "_id": "cache",
  "repos": ["trading-dashboard", "portfolio-site", ...],
  "branches": {
    "trading-dashboard": ["main", "dev", "feature/ws-v2"],
    ...
  },
  "updated_at": "2026-04-11T14:00:00Z"
}
```

---

## 21. Build Plan

**Total effort:** ~65-80 hours across 4 weeks (part-time, ~15-20 hrs/week). Full-time: ~2 weeks.

| Week | Focus | Deliverable |
|---|---|---|
| **1** | Foundation + GitHub queries | Bot responds to all GitHub queries with fuzzy autocomplete. Zero LLM calls yet. |
| **2** | Multi-target deployment | End-to-end deploy via slash command (clone → build → push → pull → run). |
| **3** | Rollback, diagnostics, UI, cleanup | Full deploy lifecycle with diagnostics, rollback, image management, and rich Discord UI — all with 0 tokens. |
| **4** | AI layer + hardening + polish | Production-grade agent running on the physical server. Portfolio ready. |

---

## 22. Setup Steps (one-time)

### On your laptop (development)

```bash
# 1. Clone / create the project
cd /Users/macbook/Desktop/Practice/Project

# 2. Create venv + install
make install

# 3. Copy and fill .env
cp .env.example .env
# edit: GITHUB_TOKEN, OPENAI_API_KEY, DISCORD_BOT_TOKEN, MONGO_URL,
#       ALLOWED_DISCORD_USERS, GITHUB_ORG, DOCKER_HUB_USER,
#       ENABLE_FREE_TEXT_CHAT, ENABLE_PREDEPLOY_ANALYSIS, ENABLE_EXPLAIN_COMMAND
chmod 600 .env

# 4. Create the PEM folder
sudo mkdir -p /devops_agent/pem
sudo chown $(whoami) /devops_agent/pem
chmod 700 /devops_agent/pem

# 5. (Dev only) SSH key for your physical server
ssh-keygen -t ed25519 -f ./devops-agent-physical -N ""
ssh-copy-id -i ./devops-agent-physical.pub server@122.172.241.96
mv ./devops-agent-physical /devops_agent/pem/physical.pem
chmod 600 /devops_agent/pem/physical.pem

# 6. Configure servers
cp config/servers.example.yml secrets/servers.yml
chmod 600 secrets/servers.yml
# edit with your real targets

# 7. Login to Docker Hub once
docker login

# 8. Start MongoDB locally (or use Atlas) — see MongoDB-Setup.md

# 9. Run the agent
make dev
```

### On your physical server (production)

```bash
# 1. Git clone the agent code
git clone <your-repo> ~/devops-agent
cd ~/devops-agent

# 2. SCP each client PEM
# (from your laptop)
scp acme.pem server@your-server:/devops_agent/pem/acme.pem
# (on server)
chmod 600 /devops_agent/pem/acme.pem

# 3. DO NOT copy physical.pem — agent runs locally now

# 4. Create .env with prod secrets
chmod 600 .env

# 5. Edit secrets/servers.yml: change physical-main to connection: local

# 6. Build + run via docker-compose
docker compose up -d

# 7. Check logs
docker compose logs -f agent
```

---

## 23. Threat Model

| Threat | Mitigation |
|---|---|
| Random Discord user runs commands | Allowlist of Discord user IDs |
| LLM hallucinates a destructive tool call | Tier system + denylist + HITL approval |
| Compromised agent host → all client keys leak | PEMs in restricted folder, host hardening required |
| Mongo dump leaks env vars | Env vars in plain .env (noted trade-off — simple operation) |
| Discord channel compromised | No secrets ever sent through Discord |
| Agent crash mid-deploy → orphaned containers | Mongo checkpointer resumes mid-graph |
| Disk fills up from old images | Auto-cleanup honoring `image_history` |
| Container escape from deployed app | Hardening flags: read-only, cap-drop, no-new-privileges, resource limits |
| Broken deploy in production | `/rollback` restores previous image in ~6s |
| Invalid `deploy.config.yml` wastes a build | Pydantic validation fails fast before build starts |

---

## 24. Verification (post-build checklist)

1. **Guardrails**: `/stop mongo` → refused (denylist). Non-allowlisted user runs `/deploy` → refused.
2. **Approval**: `/stop test-dep` → button card → click approve → container actually stops.
3. **Autocomplete**: `/deploy repo:tra` → dropdown shows trading-dashboard at top. Typo `trding` still matches.
4. **Audit log**: any command → Mongo `audit_log` row with actor, tier, result, duration.
5. **Checkpointing**: start a deploy → kill agent mid-build → restart → resumes correctly.
6. **Metrics**: `curl http://localhost:8000/metrics` → Prometheus counters visible.
7. **Container hardening**: `docker inspect <svc>` → `ReadonlyRootfs: true`, `CapDrop: [ALL]`.
8. **Multi-target**: deploy with `target_server: client-acme-prod` → container on EC2, not physical.
9. **Identifier resolution**: `/logs trading-dashboard`, `/logs kalpesh281/trading-dashboard`, `/logs internal` → all resolve to same deployment.
10. **Auto-cleanup**: deploy 6 times → only last 5 images remain (history length).
11. **Rollback**: `/rollback name` → restores previous image in <10s, healthcheck passes.
12. **`/images`**: shows last 5 versions; "Remove old" button removes all but current + previous.
13. **Layer 1 diagnostics**: `/report name` → populated Embed in <1s, 0 tokens.
14. **Layer 2 explain**: `/explain name` → AI hypothesis + token count in footer.
15. **YAML validation**: push a repo with typo'd field → Discord error with "did you mean" suggestion.
16. **`.env` check**: `chmod 644 .env` → agent boot logs a warning.
17. **Dev → prod**: flip `physical-main.connection` ssh→local → no code changes → works.
18. **AI toggles**: set all three `ENABLE_*` flags to false → agent still deploys and diagnoses normally.
19. **CI**: push a PR with broken type → mypy/ruff/test failure in Actions.

---

## 25. Project Rating & Trade-offs

### Rating: **8.8 / 10** for portfolio value

| Dimension | Score | Notes |
|---|---|---|
| Technical depth | 9/10 | Multi-target deploy + hybrid AI + LangGraph HITL |
| Production-readiness | 8.5/10 | Rollback, validation, audit log, checkpointing, hardening |
| Security posture | 7.5/10 | Plaintext .env + PEM (trade-off for simplicity) |
| Resume impact | 9.5/10 | Rare combo; demonstrates judgment, not just execution |
| Daily usefulness | 10/10 | You'll actually use it |

### Accepted trade-offs

| Trade-off | Choice | Justification |
|---|---|---|
| **Secrets at rest** | Plain `.env` + PEM files | Simple operation; startup check warns on bad perms; easy migration path to Vault in v3 |
| **Docker registry** | Docker Hub (no local mirror) | <50 deploys/day at startup scale, well under rate limits |
| **GitHub cache refresh** | Polling every 5 min | <200 API calls/hour; webhook-driven refresh is v3 optimization |
| **Single-host deploy** | Agent runs on one server | Single-user tool; HA is v3 territory |
| **No web dashboard** | Discord-only | Discord gives you Embeds, buttons, autocomplete for free |

---

## 26. Resume Bullet

> Built a production-grade conversational DevOps AI agent (LangGraph + FastAPI + Discord) that manages GitHub repositories and Docker deployments across multiple servers (physical + AWS EC2). Hybrid AI design: core features (deploy, rollback, diagnostics, autocomplete) use **zero LLM calls** and work offline, while three opt-in AI features (free-text chat, pre-deploy Dockerfile review, `/explain` root-cause hypothesis) can be toggled independently via config flags. Includes tiered authorization with Discord button-based human-in-the-loop approval, Mongo-backed LangGraph checkpointing for resumable graph execution, rapidfuzz-powered slash command autocomplete over a cached repo/branch list, a two-layer diagnostics system (regex + rule engine for Layer 1, LLM hypothesis on structured summaries for Layer 2 at <300 tokens/call), and rich Discord UI with color-coded Embeds, paginated logs, and live-streaming deploy messages. Replaces manual SSH workflows with single-command deployments, rollbacks, and diagnostics — reducing deploy time from ~10 minutes to ~25 seconds. Full monthly LLM cost: **~$0.02**.

---

## 27. v3 Roadmap

- Web dashboard (React) alongside Discord
- PR-triggered preview deployments via GitHub webhooks
- AWS SSM Session Manager as an alternative target type (keyless, audited)
- Traefik / Caddy reverse proxy with auto-SSL
- HashiCorp Vault integration for secrets
- Local Docker Hub pull-through cache (if deploy frequency grows)
- Multi-LLM provider support (Anthropic + OpenAI)
- Approval delegation (require 2 Discord users for the most destructive ops)
- Webhook-driven GitHub cache invalidation (vs polling)
- Disk-based log archiving with search
- Cost tracking per deployment
