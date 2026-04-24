# Phase 1 — Config, Logging, Mongo Plumbing

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 0 |
| **Blocks** | Phases 2–12 |
| **Spec references** | `docs/PROJECT_V2.md` §3 (stack), §12.3 (token caps), §13 (toggles), §14.3 (secrets check), §15 (observability), §20 (data model) |

---

## Objective

Stand up the FastAPI application shell, Mongo connection, structured logging, and the startup security check. End state: `make dev` boots, `curl :8000/health` returns `{"status":"ok","mongo":"connected"}`, and every subsequent phase has a clean config object + Mongo handle + logger to use.

## Design choices

| Choice | Why |
|---|---|
| **`pydantic-settings` for `Settings`** | Type-safe access to every `.env` var; fails loudly on missing required vars. |
| **Single `Settings()` instance exported as module-level `settings`** | One import, one place that knows what's configured. |
| **`motor.AsyncIOMotorClient` on the FastAPI lifespan** | One connection pool for the whole app (checkpointer, audit log, cache, scraper all share it, per §7.4). |
| **TTL indexes created on startup, idempotently** | `checkpoints` 7d, `container_logs` 7d, `diagnostic_events` 30d (§20). Idempotent `create_index` is safe to re-run. |
| **`structlog` in JSON mode** | §15 observability: one line per event, grep/jq-friendly, stdout-only (systemd/journalctl picks it up in prod). |
| **`verify_env_security()` runs at startup, warns but does not refuse boot** | §14.3 says "warns loudly on permissive modes" — warning, not fatal. |
| **`/health` returns a shape that exposes Mongo status** | Cheap monitor signal: if Mongo drops, `/health` goes red before any request fails. |
| **`/metrics` uses `prometheus-client` default registry** | §15: `deploys_total`, `tool_calls_total`, `llm_tokens_total` etc. get registered by later phases against the same registry. |

## Deliverables

### Files created

- `config/settings.py` — `Settings` class with every Stage 1 + Stage 2 + Stage 3 var from `.env.example`; feature toggles (`ENABLE_FREE_TEXT_CHAT`, `ENABLE_PREDEPLOY_ANALYSIS`, `ENABLE_EXPLAIN_COMMAND`, `ENABLE_LOG_ALERTS`).
- `config/token_limits.py` — `TOKEN_BUDGETS` dict per §12.3 (`intent_parse: 1000`, `predeploy: 2000`, `explain: 800`).
- `utils/logger.py` — `structlog` setup, `get_logger(name)` helper, JSON output configurable via `LOG_LEVEL`.
- `utils/mongo.py` — module-level `client`, `db`, `ensure_indexes()`, `close()`.
- `utils/secrets_check.py` — `verify_env_security()` per §14.3.
- `api/main.py` — FastAPI `app`, lifespan that: runs secrets check → connects Mongo → ensures indexes → yields → closes Mongo. Registers `/health` and `/metrics` routers.
- `api/routes/health.py` — `GET /health` returns `{"status": "ok", "mongo": "connected" | "down"}`.
- `api/routes/metrics.py` — `GET /metrics` returns `prometheus_client.generate_latest()` with correct content-type.
- `tests/unit/test_settings.py` — assertions that required fields raise when missing, defaults applied correctly.
- `tests/unit/test_secrets_check.py` — perm-mode logic tested with `tmp_path` fixtures.

### Folder tree delta

```
config/
├── __init__.py
├── settings.py          ← new
└── token_limits.py      ← new
utils/
├── __init__.py
├── logger.py            ← new
├── mongo.py             ← new
└── secrets_check.py     ← new
api/
├── __init__.py
├── main.py              ← new
└── routes/
    ├── __init__.py
    ├── health.py        ← new
    └── metrics.py       ← new
tests/unit/
├── test_settings.py     ← new
└── test_secrets_check.py ← new
```

## Verification

```bash
# 0. Prerequisites
cp .env.example .env
chmod 600 .env
# fill: MONGO_URL, GITHUB_TOKEN (dummy OK), OPENAI_API_KEY (dummy OK),
#       GITHUB_ORG=GradScalerTeam, DOCKER_HUB_USER, DOCKER_HUB_TOKEN
# Leave Stage 2 placeholders until Phase 3.

# 1. Unit tests pass
make test

# 2. App boots
make dev
# expect: uvicorn log "Application startup complete"
# expect: structlog JSON line "mongo.connected"

# 3. Health endpoint
curl -s http://localhost:8000/health | python3 -m json.tool
# expect: {"status":"ok","mongo":"connected","version":"0.1.0"}

# 4. Metrics endpoint (Prometheus format)
curl -s http://localhost:8000/metrics | head -5
# expect: lines like "# HELP python_info Python runtime information"

# 5. Secrets check warns on loose perms
chmod 644 .env; make dev 2>&1 | grep -i "permissive" && chmod 600 .env
# expect: at least one WARNING line mentioning .env permissions

# 6. Mongo TTL indexes created
mongosh "$MONGO_URL" devops_agent --eval '
  ["checkpoints","container_logs","diagnostic_events"].forEach(c =>
    print(c, JSON.stringify(db[c].getIndexes().filter(i => i.expireAfterSeconds))))'
# expect: three collections each showing one TTL index

# 7. Typecheck passes on Phase 1 files
make typecheck
```

## Acceptance criteria

- [ ] `make dev` boots without exception; lifespan logs `mongo.connected`
- [ ] `/health` returns `{"status":"ok","mongo":"connected"}` when Mongo is up
- [ ] `/health` returns `{"status":"ok","mongo":"down"}` (HTTP 503) when Mongo is killed
- [ ] `/metrics` returns Prometheus text format
- [ ] TTL indexes present on `checkpoints` (7d), `container_logs` (7d), `diagnostic_events` (30d)
- [ ] `verify_env_security()` warns on `chmod 644 .env`, passes silently on `600`
- [ ] All unit tests green; `make lint` + `make typecheck` clean
- [ ] `utils.logger.get_logger(__name__)` produces JSON lines

## What this phase does NOT do

- No LangGraph, no tools, no Telegram, no GitHub (later phases)
- No `/health` check of remote target servers — just Mongo
- No metrics counters yet (registered lazily by phases that emit them)

## Rollback

```bash
rm -rf config/settings.py config/token_limits.py \
       utils/logger.py utils/mongo.py utils/secrets_check.py \
       api/main.py api/routes/health.py api/routes/metrics.py \
       tests/unit/test_settings.py tests/unit/test_secrets_check.py
```
