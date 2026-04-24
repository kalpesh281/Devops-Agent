# DevOps AI Agent — v2 (Production-Hardened)

A conversational AI agent (Telegram bot) that manages GitHub repositories and Docker deployments across multiple servers — your physical server plus client-specific AWS EC2 instances. Built with LangGraph, FastAPI, OpenAI GPT-5.4-nano, and the Docker SDK.

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

You: tap "Explain with AI"
Bot: 🟣 AI Analysis — trading-dashboard
     The container is running but experiencing frequent MongoDB timeouts.
     The pattern suggests the mongo container is unhealthy.
     Recommended: /report mongo → if unhealthy, /restart mongo
     GPT-5.4-nano • 247 tokens • ~$0.00015
```

---

## 2. Goals & Non-Goals

### Goals (v2)
- Single-user (you) personal DevOps agent, controlled via Telegram
- **Multi-target deployment**: physical server + N client AWS EC2 instances
- Commands with inline-mode entity search over a cached repo/branch list (0 tokens for the search itself)
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
- Telegram UI layer: emoji-coded HTML messages, paginated logs via inline keyboards, callback-query button interactions
- `deploy.config.yml` schema validation with friendly error messages
- `.env` startup security check
- Tests + CI + docs + demo asset

### Non-Goals (v3+)
- Multi-user / multi-tenant
- Web dashboard (Telegram-only for v2)
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
| Telegram client | **python-telegram-bot v21+** | Commands + inline keyboards + callback queries + inline mode |
| Fuzzy matching | **rapidfuzz** | C-accelerated fuzzy matching for entity selection |
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
                    │  Telegram   │
                    │    (DM)     │
                    └──────┬──────┘
                           │
                           ▼
                  ┌──────────────────┐         ┌──────────────────┐
                  │  Telegram bot    │────────▶│  GitHub API      │
                  │python-telegram-bot│ cache  │  (PyGithub)      │
                  │                  │         └──────────────────┘
                  │  • Commands      │
                  │  • Inline kbd    │         ┌──────────────────┐
                  │  • Inline mode   │────────▶│  OpenAI          │
                  │  • HTML messages │ opt-in  │  GPT-5.4-nano    │
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
       │ route_input   │  ← command vs free-text
       └───┬───────┬───┘
           │       │
 command   │       │  free-text
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
                ▼                  │
       ┌─────────────────┐         │   ← only for approval-tier ops
       │ typed_confirm   │         │     user must type "ACTION NAME"
       │    interrupt    │         │     within 60s (OD-L6)
       └────────┬────────┘         │
                │                  │
                └────────┬─────────┘
                         ▼
                  ┌────────────────┐
                  │ execute_tool   │
                  └────────┬───────┘
                           │
                           ▼
                  ┌────────────────┐
                  │ format_response│  ← Telegram HTML message / templated, no LLM
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
    platform_user_id: str
    platform_chat_id: str
    trace_id: str

    input_mode: Literal["command", "free_text"]
    intent: Optional[str]
    intent_args: dict[str, Any]
    tool_name: Optional[str]
    tool_tier: Optional[Literal["auto", "notify", "approval"]]

    pending_approval: bool
    approved: Optional[bool]

    typed_confirm_expected: Optional[str]       # e.g. "STOP trading-dashboard"
    typed_confirm_received: Optional[str]       # populated when user replies
    typed_confirm_deadline: Optional[datetime]

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

| Command | Selection UX | Action |
|---|---|---|
| `/repos` | — | List repos in org (from cache) |
| `/branches <repo>` | inline mode · keyboard | List branches for a repo |
| `/commits <repo> <branch>` | inline mode · keyboard | Recent commits (default 10) |
| `/prs <repo>` | inline mode · keyboard | Open pull requests |
| `/files <repo> <branch>` | inline mode · keyboard | Show key files (Dockerfile, package.json, etc.) |
| `/refresh` | — | Force-refresh the GitHub cache |

### Deployment (notify tier)

| Command | Selection UX | Action |
|---|---|---|
| `/deploy <repo> <branch>` | inline mode · keyboard | Build → push → pull → run → cleanup |
| `/redeploy <name>` | inline mode · keyboard | Pull latest + restart |
| `/restart <name>` | inline mode · keyboard | Restart container |
| `/status` | — | Grouped deployments by target server (ASCII table in `<pre>`) |
| `/status <server>` | keyboard | Filter by one server |
| `/servers` | — | List registered target servers |
| `/disk <server>` | keyboard | `docker system df` on a target |

### Destructive (approval tier, HITL button)

| Command | Selection UX | Action |
|---|---|---|
| `/stop <name>` | inline mode · keyboard | Stop deployment |
| `/rollback <name>` | inline mode · keyboard | Roll back to previous image (5-6s) |
| `/remove-images <name>` | inline mode · keyboard | Remove all images except current + previous 1 |
| `/cleanup <server>` | keyboard | Manual image cleanup pass |
| `/delete-deployment <name>` | inline mode · keyboard | Stop + remove deployment record |

### Diagnostics (auto tier, 0 tokens)

| Command | Selection UX | Action |
|---|---|---|
| `/logs <name>` | inline mode · keyboard | Paginated logs from Mongo with level/time filters (§11.3) |
| `/inspect <name>` | inline mode · keyboard | Parsed `docker inspect` HTML message |
| `/health <name>` | inline mode · keyboard | Uptime + restart count + health status |
| `/report <name>` | inline mode · keyboard | Full Layer 1 diagnostic message (inspect + logs + rules) |
| `/history <name>` | inline mode · keyboard | Browsable diagnostic event timeline (§11.8) |
| `/images <name>` | inline mode · keyboard | List last 5 image versions with buttons |

### AI-powered (opt-in, tokens used)

| Command | Selection UX | Tokens | Action |
|---|---|---|---|
| `/explain <name>` | inline mode · keyboard | ~250 | Layer 1 report + LLM hypothesis |

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

### 9.3 Persistent log ingestion

Layer 1 runs on-demand against live `docker logs`. For history/trends and background error detection, the agent also runs a **per-deployment background scraper** that flushes logs to Mongo at a configurable cadence.

**Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│ Background task per running deployment                      │
│ (asyncio.Task spawned on startup, cancelled on /stop)       │
│                                                             │
│ 1. Poll every 60s (OD-L1)                                   │
│    docker logs --since=<last_flush_ts> --timestamps         │
│                                                             │
│ 2. Insert new lines → Mongo `container_logs` (TTL 7d)       │
│                                                             │
│ 3. Run §9.1 rule engine on the delta                        │
│    → matched rules → `diagnostic_events` (TTL 30d)          │
│                                                             │
│ 4. If severity ≥ error AND ENABLE_LOG_ALERTS                │
│    → send Telegram alert                                    │
│    → rate-limited: 1/min per deployment                     │
└─────────────────────────────────────────────────────────────┘
```

