# DevOps AI Agent (v2)

A conversational AI agent (Telegram bot) that manages GitHub repositories and Docker deployments across multiple servers — your physical server plus client-specific AWS EC2 instances. Built with **LangGraph**, **FastAPI**, **OpenAI GPT-5.4-nano**, and the **Docker SDK**.

> **Design philosophy:** AI-enabled, not AI-dependent. Core features (listing, deploying, logs, diagnostics, rollback) use **zero LLM calls**. AI is an opt-in layer on top — free-text chat, pre-deploy config analysis, and on-demand root-cause hypothesis. Disable all AI with config flags and the tool still works end-to-end.

See [docs/PROJECT_V2.md](docs/PROJECT_V2.md) for the full specification.

---

## Features

- **Telegram-first conversational UX** — commands, inline-mode entity search, inline-keyboard selection, callback-query buttons, paginated logs
- **Multi-target deploys** — physical server + N client AWS EC2 instances, resolved per deploy
- **Build → Push → Pull → Run** pipeline using Docker Hub
- **Full image lifecycle** — `/deploy`, `/rollback`, `/images`, `/remove-images`, auto-cleanup after each deploy
- **Two-layer diagnostics** — `/report` (rule engine, 0 tokens) + `/explain` (LLM hypothesis, ~250 tokens)
- **Persistent log ingestion** — per-deployment background scraper → Mongo, browsable via `/history`
- **Readable UI** — emoji-coded HTML messages, level/time filters, cluster summaries
- **Pre-deploy config check** — optional Dockerfile + `deploy.config.yml` review (~550 tokens/deploy)
- **Tiered authorization** — auto / notify / approval, with typed-keyword confirmation for destructive ops
- **Audit log** in MongoDB — actor, action, tier, result, duration
- **LangGraph Mongo checkpointing** — resumes across restarts
- **Container hardening** — read-only FS, cap-drop, resource limits by default
- **Startup security checks** — `.env` and PEM permission validation

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| API | FastAPI (`/health`, `/metrics`) |
| Agent | LangGraph 1.0+ |
| LLM | OpenAI GPT-5.4-nano |
| Telegram | python-telegram-bot v21+ |
| GitHub | PyGithub |
| Docker | `docker` SDK for Python + BuildKit |
| DB | MongoDB (motor) |
| Fuzzy match | rapidfuzz |
| Tests | pytest + pytest-asyncio |
| Lint/Format | ruff |
| Type check | mypy |
| Env | Plain `venv` + `pyproject.toml` |

---

## Quick Start

### Prerequisites
- Python 3.11+
- Docker + Docker Hub account
- MongoDB (local or remote / Atlas)
- Telegram bot token (via @BotFather), GitHub PAT, OpenAI API key

### Setup

```bash
# 1. Clone
git clone <repo-url>
cd "Devops Agent"

# 2. Create venv and install
make install
# or manually:
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
chmod 600 .env
# fill in TELEGRAM_BOT_TOKEN, ALLOWED_TELEGRAM_USERS, GITHUB_TOKEN,
# OPENAI_API_KEY, MONGO_URL, DOCKER_HUB_USER, DOCKER_HUB_TOKEN

# 4. Set up PEM folder
sudo mkdir -p /devops_agent/pem
sudo chown $(whoami) /devops_agent/pem
chmod 700 /devops_agent/pem
# drop per-project PEMs: /devops_agent/pem/<project>.pem  (chmod 600)

# 5. Declare target servers
cp config/servers.example.yml secrets/servers.yml
chmod 600 secrets/servers.yml
# edit servers.yml — declare physical + any client EC2s

# 6. Run
make dev   # uvicorn with reload on :8000
```

See [docs/PROJECT_V2.md §15](docs/PROJECT_V2.md) for the full setup walkthrough, including the local-dev → physical-server migration path.

---

## Makefile targets

| Target | What it does |
|---|---|
| `make install` | Create `.venv` and install the package + dev deps |
| `make dev` | Run FastAPI with `--reload` on :8000 |
| `make run` | Run FastAPI (no reload) |
| `make test` | Run `pytest tests/` |
| `make lint` | `ruff check` + `ruff format --check` |
| `make typecheck` | `mypy` on `agents/ api/ tools/ utils/ discord_bot/ config/` |
| `make clean` | Remove `.venv`, caches |

---

## Project Layout

```
.
├── agents/          # LangGraph nodes + graph wiring
├── api/             # FastAPI app (health, metrics, webhooks)
├── telegram_bot/    # python-telegram-bot handlers, keyboards, messages
├── tools/           # github_*, docker_*, server_*, diagnose_*, image_*
├── utils/           # mongo, llm, docker context, fuzzy, log_scraper, log analyzer...
├── config/          # schemas, example configs
├── docs/            # architecture, security, runbook
├── tests/           # unit, integration, eval
├── scripts/         # setup_dev.sh, deploy_agent.sh
├── secrets/         # gitignored — servers.yml
├── logs/            # gitignored — runtime MD reports
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── Makefile
```

---

## Security

- **Secrets never committed** — `.env`, `secrets/`, and all `*.pem` files are gitignored
- **PEM folder** lives outside the repo at `/devops_agent/pem/` (`chmod 700`, files `chmod 600`)
- **Startup check** refuses to boot if `.env` has permissive permissions
- **`.dockerignore`** prevents secrets leaking into images
- **Tiered authorization** + human-in-the-loop interrupts for destructive operations
- **Container hardening** defaults: read-only FS, cap-drop, memory/CPU limits

See [docs/security.md](docs/security.md) for the threat model.

---

## Status

v2 is the production-hardened rewrite of v1. See [docs/PROJECT_V2.md](docs/PROJECT_V2.md) for goals, non-goals, and the full architecture.

## License

Private — personal project.
