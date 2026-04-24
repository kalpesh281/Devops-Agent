# Phase Tracker

Each phase has a dedicated markdown file with objectives, deliverables, verification steps, and acceptance criteria. When a phase is **completed AND verified**, move its file from `docs/phases/` to `docs/completed/` and flip `Status` to `✅ COMPLETED` with the `Completed on` date.

## Workflow

```
docs/phases/<phase>.md          ← active / in-progress / queued
         │
         │  1. implement per "Deliverables"
         │  2. run "Verification" steps — all must pass
         │  3. tick every "Acceptance criteria" checkbox
         │  4. mv docs/phases/<phase>.md docs/completed/<phase>.md
         ▼
docs/completed/<phase>.md       ← frozen record of what shipped
```

## Phase index

| # | Phase | Status | File |
|---|---|---|---|
| 0  | Environment & scaffolding             | ✅ COMPLETED   | [`../completed/phase-0-environment-scaffolding.md`](../completed/phase-0-environment-scaffolding.md) |
| 1  | Config, logging, Mongo plumbing       | ✅ COMPLETED   | [`../completed/phase-1-config-logging-mongo.md`](../completed/phase-1-config-logging-mongo.md) |
| 2  | GitHub layer (cache + tool registry)  | ✅ COMPLETED   | [`../completed/phase-2-github-layer.md`](../completed/phase-2-github-layer.md) |
| 3  | Telegram bot shell + GitHub commands  | ⚪ QUEUED      | [`phase-3-telegram-bot-shell.md`](phase-3-telegram-bot-shell.md) |
| 4  | Server registry + Docker context      | ⚪ QUEUED      | [`phase-4-server-registry-docker-context.md`](phase-4-server-registry-docker-context.md) |
| 5  | Deploy pipeline (build → push → pull → run) | ⚪ QUEUED | [`phase-5-deploy-pipeline.md`](phase-5-deploy-pipeline.md) |
| 6  | LangGraph agent (graph + nodes)       | ⚪ QUEUED      | [`phase-6-langgraph-agent.md`](phase-6-langgraph-agent.md) |
| 7  | Rollback + destructive ops (HITL + typed-confirm) | ⚪ QUEUED | [`phase-7-rollback-destructive-ops.md`](phase-7-rollback-destructive-ops.md) |
| 8  | Layer 1 diagnostics                   | ⚪ QUEUED      | [`phase-8-layer-1-diagnostics.md`](phase-8-layer-1-diagnostics.md) |
| 9  | Persistent log scraper + `/history`   | ⚪ QUEUED      | [`phase-9-log-scraper-history.md`](phase-9-log-scraper-history.md) |
| 10 | AI layer (free-text, pre-deploy, `/explain`) | ⚪ QUEUED | [`phase-10-ai-layer.md`](phase-10-ai-layer.md) |
| 11 | Tests, CI, Dockerfile, docker-compose | ⚪ QUEUED      | [`phase-11-tests-ci-docker.md`](phase-11-tests-ci-docker.md) |
| 12 | Physical-server deployment            | ⚪ QUEUED      | [`phase-12-physical-server-deployment.md`](phase-12-physical-server-deployment.md) |

## Legend

- ⚪ **QUEUED** — not started
- 🟡 **IN PROGRESS** — under active implementation
- 🔵 **TESTING** — implemented, verification in progress
- ✅ **COMPLETED** — verified and moved to `docs/completed/`
- 🔴 **BLOCKED** — waiting on external input (bot token, server access, etc.)

Each phase doc follows a standard template (see `../completed/phase-0-environment-scaffolding.md` for the canonical shape).

## Next up

**Phase 3** is the next queued phase. It delivers the Telegram bot shell — `python-telegram-bot v21+`, inline-mode entity search, keyboard fallback, "did you mean?" fuzzy resolution, and the six GitHub commands (`/repos`, `/branches`, `/commits`, `/prs`, `/files`, `/refresh`) wired to the Phase 2 tools. Still 0 LLM calls.

**Prerequisite before starting Phase 3:** create a Telegram bot via @BotFather and add `TELEGRAM_BOT_TOKEN` + `ALLOWED_TELEGRAM_USERS` to `.env`. See `docs/PROJECT_V2.md` §22.9 for the BotFather setup steps.