**Code sketch:**

```python
# utils/log_scraper.py
import asyncio
from datetime import datetime, timedelta
from utils.event_detector import detect_events
from utils.mongo import db

POLL_INTERVAL = 60  # OD-L1

class LogScraper:
    def __init__(self, deployment_id: str, docker_client, target_server: str):
        self.deployment = deployment_id
        self.docker = docker_client
        self.server = target_server
        self.last_flush = datetime.utcnow() - timedelta(seconds=POLL_INTERVAL)

    async def run(self):
        while True:
            try:
                await self._flush_once()
            except Exception as e:
                logger.error(f"scraper error for {self.deployment}: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    async def _flush_once(self):
        container = self.docker.containers.get(self.deployment)
        raw = container.logs(
            since=int(self.last_flush.timestamp()),
            timestamps=True,
            stream=False,
        ).decode("utf-8", errors="replace")
        self.last_flush = datetime.utcnow()

        lines = [
            parse_line(l, self.deployment, self.server)
            for l in raw.splitlines() if l.strip()
        ]
        if not lines:
            return

        await db.container_logs.insert_many(lines)

        # rule engine over the delta
        events = detect_events(lines, self.deployment)
        if events:
            await db.diagnostic_events.insert_many(events)
            await alert_if_needed(events)
```

**Freshness escape hatch:** `/logs <name>` and `/report <name>` may bypass the 60s cache with a live `docker logs` call for real-time data. The Mongo cache powers `/history`, trend detection, and the background alerting loop.

**Storage budget:** ~1.5 MB/day per container. For 10 active containers with a 7-day TTL: ~100 MB in Mongo. Negligible.

---

## 10. Entity Selection — Inline Mode + Fuzzy Keyboard

### 10.1 The insight

Telegram doesn't do Discord-style per-argument live autocomplete. But it offers two primitives that — combined — give the same 0-token entity selection:

1. **Inline mode** — the user types `@yourbot <query>` from any chat's compose box and gets a searchable dropdown that inserts the chosen value into the message.
2. **Inline keyboards** — when the bot asks "pick a repo?" mid-conversation, it sends a top-10 fuzzy-matched keyboard; the user taps; a callback query carries the selection.

Both read from the same in-memory rapidfuzz-backed cache. Neither needs the LLM.

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

### 10.3 Inline mode handler (entity search via `@yourbot <query>`)

```python
# telegram_bot/handlers.py
from telegram import InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import InlineQueryHandler
from rapidfuzz import process
from utils.github_cache import cache

async def inline_repo_search(update, context):
    query = update.inline_query.query.strip()
    if not query:
        matches = [(r, 100, None) for r in cache.repos[:25]]
    else:
        matches = process.extract(query, cache.repos, limit=25)
    results = [
        InlineQueryResultArticle(
            id=name,
            title=name,
            input_message_content=InputTextMessageContent(name),
        )
        for name, score, _ in matches if score > 40
    ]
    await update.inline_query.answer(results, cache_time=60)
```

Registered once in `telegram_bot/bot.py`:

```python
application.add_handler(InlineQueryHandler(inline_repo_search))
```

### 10.4 Keyboard fallback (in-conversation selection)

When the bot replies to a conversational turn needing entity selection, it sends a top-10 keyboard with an "others…" paginator button for the tail.

```python
# telegram_bot/keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from rapidfuzz import process
from utils.github_cache import cache

def build_repo_keyboard(query: str, action: str) -> InlineKeyboardMarkup:
    if query:
        matches = process.extract(query, cache.repos, limit=10)
        repos = [m[0] for m in matches if m[1] > 40]
    else:
        repos = cache.repos[:10]
    rows = [[InlineKeyboardButton(r, callback_data=f"{action}:{r}")] for r in repos]
    if len(cache.repos) > 10:
        rows.append([InlineKeyboardButton("others…", callback_data=f"{action}:__more__")])
    return InlineKeyboardMarkup(rows)
```

Branches, deployment names, and servers get analogous builders over the same cache + Mongo-backed lists.

### 10.5 Fuzzy "did you mean?" for free-text commands

On `/deploy trding-dashbord main`, if no exact match:

