# Phase 3 — Telegram Bot Shell + GitHub Commands

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 2 |
| **Blocks** | Phases 5, 6, 7, 9, 10 (all user-facing commands need the bot) |
| **Spec references** | `docs/PROJECT_V2.md` §8 (commands), §10 (inline mode + keyboards), §11 (UI), §14.1 (allowlist), §22.9 (BotFather setup) |

---

## Objective

Wire `python-telegram-bot v21+` into the FastAPI lifespan and expose the six GitHub commands (`/repos`, `/branches`, `/commits`, `/prs`, `/files`, `/refresh`) with inline-mode fuzzy search, keyboard fallback, and "did you mean?" disambiguation. Zero LLM calls. User allowlist enforced.

## Design choices

| Choice | Why |
|---|---|
| **Bot polling started in FastAPI lifespan (not a separate process)** | Single-process simplicity; FastAPI is already running for `/health` and `/metrics`. |
| **`Application.run_polling()` isn't used — we use manual `start()/stop()` inside lifespan** | `run_polling()` owns the event loop; we need FastAPI to own it. We call `updater.start_polling()` explicitly. |
| **Allowlist check in a single decorator (`@require_allowlisted_user`)** | §14.1 — one check, applied to every handler. Silent drop (no reply) for unauthorized users to avoid enumeration. |
| **HTML parse mode by default, emoji from `colors.py`** | §11.1 — consistent palette across the bot. |
| **`edit_message_text` callback pattern** | §11.6 — keyboard callbacks edit the same message in place, never spam the chat. |
| **Inline query answers cached 60 s by Telegram** | `cache_time=60` in `answer_inline_query` — matches the GitHub cache refresh cadence. |
| **Commands registered with BotFather via `scripts/telegram_commands.txt`** | §22.9 — paste-friendly; the file is the canonical list. |

## Deliverables

### Files created

- `telegram_bot/colors.py` — `Colors` class (§11.1 emoji palette).
- `telegram_bot/formatters.py` — `format_uptime(seconds)`, `format_size_mb(bytes)`, `time_ago(dt)`.
- `telegram_bot/messages.py` — HTML builders: `build_repos_message`, `build_branches_message`, `build_commits_message`, `build_prs_message`, `build_files_message`, `build_error_message`.
- `telegram_bot/keyboards.py` — `build_repo_keyboard(query, action)`, `build_branch_keyboard(repo, query, action)`, `build_confirm_keyboard(action, target)`.
- `telegram_bot/handlers.py` — command handlers, inline query handler, callback query handler, authorization decorator.
- `telegram_bot/bot.py` — `build_application(settings)`, `start_bot(app, mongo)`, `stop_bot(app)`.
- `scripts/telegram_commands.txt` — BotFather `/setcommands` payload (all 20+ commands from §8, even the ones implemented by later phases, so the UI is consistent from day one).
- `api/main.py` — extended: lifespan now starts + stops the Telegram bot.
- `tests/unit/test_handlers_authz.py` — allowlist accept/reject logic.
- `tests/unit/test_messages.py` — HTML builders produce well-formed output.

### Commands this phase delivers (all tier=auto)

| Command | Handler | Data source |
|---|---|---|
| `/repos` | `cmd_repos` | `cache.repos` |
| `/branches <repo>` | `cmd_branches` | `cache.branches[repo]` |
| `/commits <repo> <branch>` | `cmd_commits` | live `PyGithub` via `list_commits` |
| `/prs <repo>` | `cmd_prs` | live via `list_prs` |
| `/files <repo> <branch>` | `cmd_files` | live via `list_files` |
| `/refresh` | `cmd_refresh` | forces `cache.refresh()` |
| `@bot <query>` | `inline_query_handler` | `cache.repos` via rapidfuzz |

### Folder tree delta

```
telegram_bot/
├── __init__.py
├── colors.py            ← new
├── formatters.py        ← new
├── messages.py          ← new
├── keyboards.py         ← new
├── handlers.py          ← new
└── bot.py               ← new
scripts/
└── telegram_commands.txt ← new
tests/unit/
├── test_handlers_authz.py
└── test_messages.py
```

## Prerequisites (before this phase starts)

Create the bot and fill `.env` Stage 2:

```bash
# 1. DM @BotFather on Telegram:
#    /newbot   → pick name + username, copy token
#    /setcommands → paste scripts/telegram_commands.txt (this phase creates it)
#    /setprivacy → enable
#    /setinline → enable, placeholder: "search repos, branches, deployments"

# 2. Get your Telegram user ID from @userinfobot

# 3. Fill .env:
#    TELEGRAM_BOT_TOKEN=0000000000:AA...
#    ALLOWED_TELEGRAM_USERS=<your-numeric-id>
```

## Verification

```bash
# 1. Unit tests
make test
# expect: all authz + message-builder tests green

# 2. Bot starts on lifespan
make dev
# expect: "telegram.bot.started" structlog line

# 3. Real Telegram tests (DM the bot)
#    /start           → welcome message, HTML formatted
#    /repos           → top 10 repos from GradScalerTeam, rest via "others…" keyboard
#    /branches trading-dashboard (or any repo) → branches list
#    @yourbot tra     → fuzzy match shows "trading-dashboard" in top result < 200 ms
#    /deploy trding main  (command exists but tool not wired yet)
#                     → "did you mean trading-dashboard?" with confirm button
#    (from a non-allowlisted account)
#    /repos           → no reply (silent drop)

# 4. Callback edits message in place
#    Tap "others…" on /repos result → same message updates (no new message sent)

# 5. /refresh forces cache rebuild
#    /refresh → "cache refreshed in <N>s" message; new data visible immediately

# 6. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [ ] Bot starts automatically on `make dev` and stops cleanly on Ctrl-C
- [ ] All six GitHub commands return correct data from GradScalerTeam
- [ ] Inline mode (`@yourbot tra`) returns results in <200 ms
- [ ] Fuzzy "did you mean?" prompt fires on typo'd repo name
- [ ] Non-allowlisted user gets **no reply** (silent drop, not an error message)
- [ ] Every message uses HTML parse mode and the `Colors` palette
- [ ] Callback queries edit the same message (never spam the chat)
- [ ] `/refresh` triggers `cache.refresh()` and reports duration
- [ ] All unit tests + `make lint` + `make typecheck` green

## What this phase does NOT do

- No `/deploy`, `/status`, `/logs`, etc. — later phases add those command handlers against already-existing tools
- No conversational free-text parsing (Phase 10)
- No approval/HITL flow (Phase 7)

## Rollback

```bash
rm -rf telegram_bot/colors.py telegram_bot/formatters.py \
       telegram_bot/messages.py telegram_bot/keyboards.py \
       telegram_bot/handlers.py telegram_bot/bot.py \
       scripts/telegram_commands.txt \
       tests/unit/test_handlers_authz.py tests/unit/test_messages.py
# revert api/main.py to its Phase 1 form (remove bot start/stop calls)
```

## Open questions

- None blocking. If the user wants webhook-based dispatch instead of polling, that's a v3 decision (§25).
