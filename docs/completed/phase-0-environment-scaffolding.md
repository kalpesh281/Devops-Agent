# Phase 0 — Environment & Scaffolding

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETED |
| **Started on** | 2026-04-24 |
| **Completed on** | 2026-04-24 |
| **Depends on** | nothing |
| **Blocks** | every subsequent phase |
| **Spec references** | `docs/PROJECT_V2.md` §17 (folder tree), §18 (pyproject), §19 (Makefile), `README.md` Quick Start |

---

## Objective

Get the repo from "spec + docs only" to "a working Python 3.12 venv with every dependency installed, a runnable Makefile, a clean package layout, and Docker-build safety (`.dockerignore`)". No application code yet — just the build surface.

## Design choices

| Choice | Why |
|---|---|
| **Python 3.12** (pinned in `Makefile`) | Matches the physical server's 3.12.3 (per `docs/deployment/post-dev-deployment.md` §6) and every dependency in §18 has stable 3.12 wheels. |
| **Plain `venv` + `pyproject.toml`** | Spec mandate (§3). No Poetry / uv / Pipenv. |
| **`setuptools.packages.find` with explicit include** | Scopes the editable install to first-party packages (`agents/`, `api/`, `telegram_bot/`, `tools/`, `utils/`, `config/`) so pip doesn't walk `tests/`, `scripts/`, `secrets/`, `logs/`. |
| **`ruff` covers lint + format** | §3 — one tool, fast. |
| **`mypy` strict, per-package scope** | §3 — typechecks only first-party code; `tests/` relaxed. |
| **`pytest-asyncio` in `auto` mode** | Matches the codebase's async-first shape (FastAPI, motor, python-telegram-bot v21). |
| **`.dockerignore` excludes `secrets/`, `*.pem`, `.env`, `docs/`, `.git/`, `tests/`, `.venv/`** | Mandatory per §14.3 + spec §17 "`.dockerignore` must keep secrets out of images." |
| **`AGENT_PORT=8100` everywhere** | Unified port: Mac dev + physical server both use 8100. `voice-auth-backend` owns 8000 on prod, so we picked 8100 once and use it universally to avoid env-specific copy-paste mistakes. |

## Deliverables

### Files created

- `pyproject.toml` — deps (§18) + ruff + mypy + pytest + coverage config
- `Makefile` — `install`, `dev`, `run`, `test`, `lint`, `format`, `typecheck`, `clean`, `reset`, `help` (§19, with `python3.12` pin + clearer error if missing)
- `.dockerignore` — secret + artifact exclusions
- `agents/__init__.py`, `agents/nodes/__init__.py`
- `api/__init__.py`, `api/routes/__init__.py`
- `telegram_bot/__init__.py`
- `tools/__init__.py`
- `utils/__init__.py`
- `config/__init__.py`
- `tests/conftest.py` (empty, shared fixtures land here later)
- `secrets/.gitkeep`, `logs/.gitkeep` (so the gitignored dirs persist in git)
- `docs/phases/README.md` — phase tracker index
- `docs/phases/phase-0-environment-scaffolding.md` — this file
- `docs/completed/` — destination folder for finished phases

### Folder tree after this phase

```
devops-agent/
├── .claude/                 ✅ (pre-existing)
├── agents/
│   ├── __init__.py
│   └── nodes/__init__.py
├── api/
│   ├── __init__.py
│   └── routes/__init__.py
├── telegram_bot/__init__.py
├── tools/__init__.py
├── utils/__init__.py
├── config/__init__.py
├── tests/
│   ├── conftest.py
│   ├── unit/                (empty)
│   ├── integration/         (empty)
│   └── eval/                (empty)
├── scripts/                 (empty)
├── secrets/                 (.gitkeep only)
├── logs/                    (.gitkeep only)
├── docs/
│   ├── PROJECT_V2.md        ✅
│   ├── deployment/post-dev-deployment.md ✅
│   ├── phases/
│   │   ├── README.md
│   │   └── phase-0-environment-scaffolding.md
│   └── completed/           (empty)
├── .dockerignore
├── .env.example             ✅
├── .gitignore               ✅
├── CLAUDE.md                ✅
├── Makefile
├── pyproject.toml
└── README.md                ✅
```

## Verification

Run these in order. Every step must pass before this phase moves to `docs/completed/`.