```python
from rapidfuzz import process

def fuzzy_resolve(query: str, choices: list[str]) -> tuple[str, int] | None:
    best = process.extractOne(query, choices, score_cutoff=60)
    return (best[0], best[1]) if best else None

# handler:
hit = fuzzy_resolve(repo_arg, cache.repos)
if not hit:
    await update.message.reply_text(f"No match for <code>{repo_arg}</code>.", parse_mode="HTML")
elif hit[0] != repo_arg:
    kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"yes, {hit[0]}", callback_data=f"confirm_deploy:{hit[0]}"),
        InlineKeyboardButton("cancel", callback_data="cancel"),
    ]])
    await update.message.reply_text(
        f"No exact match. Did you mean <b>{hit[0]}</b>?",
        parse_mode="HTML",
        reply_markup=kbd,
    )
```

### 10.6 Three input modes (all coexist)

| Mode | Trigger | Tokens | Latency |
|---|---|---|---|
| **Inline mode entity search** | `@yourbot tra` in any chat | 0 | ~80–120 ms |
| **Typed command + fuzzy resolve** | `/deploy trading-dashboard main` | 0 | ~80 ms |
| **Conversational free-text** | "deploy the trading dashboard" | ~230 | ~1–2s |

---

## 11. Telegram UI Layer

Pure `python-telegram-bot` v21+ primitives + `tabulate` for ASCII tables inside `<pre>` blocks. No extra UI libraries.

### 11.1 Emoji palette (consistent across the bot)

```python
# telegram_bot/colors.py
class Colors:
    SUCCESS = "🟢"
    WARNING = "🟡"
    ORANGE  = "🟠"
    ERROR   = "🔴"
    INFO    = "🔵"
    AI      = "🟣"
    MUTED   = "⚪"
```

Usage: prefix the status line / title with the emoji. Telegram messages have no color field — emoji is the color.

### 11.2 `/report` — readable, structured diagnostic message

Readable format with labelled sections: status header, health snapshot, recent issues, suggested actions, footer. Inline keyboard carries the next-step actions.

**Rendered example:**

```
🟡 trading-dashboard — Running with errors

📊 Health snapshot
• Target:   physical-main
• Uptime:   2h 14m · Restarts: 0
• Memory:   340/512 MB (66%)
• CPU:      12.3%
• Health:   passing (5/5)

⚠️ Recent issues (last 10 min)
• 🔴 42× MongoDB connection timeout
• 🟡  3× Unhandled rejection

💡 Suggested actions
1. /report mongo — check mongo health
2. /restart mongo — if mongo is unhealthy
3. /explain trading-dashboard — AI root-cause

Layer 1 · 623 ms · 0 tokens

[🤖 Explain with AI] [📜 Raw logs]
[🔄 Restart]        [↩ Rollback]
```

**Code:**

```python
# telegram_bot/messages.py
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram_bot.colors import Colors

def build_report_message(inspect: dict, logs: dict, name: str) -> tuple[str, InlineKeyboardMarkup]:
    if not inspect["running"]:
        icon, status = Colors.ERROR, f"Stopped (exit {inspect['exit_code']})"
    elif inspect["restart_count"] > 5:
        icon, status = Colors.ORANGE, f"Unstable ({inspect['restart_count']} restarts)"
    elif logs["error_count"] > 10:
        icon, status = Colors.WARNING, "Running with errors"
    else:
        icon, status = Colors.SUCCESS, "Healthy"

    mem_pct = int(100 * inspect["memory_mb"] / inspect["memory_limit_mb"])
    health_line = inspect.get("health_status", "—")
    if inspect.get("health_failing_streak") is not None:
        total = inspect.get("health_total_checks", 5)
        passing = max(0, total - inspect["health_failing_streak"])
        health_line = f"{health_line} ({passing}/{total})"

    sections = [
        f"<b>{icon} {escape(name)} — {status}</b>",
        "",
        "<b>📊 Health snapshot</b>",
        f"• Target:   <code>{inspect['target_server']}</code>",
        f"• Uptime:   {format_uptime(inspect['uptime_seconds'])} · Restarts: {inspect['restart_count']}",
        f"• Memory:   {inspect['memory_mb']}/{inspect['memory_limit_mb']} MB ({mem_pct}%)",
        f"• CPU:      {inspect['cpu_pct']:.1f}%",
        f"• Health:   {health_line}",
    ]

    if logs["error_count"] > 0 or logs["warn_count"] > 0:
        sections += ["", "<b>⚠️ Recent issues (last 10 min)</b>"]
        for pattern, count in logs["top_errors"][:3]:
            lvl_icon = Colors.ERROR if count >= 10 else Colors.WARNING
            sections.append(f"• {lvl_icon} {count}× <code>{escape(pattern[:80])}</code>")

    suggestions = build_suggestions(inspect, logs, name)
    if suggestions:
        sections += ["", "<b>💡 Suggested actions</b>"]
        for i, s in enumerate(suggestions, 1):
            sections.append(f"{i}. {s}")

    sections += ["", f"<i>Layer 1 · {inspect['duration_ms']} ms · 0 tokens</i>"]

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Explain with AI", callback_data=f"explain:{name}"),
         InlineKeyboardButton("📜 Raw logs",        callback_data=f"logs:{name}:0")],
        [InlineKeyboardButton("🔄 Restart",         callback_data=f"restart:{name}"),
         InlineKeyboardButton("↩ Rollback",         callback_data=f"rollback:{name}")],
    ])
    return "\n".join(sections), kbd
```

### 11.3 `/logs` — readable line format + level/time filters

Each line prefixed with an emoji (level) + short timestamp + trimmed message. Cluster summary at the bottom. Filter keyboard drives re-query against `container_logs` (§9.3), or falls back to a live `docker logs` call when freshness matters.

**Rendered example:**

