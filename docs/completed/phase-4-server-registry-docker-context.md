# Phase 4 — Server Registry + Docker Context

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETED |
| **Started on** | 2026-04-25 |
| **Completed on** | 2026-04-25 |
| **Depends on** | Phase 3 |
| **Blocks** | Phase 5 (deploy needs a target), Phase 8 (diagnostics need Docker context), Phase 9 (scraper needs Docker context) |
| **Spec references** | `docs/PROJECT_V2.md` §5 (server registry), §6 (dev vs prod), §14.4 (deploy config schema), §20 (`servers` collection) |

---

## Objective

Load `secrets/servers.yml` into the Mongo `servers` collection on startup, provide a Docker client factory that returns the right daemon per target (`connection: local` vs `connection: ssh`), validate `deploy.config.yml` with a strict Pydantic schema, and expose `/servers`, `/status`, `/disk` commands.

## Design choices

| Choice | Why |
|---|---|
| **Server registry is file-only (`secrets/servers.yml`)** | §5.1 — no chat command can add/remove servers. Upsert on startup ensures Mongo matches file. |
| **`connection: local` uses default Docker socket; `connection: ssh` uses `docker.DockerClient(base_url="ssh://user@host")`** | §6 — one line flips dev → prod. Docker SDK's context system handles it with no code branches. |
| **Docker clients are cached in-memory by server ID, rebuilt only on config change** | Avoids paying the SSH-connect cost per command. |
| **PEM path resolution: `${PEM_DIR}/${servers[i].pem}.pem`** | §5.2 — agent never hard-codes paths; `pem:` field is a stem, path is composed. Missing PEM → raise `PemNotFoundError` before any connection attempt. |
| **`DeployConfig` Pydantic model uses `model_config = {"extra": "forbid"}`** | §14.4 — unknown fields are errors; rapidfuzz suggests "did you mean". |
| **`/status` table uses `tabulate` in `<pre>` block** | §11.4 — monospace alignment in Telegram. |
| **`target_server` in `DeployConfig` must resolve to an entry in `servers.yml`** | Fail-fast validation at config load, not deploy time. |

## Deliverables

### Files created

- `config/deploy_config_schema.py` — `DockerHubConfig`, `ResourceLimits`, `DeployConfig` (Pydantic v2, `extra="forbid"`).
- `config/servers.example.yml` — canonical example (physical + one EC2 stub).
- `docs/deploy.config.example.yml` — committed example for repo authors.
- `utils/server_registry.py` — `load_servers_yml()`, `sync_to_mongo(db, servers)`, `get_server(server_id)`.
- `utils/docker_context.py` — `get_docker_client(server_id)`, `invalidate(server_id)`, caching logic.
- `tools/server_tools.py` — `/servers`, `/status`, `/disk` registered as `@tool` (all tier=auto). Identifier resolution per §8.
- `tests/unit/test_deploy_config_schema.py` — valid configs pass, unknown fields rejected, "did you mean" suggestion generated.
- `tests/unit/test_server_registry.py` — YAML parsing + Mongo upsert with `mongomock` or a test DB.
- `tests/unit/test_docker_context.py` — client factory branches on connection type (mocked `docker.DockerClient`).

### Commands this phase delivers

| Command | Tier | Source |
|---|---|---|
| `/servers` | auto | `servers` collection |
| `/status` | auto | `deployments` + `docker.containers.list()` per server |
| `/status <server>` | auto | filter by target |
| `/disk <server>` | auto | `docker system df` via Docker SDK |

### Folder tree delta

```
config/
├── deploy_config_schema.py   ← new
└── servers.example.yml       ← new
docs/
└── deploy.config.example.yml ← new
utils/
├── server_registry.py        ← new
└── docker_context.py         ← new
tools/
└── server_tools.py           ← new
tests/unit/
├── test_deploy_config_schema.py
├── test_server_registry.py
└── test_docker_context.py
```

## Verification

```bash
# 0. Prerequisites
cp config/servers.example.yml secrets/servers.yml
chmod 600 secrets/servers.yml
# Edit: keep "physical-main" with connection: local (talks to your Mac's Docker Desktop)

# 1. Unit tests
make test

# 2. On boot, servers.yml upserts into Mongo
make dev
mongosh "$MONGO_URL" devops_agent --eval 'db.servers.find().pretty()'
# expect: at least one entry matching servers.yml

# 3. Command: /servers
#    → should list "physical-main" with connection: local

# 4. Command: /status
#    → should render an empty tabulate table inside <pre> (no deployments yet)

# 5. Docker client factory works locally
.venv/bin/python -c "
from utils.docker_context import get_docker_client
c = get_docker_client('physical-main')
print(c.version()['Version'])
"
# expect: a Docker Desktop version string (e.g. '28.3.2')

# 6. DeployConfig schema rejects unknowns
.venv/bin/python -c "
import yaml
from config.deploy_config_schema import DeployConfig
from pydantic import ValidationError
try:
    DeployConfig.model_validate({
        'name': 'x', 'stack': 'node', 'port': 3000,
        'target_sever': 'physical-main',  # typo
        'docker_hub': {'image': 'me/x'},
    })
except ValidationError as e:
    print('rejected typo:', e.errors()[0]['type'])
"
# expect: rejected typo: extra_forbidden

# 7. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [x] `secrets/servers.yml` loads into Mongo on every startup; stale entries removed (`sync_to_mongo` drops any `_id` not in the YAML; verified by `test_sync_removes_stale_entries`)
- [x] `get_docker_client(ServerConfig)` returns a working client (verified locally — builds the SDK client successfully; ``.version()`` works whenever Docker Desktop is running, and ``ping()`` returns a structured ``{ok: False, error}`` when it's not)
- [x] `/servers` lists all targets; `/status` shows empty table; `/disk physical-main` renders the df summary (all three wired in `telegram_bot/handlers.py` + `messages.py`)
- [x] DeployConfig rejects extra fields with a friendly "did you mean" message (`test_extra_field_rejected_with_did_you_mean`)
- [x] Identifier resolution via rapidfuzz on `/status` / `/disk` — missing id triggers fuzzy-suggest reply (`_resolve_server_id`)
- [x] Docker client cache invalidated when server config changes (`test_config_change_invalidates_cache`)
- [x] `make lint` + `make typecheck` + unit tests all clean — 68/68 passing

## What this phase does NOT do

- No deploy pipeline yet — `/deploy` is in Phase 5
- No SSH target testing — dev stays on local Docker Desktop; SSH path is implemented but not exercised until Phase 12
- No real EC2 target configured in `servers.yml` — that's user data, filled per-client at onboarding time

## Rollback

```bash
rm -rf config/deploy_config_schema.py config/servers.example.yml \
       docs/deploy.config.example.yml \
       utils/server_registry.py utils/docker_context.py \
       tools/server_tools.py \
       tests/unit/test_deploy_config_schema.py \
       tests/unit/test_server_registry.py \
       tests/unit/test_docker_context.py
# revert api/main.py lifespan (remove sync_to_mongo call)
```