```bash
# 1. Python 3.12 is available
python3.12 --version
# Expect: Python 3.12.x

# 2. Makefile help works (no syntax errors)
make help

# 3. Clean install creates venv + installs every dep
make install
# Expect: final line "✅ venv ready. Activate with: source .venv/bin/activate"
# Expect no pip resolver errors

# 4. Every first-party dep is importable
.venv/bin/python -c "import fastapi, uvicorn, langgraph, openai, github, docker, telegram, motor, pymongo, pydantic, pydantic_settings, yaml, prometheus_client, structlog, rapidfuzz, tabulate, rich; print('all deps OK')"
# Expect: all deps OK

# 5. Editable install registered our packages
.venv/bin/python -c "import agents, api, telegram_bot, tools, utils, config; print('all packages importable')"
# Expect: all packages importable

# 6. Ruff runs cleanly (no code yet, so no findings)
make lint
# Expect: "All checks passed!" + format check passes

# 7. pytest collects zero tests (no tests written yet)
make test
# Expect: "no tests ran" (exit code 5 is fine at this stage — Phase 1 adds the first tests)

# 8. .dockerignore blocks secrets (sanity)
grep -E '^(\.env|secrets/|\*\.pem)$' .dockerignore
# Expect: all three lines present
```

## Acceptance criteria

- [x] `make install` completes without errors (91 packages installed)
- [x] `.venv/` exists and is Python 3.12 (verified: 3.12.12)
- [x] All 18 runtime deps + 6 dev deps are installed
- [x] `agents`, `api`, `telegram_bot`, `tools`, `utils`, `config` all import without raising
- [x] `make lint` passes on the empty codebase (`All checks passed!`, `9 files already formatted`)
- [x] `.dockerignore` excludes `.env`, `secrets/`, `*.pem`, `.git/`, `tests/`, `.venv/`, `docs/`
- [x] Folder tree matches the diagram above
- [x] Moved to `docs/completed/` and phase index updated

## Verification log (2026-04-24)

```
✅ Python 3.12.12
✅ make help      — all 9 targets listed
✅ make install   — 91 packages installed, editable wheel built, "venv ready"
✅ deps import    — fastapi, uvicorn, langgraph, openai, github, docker, telegram,
                    motor, pymongo, pydantic, pydantic_settings, yaml,
                    prometheus_client, structlog, rapidfuzz, tabulate, rich
✅ packages import — agents, agents.nodes, api, api.routes, telegram_bot,
                    tools, utils, config
✅ make lint      — "All checks passed!" + "9 files already formatted"
✅ make test      — pytest exit 5 tolerated; exit 0 after Makefile fix
✅ .dockerignore  — .env, secrets/, *.pem all present
```

## Changes vs. the original plan

- **`make test` tolerates pytest exit code 5** (no-tests-collected) until Phase 2 adds the first unit tests. The Makefile wraps pytest with a shell conditional that exits 0 on code 5 only — any real test failure (exit 1, 2, 3, 4) still fails the target.

## What this phase explicitly does NOT do

- No actual application code (Phase 1+)
- No Dockerfile / docker-compose.yml (Phase 11)
- No tests beyond the empty `conftest.py` (Phase 2+)
- No `.env` — you must create your own (template is `.env.example`)
- No MongoDB setup — Phase 1 adds connection + TTL indexes
- No Telegram bot token — Phase 3 prerequisite

## Rollback

If this phase is backed out:

```bash
make clean
rm -f pyproject.toml Makefile .dockerignore
rm -rf agents/ api/ telegram_bot/ tools/ utils/ config/ tests/ logs/ secrets/
# leaves README.md, CLAUDE.md, docs/, .env.example, .gitignore untouched
```

The repo returns to its pre-Phase-0 "spec-only" state.

## Open questions for later phases (tracked here so they don't get lost)

- **Phase 2** — `GITHUB_ORG=GradScalerTeam` confirmed. The cache loader should accept both orgs and personal accounts (future-proof).
- **Phase 10** — OpenAI model name: `gpt-5.4-nano` in the spec isn't a real OpenAI model. Default to `gpt-4o-mini` unless told otherwise before Phase 10 starts.
- **Phase 3** — Telegram bot token + `ALLOWED_TELEGRAM_USERS` list must be in `.env` before we can start this phase.
- **Phase 5** — `docker login` on the dev machine required; push test needs a Docker Hub namespace (`DOCKER_HUB_USER`).