```
📜 Logs — trading-dashboard
⏱ Last 5 min · 🔴 4 · 🟡 2 · 🔵 12 · 📊 18 lines

🔴 12:34:57  MongoDB connection timeout
🟡 12:34:58  Retrying mongo connection (2/5)
🔴 12:35:02  MongoDB connection timeout
🟡 12:35:03  Circuit breaker opened
🔵 12:35:05  Fallback to cache (3 items)
🔴 12:35:10  MongoDB connection timeout
🔵 12:35:12  Request served from cache
🔴 12:35:15  MongoDB connection timeout
🔵 12:35:18  Health check passed

Patterns
▸ 4× MongoDB connection timeout
▸ 2× Retrying mongo connection
▸ 1× Circuit breaker opened

[🔴 Errors only] [🟡 Warn+] [🔵 All]
[⏱ 5m] [⏱ 1h] [⏱ 24h]
[⏮] [◀] 1/4 [▶] [⏭]
```

**Code:**

```python
# telegram_bot/messages.py
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram_bot.colors import Colors
from utils.mongo import db

LEVEL_ICON = {"ERROR": Colors.ERROR, "FATAL": Colors.ERROR,
              "WARN": Colors.WARNING, "INFO": Colors.INFO}

async def build_logs_message(
    name: str, page: int, level_filter: str = "ALL", window: str = "5m",
) -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.container_logs.find(
        query_for(name, level_filter, window)
    ).sort("timestamp", 1).to_list(length=1000)

    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for r in rows:
        counts[r["level"]] = counts.get(r["level"], 0) + 1

    # page slice — 30 lines per page
    per_page, total_pages = 30, max(1, (len(rows) + 29) // 30)
    slice_ = rows[page*per_page : (page+1)*per_page]

    header = (
        f"<b>📜 Logs — {escape(name)}</b>\n"
        f"<i>⏱ Last {window} · {Colors.ERROR} {counts['ERROR']} · "
        f"{Colors.WARNING} {counts['WARN']} · {Colors.INFO} {counts['INFO']} · "
        f"📊 {len(rows)} lines</i>"
    )
    body = "\n".join(
        f"{LEVEL_ICON.get(r['level'], Colors.MUTED)} "
        f"<code>{r['timestamp'].strftime('%H:%M:%S')}</code>  "
        f"{escape(r['line'][:140])}"
        for r in slice_
    )

    # cluster summary (top 3)
    clusters = top_clusters(rows, limit=3)
    clusters_block = ""
    if clusters:
        lines = "\n".join(f"▸ <b>{c}×</b> {escape(t[:80])}" for t, c in clusters)
        clusters_block = f"\n\n<b>Patterns</b>\n{lines}"

    text = f"{header}\n\n{body}{clusters_block}"
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Errors", callback_data=f"logs:{name}:f:ERROR"),
         InlineKeyboardButton("🟡 Warn+",  callback_data=f"logs:{name}:f:WARN"),
         InlineKeyboardButton("🔵 All",    callback_data=f"logs:{name}:f:ALL")],
        [InlineKeyboardButton("⏱ 5m",  callback_data=f"logs:{name}:w:5m"),
         InlineKeyboardButton("⏱ 1h",  callback_data=f"logs:{name}:w:1h"),
         InlineKeyboardButton("⏱ 24h", callback_data=f"logs:{name}:w:24h")],
        [InlineKeyboardButton("⏮", callback_data=f"logs:{name}:p:0"),
         InlineKeyboardButton("◀", callback_data=f"logs:{name}:p:{max(0, page-1)}"),
         InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"),
         InlineKeyboardButton("▶", callback_data=f"logs:{name}:p:{min(total_pages-1, page+1)}"),
         InlineKeyboardButton("⏭", callback_data=f"logs:{name}:p:{total_pages-1}")],
    ])
    return text, kbd
```

Callback handler edits the same message in place via `context.bot.edit_message_text`. Long tracebacks are collapsed into the "Patterns" cluster summary rather than dumped inline.

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
    return f"<b>Deployments ({len(deployments)})</b>\n<pre>{table}</pre>"
```

### 11.5 `/images` — HTML message + management keyboard

```python
def build_images_message(images: list[dict], name: str) -> tuple[str, InlineKeyboardMarkup]:
    lines = [f"<b>📦 Images for {escape(name)}</b>"]
    for i, img in enumerate(images):
        marker = "▸ <b>current</b>" if i == 0 else "  previous" if i == 1 else "  old"
        lines.append(
            f"\n<code>{img['tag'][:12]}</code> — {marker}\n"
            f"Deployed {time_ago(img['deployed_at'])} · Size: {img['size_mb']} MB"
        )
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Remove old", callback_data=f"images:remove:{name}")],
        [InlineKeyboardButton("↩ Rollback",    callback_data=f"images:rollback:{name}")],
    ])
    return "\n".join(lines), kbd
```

### 11.6 Deploy — single self-updating message

For long operations, the agent edits one message as each step completes instead of spamming the chat:

```python
async def deploy_with_streaming(update, context, repo, branch):
    msg = await update.message.reply_text(
        f"{Colors.INFO} Cloning repo…", parse_mode="HTML"
    )
    await clone(repo, branch)
    await context.bot.edit_message_text(
        chat_id=msg.chat_id, message_id=msg.message_id,
        text=f"✅ Cloned\n{Colors.INFO} Building image…",
        parse_mode="HTML",
    )
    await build(...)
    await context.bot.edit_message_text(
        chat_id=msg.chat_id, message_id=msg.message_id,
        text=f"✅ Cloned\n✅ Built (12s)\n{Colors.INFO} Pushing…",
        parse_mode="HTML",
    )
    # … and so on, final edit turns green
    await context.bot.edit_message_text(
        chat_id=msg.chat_id, message_id=msg.message_id,
        text=(
            "✅ Cloned (1s)\n"
            "✅ Built (12s)\n"
            "✅ Pushed (4s)\n"
            "✅ Pulled on physical-main (2s)\n"
            "✅ Running → http://server:4001\n"
            "<b>Total: 22s</b>"
        ),
        parse_mode="HTML",
    )
