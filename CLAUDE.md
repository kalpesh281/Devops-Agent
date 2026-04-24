# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo state

This is currently a **spec-only repository**. The only source of truth for scope, architecture, and conventions is `docs/PROJECT_V2.md` (v2 supersedes an older v1). `README.md` is the short-form summary. No implementation code exists yet — if you are asked to build something, read `docs/PROJECT_V2.md` end-to-end first; do not infer architecture from the folder layout (the folders in §17 of the spec do not yet exist on disk).

## Commands

The spec defines a `Makefile` (not yet materialized). Once `make install` has been run and `.venv/` exists, the agreed-upon commands are:

| Command | Purpose |
|---|---|
| `make install` | Create `.venv` and `pip install -e ".[dev]"` |
| `make dev` | `uvicorn api.main:app --reload --port 8100` |
| `make run` | `uvicorn api.main:app --port 8100` (no reload) |
| `make test` | `pytest tests/` |
| `make lint` | `ruff check .` + `ruff format --check .` |
| `make typecheck` | `mypy agents/ api/ tools/ utils/ discord_bot/ config/` |
| `make clean` | Remove `.venv` and caches |

Running a single test: `. .venv/bin/activate && pytest tests/unit/test_log_analyzer.py::test_name -v`.

Dependency management is **plain `venv` + `pyproject.toml`**. Do not introduce Poetry, uv, or Pipenv.

## Architecture — what requires reading multiple files to understand

### Core design rule: AI-enabled, not AI-dependent

Every core feature (listing, deploy, rollback, logs, diagnostics, status, autocomplete) MUST work with **zero LLM calls**. LLM calls are confined to three opt-in features, each controlled by a flag in `config/settings.py`:

- `ENABLE_FREE_TEXT_CHAT` — free-text intent parsing (~230 tokens)
- `ENABLE_PREDEPLOY_ANALYSIS` — Dockerfile/config review before `/deploy` (~550 tokens)
- `ENABLE_EXPLAIN_COMMAND` — `/explain <name>` root-cause hypothesis (~250 tokens)

If you add a feature and it calls the LLM on the hot path without a flag, you have violated the design. Slash commands, autocomplete, Layer 1 diagnostics, formatting, and approvals are always 0-token.

### Tiered authorization + LangGraph HITL

Every tool is tagged with a tier in `config/tool_tiers.yml`:

- **auto** — GitHub queries, logs, inspect, report, status, health, images → execute immediately
- **notify** — deploy, restart, redeploy → execute and post a notification
- **approval** — stop, rollback, remove-images, cleanup, delete-deployment → LangGraph interrupt → Telegram inline-keyboard button → typed-keyword confirmation (`ACTION NAME`, 60s timeout) → resume

The Mongo checkpointer (`langgraph-checkpoint-mongodb`) is load-bearing here: approval interrupts must survive agent restarts. A TTL index expires checkpoints after 7 days. Denylist (e.g. `mongo`, `agent`, `traefik`) overrides tier — these can never be stopped/deleted via chat regardless of approval.

### Multi-target deployment model

Target servers are declared in **`secrets/servers.yml` only** (gitignored, mode 600). No chat command can add/remove/edit servers — this is intentional and enforced. On startup the file is upserted into the Mongo `servers` collection.

PEM files live **outside the repo** at `/devops_agent/pem/<project>.pem` (folder `700`, files `600`). Each repo's `deploy.config.yml` has a `project:` field; the agent resolves the PEM by that name. Missing PEM → fail fast.

Dev-vs-prod delta is **one line**: `connection: ssh` (dev, agent on laptop reaches physical over SSH) vs `connection: local` (prod, agent runs on the physical server and talks to the local Docker daemon). No code branches on this — the Docker SDK's context system handles it.

### Tool registry pattern

Tools are registered via a `@tool(name, tier, description, schema)` decorator into a single `REGISTRY` dict (see spec §7.3). Adding a new tool is one decorator; the LangGraph graph never changes. Preserve this invariant — do not hardcode tool lists in graph nodes.

### Two-layer diagnostics

- **Layer 1** (`utils/docker_diagnostics.py`, `utils/log_analyzer.py`, `utils/report_builder.py`) — pure Python: `docker inspect` parsing + regex + clustering + a rule engine. Runs on every `/logs`, `/inspect`, `/health`, `/report`. Must work offline and in sub-second time.
- **Layer 2** (`tools/explain_tool.py`) — sends the **Layer 1 structured summary** (not raw logs) to the LLM on `/explain`. This keeps input ~150 tokens instead of ~6000. Do not pass raw logs to the LLM.

### Slash + autocomplete over a cached index

`utils/github_cache.py` holds repos/branches in memory, refreshed by a background task every 5 min (see spec §10). Autocomplete handlers in `discord_bot/commands.py` use `rapidfuzz` against that cache. `/repos`, `/branches`, etc. read from cache, not from GitHub live. `/refresh` forces a re-fetch.

### Identifier resolution for `<name>` args

Any command that takes a deployment `<name>` accepts container name, repo name, or project tag. Resolution order (see spec §8):
1. Exact match on `deployments._id`
2. Exact match on `deployments.repo`
3. Exact match on `deployments.project`
4. Fuzzy substring → disambiguation picker if multiple hits

### Graph shape

`agents/graph.py` wires: `START → validate_auth → route_input → (parse_intent if free-text) → classify_tier → (approval interrupt | pre_deploy_check) → execute_tool → format_response → audit_log → END`. The `audit_log` node **always runs, even on errors**.

### Auto-cleanup invariants (images)

After every successful deploy: always keep the running image + everything in `deployments.image_history` (last 5), delete older tags for the same repo only, prune dangling layers older than 168h. **Never touch images from other repos.** Every deletion is audit-logged.

## Conventions worth remembering

- **Image tags**: commit SHA + `:latest`. Image name is `DOCKERHUB_USER/<repo>`.
- **Container hardening defaults** on every `docker run`: `--read-only` (+ tmpfs `/tmp`), `--cap-drop=ALL`, `--security-opt no-new-privileges`, memory/cpus/pids limits. Warn if Dockerfile has no `USER` directive.
- **`.env` and PEM permission check** runs at startup via `utils/secrets_check.py`; warns loudly on permissive modes.
- **`deploy.config.yml`** is validated with Pydantic (`model_config = {"extra": "forbid"}`); unknown fields are errors. Use rapidfuzz to suggest "did you mean" corrections.
- **Token budgets** are hard-capped per call in `config/token_limits.py`; truncate inputs that exceed them rather than letting costs run.
- **Long operations** edit a single Telegram message in place via `context.bot.edit_message_text` (spec §11.6). Do not spam the chat with one message per step.
- **Emoji palette** is centralized in `telegram_bot/colors.py` (🟢🟡🟠🔴🔵🟣⚪); use it rather than hardcoding emoji or status strings.
- **Persistent logs** — every running deployment has a 60s background scraper (spec §9.3) that flushes to `container_logs` (TTL 7d) and runs the rule engine into `diagnostic_events` (TTL 30d). `/logs` and `/history` read from Mongo; `/report` can bypass the cache with a live `docker logs` call when freshness matters.
- **Destructive ops require typed confirmation** — button tap alone is not enough. User must type the full `ACTION NAME` form (e.g. `STOP trading-dashboard`) within 60s. Timeouts + mismatches are audit-logged as `aborted_typed_confirm_*`.

## Security

- `.env`, `secrets/`, and all `*.pem` files are gitignored; never stage them.
- `.dockerignore` must keep secrets out of images.
- Discord user allowlist + GitHub org/repo allowlist gate every command.