```

### 11.7 `/explain` — 🟣 AI message with token footer

```python
def build_explain_message(report: dict, llm_analysis: str, tokens_used: int) -> str:
    # Blended gpt-5.4-nano price ≈ $0.62 / 1M tokens (60% in @ $0.20, 40% out @ $1.25)
    cost = tokens_used * 0.62 / 1_000_000
    return (
        f"<b>{Colors.AI} AI Analysis — {escape(report['name'])}</b>\n\n"
        f"{escape(llm_analysis)}\n\n"
        f"<b>📊 Diagnostic data</b>\n"
        f"Errors: <b>{report['error_count']}</b> · "
        f"Restarts: <b>{report['restart_count']}</b> · "
        f"Exit: <b>{report['exit_code']}</b>\n\n"
        f"<i>GPT-5.4-nano • {tokens_used} tokens • ~${cost:.5f}</i>"
    )
```

### 11.8 `/history` — browsable diagnostic event timeline

Reads from the `diagnostic_events` collection (§9.3 / §20). Each row shows severity emoji, short time, and one-line summary. Tapping a row expands the message in place to include the 20-line context window stored with the event.

**Rendered example:**

```
📜 History — trading-dashboard
Last 24 hours · 7 events

🔴 12:35  Mongo timeout spike (42 in 5 min)
🟡 11:20  Memory spike (480/512 MB)
🔴 10:03  Container restart loop (3 restarts)
🟡 09:15  Slow response time (>2 s)
🔵 08:00  Deploy success (a3f21c9)
🟡 06:44  Cold start (first request after idle)
🔵 00:00  Daily health summary

Tap an event → expand to 20 lines of context

[🔴 Errors only] [🟡 All incidents]
[⏱ 24h] [⏱ 7d] [⏱ 30d]
```

**Code:**

```python
# telegram_bot/messages.py
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram_bot.colors import Colors
from utils.mongo import db

SEV_ICON = {"error": Colors.ERROR, "warn": Colors.WARNING, "info": Colors.INFO}

async def build_history_message(
    name: str, severity_filter: str = "all", window: str = "24h",
) -> tuple[str, InlineKeyboardMarkup]:
    query = history_query(name, severity_filter, window)
    events = await db.diagnostic_events.find(query) \
        .sort("triggered_at", -1).to_list(length=50)

    header = (
        f"<b>📜 History — {escape(name)}</b>\n"
        f"<i>Last {window} · {len(events)} events</i>"
    )
    body = "\n".join(
        f"{SEV_ICON.get(e['severity'], Colors.MUTED)} "
        f"<code>{e['triggered_at'].strftime('%H:%M')}</code>  "
        f"{escape(e['message'][:80])}"
        for e in events
    ) or "<i>No events in this window.</i>"

    text = f"{header}\n\n{body}\n\n<i>Tap an event for context.</i>"
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Errors only",  callback_data=f"hist:{name}:f:error"),
         InlineKeyboardButton("🟡 All incidents", callback_data=f"hist:{name}:f:all")],
        [InlineKeyboardButton("⏱ 24h", callback_data=f"hist:{name}:w:24h"),
         InlineKeyboardButton("⏱ 7d",  callback_data=f"hist:{name}:w:7d"),
         InlineKeyboardButton("⏱ 30d", callback_data=f"hist:{name}:w:30d")],
        # Per-event tap buttons appended below this row in the handler
    ])
    return text, kbd
```

Expansion flow: tapping an event triggers `hist:<name>:open:<event_id>` → handler fetches `context_logs` from the event document and edits the message to include the 20 surrounding lines using the §11.3 readable format.

### 11.9 Typed-keyword confirmation prompt (destructive ops)

After the approval button is tapped on a destructive operation (§14.1), the bot posts a typed-keyword prompt. The user must reply with the exact phrase within 60 s (OD-L6) or the operation aborts.

**Rendered example:**

```
🔴 Stop request — trading-dashboard

This will stop the container on physical-main.
Active connections: 3 · Uptime: 2h 14m

To confirm, type exactly:
STOP trading-dashboard

(case-sensitive · 60s to respond)

[❌ Cancel]
```

**Code:**

```python
# agents/nodes/request_typed_confirmation.py
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram_bot.colors import Colors

CONFIRM_TIMEOUT_SECONDS = 60   # OD-L6

async def request_typed_confirmation(state: AgentState, bot, chat_id: int) -> AgentState:
    action = state["tool_name"].upper()                  # "STOP", "ROLLBACK", …
    target = state["intent_args"]["name"]
    expected = f"{action} {target}"                      # OD-L5 full-form

    prompt = (
        f"<b>{Colors.ERROR} {action.title()} request — {target}</b>\n\n"
        f"This will {action.lower()} the container on "
        f"<code>{state['target_server']}</code>.\n"
        f"{_impact_line(state)}\n\n"
        f"<b>To confirm, type exactly:</b>\n"
        f"<code>{expected}</code>\n\n"
        f"<i>(case-sensitive · 60s to respond)</i>"
    )
    kbd = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="confirm:cancel")]])
    msg = await bot.send_message(chat_id, prompt, parse_mode="HTML", reply_markup=kbd)

    state["typed_confirm_expected"] = expected
    state["typed_confirm_deadline"]  = datetime.utcnow() + timedelta(seconds=CONFIRM_TIMEOUT_SECONDS)

    try:
        received = await asyncio.wait_for(
            _await_user_reply(chat_id, state),
            timeout=CONFIRM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        state["approved"] = False
        state["error"]    = "typed_confirm_timeout"
        return state

    state["typed_confirm_received"] = received
    state["approved"] = (received == expected)
    if not state["approved"]:
        state["error"] = "typed_confirm_mismatch"
    return state
```

Timeouts and mismatches both write to the audit log (§14.6) with `result: "aborted_typed_confirm_<reason>"`.

---

## 12. Token Budget — Conversational Primary

### 12.1 Where tokens are actually used

| Stage | When | In | Out | Total |
|---|---|---|---|---|
| Free-text intent parser | Every conversational turn (default path) | ~200 | ~30 | ~230 |
| Pre-deploy config check | Once per `/deploy`, optional flag | ~400 | ~150 | ~550 |
| `/explain` | Only when user runs it, opt-in | ~150 | ~100 | ~250 |

**Zero-token stages:** inline-mode entity search, keyboard callbacks, fuzzy "did you mean?" resolution, `/status`, `/logs`, `/inspect`, `/report`, `/images`, `/rollback`, response formatting, error handling, approvals.

### 12.2 Realistic daily usage (conversational primary)

| Activity | Count/day | Tokens each | Subtotal |
|---|---|---|---|
| Conversational messages (intent parse) | 20 | 230 | 4,600 |
| `/deploy` with pre-check | 5 | 550 | 2,750 |
| `/explain` | 2 | 250 | 500 |
| **Daily total** | | | **~7,850** |
| **Monthly** | | | **~235K** |
| **Cost** (gpt-5.4-nano @ $0.20 in / $1.25 out per 1M) | | | **~$0.10–$0.20/month** |

Ranges: heavy-input usage skews toward $0.10; heavy-output toward $0.20. Prompt caching (§16.1) shaves input further once system prompts stabilize.

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
    ENABLE_FREE_TEXT_CHAT: bool = True           # disable → command-only mode (no conversational UX)
    ENABLE_PREDEPLOY_ANALYSIS: bool = True       # disable → skip LLM before deploys
    ENABLE_EXPLAIN_COMMAND: bool = True          # disable → remove /explain command
    ENABLE_LOG_ALERTS: bool = True               # disable → scraper still runs, but no Telegram alerts
```

**Note on `ENABLE_FREE_TEXT_CHAT`** — because Telegram is conversational-primary in v2, turning this off reduces the bot to command-only operation. All commands still work (they are 0-token), but the conversational intent-parse path is disabled; users must use explicit `/commands`.

```
CORE FEATURES (always-on, 0 tokens)
├── GitHub listing via API + cache
├── Inline-mode entity search (rapidfuzz)
├── Inline keyboard selection + "did you mean?" fallback
├── Deploy pipeline (build, push, pull, run)
├── Multi-server management
├── Layer 1 diagnostics (inspect + logs + rules)
├── Templated Telegram HTML messages + keyboards + paginators
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
| **approval** | stop, rollback, remove-images, cleanup, delete-deployment | HITL interrupt → Telegram button → typed-keyword confirm (60s timeout) → resume |

### 14.2 Allow / deny lists

- **User allowlist — GitHub-org-gated self-enrollment.** First-time users DM the bot, reply with their GitHub username, and the agent calls `org.has_in_members(user)` against `settings.GITHUB_ORG`. Verified users are upserted into the Mongo `users` collection (§20) with their Telegram ID, Telegram username, GitHub handle, `status=active`, and `role=member`. A background task re-verifies org membership every 24 h — members who leave the GitHub org are auto-revoked. `FIRST_ADMIN_TELEGRAM_ID` env var bootstraps the first admin; subsequent admins promoted via `/users promote @handle`.
- **Emergency bypass**: `ALLOWED_TELEGRAM_USERS` env var is a comma-separated list of Telegram IDs that skip enrollment. Intended for cold-boot scenarios (Mongo down, admin locked out). Logged as a warning on use.
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

Every deploy starts with a strict Pydantic validation pass. Invalid configs fail fast with a friendly Telegram message.

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

**Error formatter posts friendly messages to Telegram:**

```python
async def validate_deploy_config(yaml_text: str):
    try:
        data = yaml.safe_load(yaml_text)
        return DeployConfig.model_validate(data), None
    except yaml.YAMLError as e:
        return None, f"⚠️ Invalid YAML syntax:\n<pre>{escape(str(e))}</pre>"
    except ValidationError as e:
        errors = []
        for err in e.errors():
            field = ".".join(str(p) for p in err["loc"])
            msg = err["msg"]
            # "did you mean" via rapidfuzz for unknown fields
            if err["type"] == "extra_forbidden":
                closest = process.extractOne(field, KNOWN_FIELDS)
                if closest and closest[1] > 60:
                    msg += f" (did you mean <code>{closest[0]}</code>?)"
            errors.append(f"  • <code>{field}</code> — {msg}")
        return None, "⚠️ <code>deploy.config.yml</code> has errors:\n" + "\n".join(errors) + \
                     "\n\nFix these and retry the deploy."
```

**Example Telegram output:**

```
⚠️ deploy.config.yml has errors:
  • port — Input should be a valid integer, unable to parse 'tree-thousand'
  • target_sever — Extra inputs are not permitted (did you mean target_server?)
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
  "actor": "telegram:kalpesh281",
  "action": "deploy",
  "tool_tier": "notify",
  "target": "trading-dashboard",
  "params": { "branch": "main" },
  "target_server": "physical-main",
  "result": "success",
  "duration_ms": 47000
}
```

Actor format: `telegram:<username>` if the Telegram user has a username, else `telegram:<user_id>`.

---

## 15. Observability

- **Structured audit log** in Mongo (every action: actor, tier, result, duration)
- **Prometheus `/metrics`**: deploys_total, tool_calls_total, llm_tokens_total, container_restarts_total, image_cleanup_total
- **FastAPI `/health`** liveness endpoint — binds on `$AGENT_PORT` (default **8100 everywhere** — Mac dev + physical server). Unified because port 8000 on the physical server is owned by `voice-auth-backend`; picking 8100 once removes an env-specific footgun.
- **Per-deployment healthchecks** after every `docker run`
- **Scheduled health pings** every 5 min, alerts to Telegram on red
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
| **Streaming Telegram message edits** | Feels 2x faster |
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

**Entity selection:**

| Surface | Duration |
|---|---|
| Inline mode query (`@bot tra`) | ~80–120 ms (in-memory rapidfuzz + answer_inline_query) |
| Keyboard callback roundtrip | ~200–400 ms (network + `edit_message_text`) |

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
├── telegram_bot/                # Telegram bot (top-level)
│   ├── __init__.py
│   ├── bot.py                   # Application + dispatcher
│   ├── handlers.py              # CommandHandler + MessageHandler + CallbackQueryHandler + InlineQueryHandler
│   ├── keyboards.py             # InlineKeyboardMarkup builders
│   ├── messages.py              # HTML message builders
│   ├── colors.py                # Emoji palette
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
│   ├── deploy_agent.sh
│   └── telegram_commands.txt    # pasted into BotFather /setcommands
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
    "python-telegram-bot>=21.0.0",
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
	. .venv/bin/activate && uvicorn api.main:app --reload --host 0.0.0.0 --port $${AGENT_PORT:-8100}

run:
	. .venv/bin/activate && uvicorn api.main:app --host 0.0.0.0 --port $${AGENT_PORT:-8100}

test:
	. .venv/bin/activate && pytest tests/

lint:
	. .venv/bin/activate && ruff check . && ruff format --check .

type:
	. .venv/bin/activate && mypy agents/ api/ tools/ utils/ telegram_bot/ config/

clean:
	rm -rf .venv __pycache__ .pytest_cache .mypy_cache
```

---

## 20. Data Model (MongoDB)

### `users` (authorized Telegram users — GitHub-org-gated enrollment, §14.2)
```json
{
  "_id": 222333444,
  "telegram_username": "alice_dev",
  "telegram_first_name": "Alice",
  "github_username": "alicegithub",
  "github_org": "GradScalerTeam",
  "status": "active",
  "role": "member",
  "enrolled_by": "self",
  "enrolled_at": ISODate,
  "last_seen": ISODate,
  "last_verified": ISODate,
  "revoked_reason": null
}
```
Indexes: unique on `github_username` (one Telegram acct ↔ one GitHub handle); compound `(status, last_verified)` for the 24-hour re-verification sweep.

### `pending_enrollments` (short-lived enrollment conversation state)
```json
{
  "_id": 222333444,
  "awaiting": "github_username",
  "attempts": 0,
  "created_at": ISODate
}
```
TTL 24 h on `created_at` — abandoned enrollments auto-purge.

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
  "deployed_by": "telegram:kalpesh281"
}
```

### `audit_log`
See §14.6

### `container_logs` (persistent log ingestion — §9.3)
```json
{
  "_id": ObjectId,
  "deployment": "trading-dashboard",
  "target_server": "physical-main",
  "timestamp": "2026-04-24T12:34:56.123Z",
  "stream": "stdout",
  "line": "2026-04-24T12:34:56.123Z ERROR Mongo connection timeout",
  "level": "ERROR",
  "cluster_id": "mongo_timeout_<hash>",
  "created_at": ISODate
}
```
Indexes: compound `(deployment, timestamp DESC)` for range reads; TTL index on `created_at` — 604800 s (7 days, OD-L2).

### `diagnostic_events` (rule-engine matches — §9.3, §11.8)
```json
{
  "_id": ObjectId,
  "deployment": "trading-dashboard",
  "triggered_at": "2026-04-24T12:35:00Z",
  "rule": "mongo_timeout_spike",
  "severity": "error",
  "message": "42 mongo timeouts in last 5 min",
  "context_logs": ["...", "..."],
  "alerted": true,
  "created_at": ISODate
}
```
Indexes: compound `(deployment, triggered_at DESC)` for `/history`; TTL index on `created_at` — 2592000 s (30 days, OD-L3).

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
| **1** | Foundation + GitHub queries | Bot responds to all GitHub queries with inline-mode and keyboard selection. Zero LLM calls yet. |
| **2** | Multi-target deployment | End-to-end deploy via command (clone → build → push → pull → run). |
| **3** | Rollback, diagnostics, UI, cleanup | Full deploy lifecycle with diagnostics, rollback, image management, and rich Telegram UI — all with 0 tokens. |
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
# edit: GITHUB_TOKEN, OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, MONGO_URL,
#       ALLOWED_TELEGRAM_USERS, GITHUB_ORG, DOCKER_HUB_USER,
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

# 9. Telegram bot setup (one-time, via @BotFather)
#    DM @BotFather on Telegram:
#      /newbot       → pick a name + username, copy the token into TELEGRAM_BOT_TOKEN
#      /setcommands  → paste contents of scripts/telegram_commands.txt
#      /setprivacy   → enable (DM-only mode)
#      /setinline    → enable inline mode, placeholder: "search repos, branches, deployments"
#    Then /start your own bot and note your numeric user ID (from @userinfobot)
#    Add your user ID to ALLOWED_TELEGRAM_USERS in .env

# 10. Run the agent
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
| Random Telegram user runs commands | Allowlist of Telegram user IDs |
| LLM hallucinates a destructive tool call | Tier system + denylist + HITL approval |
| Compromised agent host → all client keys leak | PEMs in restricted folder, host hardening required |
| Mongo dump leaks env vars | Env vars in plain .env (noted trade-off — simple operation) |
| Telegram chat compromised | No secrets ever sent through Telegram |
| Telegram bot token leak | Immediate `/revoke` via @BotFather + rotate `TELEGRAM_BOT_TOKEN` in `.env` |
| Agent crash mid-deploy → orphaned containers | Mongo checkpointer resumes mid-graph |
| Disk fills up from old images | Auto-cleanup honoring `image_history` |
| Container escape from deployed app | Hardening flags: read-only, cap-drop, no-new-privileges, resource limits |
| Broken deploy in production | `/rollback` restores previous image in ~6s |
| Invalid `deploy.config.yml` wastes a build | Pydantic validation fails fast before build starts |

---

## 24. Verification (post-build checklist)

1. **Guardrails**: `/stop mongo` → refused (denylist). Non-allowlisted user runs `/deploy` → refused.
2. **Approval**: `/stop test-dep` → keyboard card → tap approve → container actually stops.
3. **Inline mode**: `@yourbot tra` → `trading-dashboard` appears in the top result within 200 ms.
4. **Fuzzy resolve**: `/deploy trding-dashbord main` → bot replies "did you mean `trading-dashboard`?" with confirm button; tapping confirm starts the deploy.
5. **Audit log**: any command → Mongo `audit_log` row with actor, tier, result, duration.
6. **Checkpointing**: start a deploy → kill agent mid-build → restart → resumes correctly.
7. **Metrics**: `curl http://localhost:8100/metrics` → Prometheus counters visible.
8. **Container hardening**: `docker inspect <svc>` → `ReadonlyRootfs: true`, `CapDrop: [ALL]`.
9. **Multi-target**: deploy with `target_server: client-acme-prod` → container on EC2, not physical.
10. **Identifier resolution**: `/logs trading-dashboard`, `/logs kalpesh281/trading-dashboard`, `/logs internal` → all resolve to same deployment.
11. **Auto-cleanup**: deploy 6 times → only last 5 images remain (history length).
12. **Rollback**: `/rollback name` → restores previous image in <10s, healthcheck passes.
13. **`/images`**: shows last 5 versions; "Remove old" button removes all but current + previous.
14. **Layer 1 diagnostics**: `/report name` → populated HTML message in <1s, 0 tokens.
15. **Layer 2 explain**: `/explain name` → AI hypothesis + token count in footer.
16. **YAML validation**: push a repo with typo'd field → Telegram error with "did you mean" suggestion.
17. **`.env` check**: `chmod 644 .env` → agent boot logs a warning.
18. **Dev → prod**: flip `physical-main.connection` ssh→local → no code changes → works.
19. **AI toggles**: set all three `ENABLE_*` flags to false → agent still deploys and diagnoses normally.
20. **CI**: push a PR with broken type → mypy/ruff/test failure in Actions.

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
| **No web dashboard** | Telegram-only | Telegram gives you HTML messages, inline keyboards, inline mode for free |
| **No per-argument autocomplete** | Telegram platform has no live per-argument completion | Mitigated by inline mode + keyboard fallback + fuzzy "did you mean?" · users adapt within a day · single-user personal tool, setup simplicity beats Discord's richer picker |

---

## 26. Resume Bullet

> Built a production-grade conversational DevOps AI agent (LangGraph + FastAPI + Telegram) that manages GitHub repositories and Docker deployments across multiple servers (physical + AWS EC2). Hybrid AI design: core features (deploy, rollback, diagnostics, entity selection) use **zero LLM calls** and work offline, while three opt-in AI features (free-text chat, pre-deploy Dockerfile review, `/explain` root-cause hypothesis) can be toggled independently via config flags. Includes tiered authorization with Telegram inline-keyboard-based human-in-the-loop approval, Mongo-backed LangGraph checkpointing for resumable graph execution, rapidfuzz-powered inline-mode entity search and keyboard fallback over a cached repo/branch list, a two-layer diagnostics system (regex + rule engine for Layer 1, LLM hypothesis on structured summaries for Layer 2 at <300 tokens/call), and a rich Telegram UI with emoji-coded HTML messages, inline-keyboard-paginated logs, and live-streaming deploy messages via `edit_message_text`. Replaces manual SSH workflows with single-command deployments, rollbacks, and diagnostics — reducing deploy time from ~10 minutes to ~25 seconds. Full monthly LLM cost: **~$0.10–$0.20**.

---

## 27. v3 Roadmap

- Web dashboard (React) alongside Telegram
- Telegram Mini App for richer in-chat UI (charts, tables)
- PR-triggered preview deployments via GitHub webhooks
- AWS SSM Session Manager as an alternative target type (keyless, audited)
- Traefik / Caddy reverse proxy with auto-SSL
- HashiCorp Vault integration for secrets
- Local Docker Hub pull-through cache (if deploy frequency grows)
- Multi-LLM provider support (Anthropic + OpenAI)
- Approval delegation (require 2 Telegram users for the most destructive ops)
- Webhook-driven GitHub cache invalidation (vs polling)
- Disk-based log archiving with search
- Cost tracking per deployment
