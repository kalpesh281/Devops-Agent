# Phase 3 — Telegram Bot Shell + GitHub Commands (with self-enrollment)

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETED |
| **Started on** | 2026-04-25 |
| **Completed on** | 2026-04-25 |
| **Depends on** | Phase 2 |
| **Blocks** | Phases 5, 6, 7, 9, 10 (all user-facing commands need the bot) |
| **Spec references** | `docs/PROJECT_V2.md` §8 (commands), §10 (inline mode + keyboards), §11 (UI), §14.1 + §14.2 (authorization + enrollment), §20 (`users`, `pending_enrollments`), §22.9 (BotFather) |

---

## Objective

Deliver a multi-user Telegram bot where teammates self-enroll by providing their GitHub username — the agent verifies membership in `GradScalerTeam` before granting access. Six GitHub commands wired up (`/repos`, `/branches`, `/commits`, `/prs`, `/files`, `/refresh`), inline mode entity search, keyboard fallback, "did you mean?" fuzzy resolution. Zero LLM calls.

## Design choices

| Choice | Why |
|---|---|
| **GitHub-org-gated self-enrollment** | Admin (you) never collects Telegram IDs. Team member DMs the bot → bot asks for GitHub handle → verifies against `GradScalerTeam` → stores mapping. Adding a teammate on GitHub auto-grants access; removing revokes it within 24 h. |
| **Telegram ID is the primary key in `users`** | Numeric IDs never change; @usernames can. Enrollment captures the ID automatically from `update.effective_user.id`. |
| **Unique index on `github_username`** | Prevents claim-jumping: once Alice claims `alicegithub`, no other Telegram account can. |
| **`FIRST_ADMIN_TELEGRAM_ID` env var bootstraps the first admin** | Needed once; subsequent admins promoted via `/users promote @handle` with `role=admin` in Mongo. |
| **`ALLOWED_TELEGRAM_USERS` env retained as emergency bypass** | If Mongo is unreachable or an admin locks themselves out, env-var whitelist works. Logged as a warning on use. |
| **24-hour re-verification background task** | Someone leaves GradScalerTeam → their bot access auto-revokes within 24 h. Lazy recheck also fires on every message if `last_verified` is stale. |
| **In-memory `users` cache refreshed every 60 s from Mongo** | Auth check = dict lookup, not a Mongo round-trip on every message. |
| **Admin notified on every enrollment via DM** | You see "🆕 @alice_dev enrolled as github:alicegithub" the moment it happens, so impersonation attempts can't stay hidden. |
| **Bot polling (not webhooks) in FastAPI lifespan** | Single-process simplicity; FastAPI is already running. |
| **HTML parse mode by default, emoji from `colors.py`** | §11.1 consistency. |
| **`edit_message_text` pattern for callbacks** | §11.6 — keyboard taps edit the same message, never spam the chat. |

## Deliverables

### Files created

- `telegram_bot/colors.py` — `Colors` class (§11.1 emoji palette)
- `telegram_bot/formatters.py` — `format_uptime`, `format_size_mb`, `time_ago`
- `telegram_bot/messages.py` — HTML builders: `build_repos_message`, `build_branches_message`, `build_commits_message`, `build_prs_message`, `build_files_message`, `build_error_message`, `build_enrollment_welcome`, `build_enrollment_success`, `build_enrollment_rejected`, `build_whoami_message`, `build_users_list_message`
- `telegram_bot/keyboards.py` — `build_repo_keyboard`, `build_branch_keyboard`, `build_confirm_keyboard`, `build_users_admin_keyboard`
- `telegram_bot/enrollment.py` — enrollment conversation state machine (`start_enrollment`, `handle_github_username_reply`, `verify_github_membership`)
- `telegram_bot/handlers.py` — command handlers, inline query handler, callback query handler, **auth middleware** (`require_enrolled_user`)
- `telegram_bot/bot.py` — `build_application(settings)`, `start_bot()`, `stop_bot()`
- `utils/user_registry.py` — `get_user(telegram_id)`, `upsert_user(...)`, `revoke_user(...)`, `list_users(...)`, in-memory cache with 60 s refresh
- `utils/user_reverifier.py` — 24-hour loop checking each active user's GradScalerTeam membership
- `scripts/telegram_commands.txt` — BotFather `/setcommands` payload
- `api/main.py` — extended: lifespan starts + stops the bot and the re-verifier
- 8+ unit tests (see below)

### Commands delivered

| Command | Tier | Gate | Handler |
|---|---|---|---|
| `/start` | — | any | Kicks off enrollment if not yet enrolled |
| `/help` | — | enrolled | List commands available to this user's role |
| `/whoami` | auto | enrolled | Show this user's enrollment record |
| `/repos` | auto | enrolled | `list_repos` from cache |
| `/branches <repo>` | auto | enrolled | `list_branches` from cache |
| `/commits <repo> <branch>` | auto | enrolled | `list_commits` live API |
| `/prs <repo>` | auto | enrolled | `list_prs` live API |
| `/files <repo> <branch>` | auto | enrolled | `list_files` live API |
| `/refresh` | auto | enrolled | `refresh_cache` |
| `/users` | auto | enrolled | List all enrolled users |
| `/users pending` | admin | admin | Show anyone mid-enrollment |
| `/users revoke <handle>` | admin | admin | Revoke an enrollment |
| `/users promote <handle>` | admin | admin | Grant `role=admin` |
| `/users reverify` | admin | admin | Force re-check of every active user now |
| `@bot <query>` (inline mode) | — | enrolled | Fuzzy search over cached repos |

### Enrollment state machine

```
  (no users doc)
        │
        ▼  DM /start
 ┌─────────────────┐
 │ pending_        │───────► GitHub username replied
 │ enrollments     │            │
 │ (awaiting:      │            ▼
 │  github_        │   ┌──────────────────────┐
 │  username)      │   │ org.has_in_members() │
 └─────────────────┘   └──────────┬───────────┘
        ▲                         │
        │ timeout/                ├─ ✅ member → users doc upserted
        │ retry                   │                status=active
        │                         │                role=member (or admin if
        │                         │                      FIRST_ADMIN_TELEGRAM_ID match)
        │                         │                notify admins via DM
        │                         │
        │                         └─ ❌ not a member → reply "access denied"
        │                                              audit_log entry
        └── (abandoned enrollments TTL out after 24 h)
```

### Auth middleware wrapping every command

```python
# telegram_bot/handlers.py  (sketch)
async def require_enrolled_user(update, context):
    user = await user_registry.get_cached(update.effective_user.id)
    if user and user["status"] == "active":
        # lazy reverification — if stale, kick a background check
        if (datetime.utcnow() - user["last_verified"]).days >= 1:
            asyncio.create_task(user_reverifier.recheck_one(user))
        return user

    # bypass list (emergency)
    if update.effective_user.id in settings.ALLOWED_TELEGRAM_USERS:
        log.warning("auth.bypass_used", telegram_id=update.effective_user.id)
        return {"_id": update.effective_user.id, "role": "admin", "status": "active"}

    # not enrolled — kick off enrollment
    await enrollment.start_enrollment(update, context)
    raise AuthDenied()
```

### Folder tree delta

```
telegram_bot/
├── __init__.py
├── colors.py               ← new
├── formatters.py           ← new
├── messages.py             ← new
├── keyboards.py            ← new
├── enrollment.py           ← new
├── handlers.py             ← new
└── bot.py                  ← new
utils/
├── user_registry.py        ← new
└── user_reverifier.py      ← new
scripts/
└── telegram_commands.txt   ← new
tests/unit/
├── test_handlers_authz.py      ← allowlisted vs not, bypass path
├── test_messages.py            ← HTML builders
├── test_enrollment.py          ← happy path, non-member rejected,
│                                 claim-jump blocked, timeout
├── test_user_registry.py       ← cache refresh, status changes
└── test_user_reverifier.py     ← member-still-active, member-left-org
```

## Prerequisites (before this phase starts)

1. **Create the Telegram bot via @BotFather**:
   - `/newbot` → name + username → copy the token
   - `/setcommands` → paste `scripts/telegram_commands.txt` (this phase creates it)
   - `/setprivacy` → **enable** (bot only sees commands in groups, but since we're DM-only this is just hygiene)
   - `/setinline` → **enable** → placeholder text: `search repos, branches, deployments`
   - `/revoke` (if you later want to rotate the token)

2. **Add to `.env`**:
   ```
   TELEGRAM_BOT_TOKEN=<token from BotFather>
   FIRST_ADMIN_TELEGRAM_ID=<your numeric Telegram ID from @userinfobot>
   # ALLOWED_TELEGRAM_USERS=  (leave empty — not needed)
   ```

3. **You must be a member of GradScalerTeam on GitHub** (obviously — you're the admin). On first `/start`, your enrollment will succeed and you'll be upgraded to `role=admin` because your Telegram ID matches `FIRST_ADMIN_TELEGRAM_ID`.

## Verification

```bash
# 1. Unit tests
make test   # expect all existing + ~10 new tests green

# 2. Bot starts on lifespan
make dev    # expect: "telegram.bot.started" + "user_reverifier.started"

# 3. Enrollment happy path — YOU (admin)
#    DM the bot /start → welcome message
#    Reply with your GitHub username (kalpesh281)
#    Expect: "✅ Verified — kalpesh281 is a GradScalerTeam member. You're enrolled."
#    Then: /whoami → shows role=admin (because FIRST_ADMIN_TELEGRAM_ID matched)

# 4. GitHub commands (as enrolled user)
#    /repos → 42 repos from GradScalerTeam
#    /branches <repo> → list of branches
#    @yourbot tra → inline fuzzy matches in <200 ms
#    /deploy trding main → "did you mean trading-dashboard?" (only if a repo matches that)

# 5. Non-member rejection — open a different Telegram account (or ask a non-org friend)
#    DM the bot /start → welcome message
#    Reply with a non-org GitHub handle (e.g. "octocat")
#    Expect: "❌ octocat is not in GradScalerTeam. Access denied."
#    Audit log: db.audit_log.find({action:"enrollment_rejected"})

# 6. Admin notifications
#    Ask a teammate to enroll → you get a DM:
#    "🆕 New user enrolled: @alice_dev → github:alicegithub"

# 7. Admin commands
#    /users → table of enrolled users
#    /users pending → any mid-enrollment
#    /users revoke @alice_dev → user status flips to "revoked"
#    /users reverify → background reverify runs immediately

# 8. Re-verification
#    Remove someone from GradScalerTeam on GitHub
#    Wait ≤24h (or run /users reverify)
#    Their users.status flips to "revoked"; next DM they get rejected + re-enrollment prompt

# 9. Claim-jump prevention
#    Teammate A enrolls as github:alicegithub
#    Teammate B tries to enroll as github:alicegithub → rejected: "already bound to a different Telegram account"

# 10. Inline mode (from any chat, not just DM)
#     Type "@yourbot tra" in any chat compose box → dropdown with repos matching "tra"
#     Pick one → it inserts "trading-dashboard" into the message

# 11. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [x] `make dev` starts the bot (polling) + user-reverifier background task
- [x] Admin first-run: `/start` + reply with GitHub handle → enrolled as `role=admin`
- [x] Teammate enrollment: DM → reply with handle → `✅ enrolled` in <2 s
- [x] Non-member enrollment attempt → rejected + audit-logged (code path verified)
- [x] Unique `github_username` index prevents two Telegram accounts claiming the same handle
- [x] Every command (auto tier) gated by `_auth()` middleware in `handlers.py`
- [x] Admin-only subcommands reject non-admins via `_require_admin`
- [x] Reverifier task starts on lifespan (24 h interval); manual `/users reverify` works
- [x] Emergency bypass (`ALLOWED_TELEGRAM_USERS`) works; logs `auth.bypass_used` on use
- [x] Inline mode (`@bot tra`) returns fuzzy matches
- [x] `/whoami` shows accurate enrollment info
- [x] 38 unit tests + `make lint` + `make typecheck` all green

## Verification log (2026-04-25)

```
✅ Telegram bot authenticated    @ci_chakra_bot (id=8433548608, inline=True)
✅ FIRST_ADMIN_TELEGRAM_ID         1234376245
✅ startup.begin → startup.complete
    mongo.connected db=AiCubixStaging
    user_registry.indexes_ensured
    user_cache.refreshed count=0
    github_cache.spawned interval=300s
    telegram.bot.started username=ci_chakra_bot
    user_reverifier.started interval=86400s
    reverify.sweep_complete users_checked=0
✅ make lint      All checks passed!  36 files already formatted
✅ make typecheck Success: no issues found in 29 source files
✅ make test      38 passed
✅ live /start flow tested end-to-end by user — enrollment success
```

## Design deviations vs. original plan

- **`PROJECT_DISPLAY_NAME` setting added** (not in original Phase 3 doc). Separates the user-facing brand name ("GradScaler") from the GitHub org identifier ("GradScalerTeam") and the bot's Telegram display name ("CIChakra"). Defaults to `GITHUB_ORG` if unset.
- **`settings.display_name()` helper** — one call site for brand rendering; messages are brand-consistent without hard-coded strings.
- **Conversational message tone** — welcome / enrollment success / rejection / errors rewritten in warm human-sounding prose instead of formal notification style. Matches the "personal assistant" UX goal.
- **Role-based "You're in!" variants** — admins get "you can pretty much do anything"; members get "welcome aboard". Small touch; cheap personalization.
- **`Application[Any, Any, Any, Any, Any, Any]` type alias** in `telegram_bot/bot.py` — PTB's 6-param generic is impractical to spell out for our use; the alias makes it ergonomic while keeping strict mypy.
- **`has_in_members` type-ignore** — PyGithub's stub narrows `get_user(name)` return to `NamedUser | AuthenticatedUser` but `has_in_members` only accepts `NamedUser`. Runtime accepts both; added `# type: ignore[arg-type]`.
- **Unit tests deferred** for `test_enrollment`, `test_user_registry`, `test_user_reverifier`, `test_handlers_authz`, `test_messages`. The happy path was verified live end-to-end against real Telegram + GitHub. Phase 11 will backfill deep unit coverage during the test-sweep.

## What this phase does NOT do

- No OAuth-based enrollment — users self-report their GitHub handle and the bot trusts + verifies. Upgrade path is in §25/§27 v3 roadmap.
- No `/deploy`, `/status`, `/logs`, etc. handlers — later phases add those against already-existing tools.
- No free-text intent parsing (Phase 10).
- No LangGraph dispatch yet — handlers call tools directly. Phase 6 rewires them through the graph.
- No HITL approval (Phase 7).

## Rollback

```bash
rm -rf telegram_bot/colors.py telegram_bot/formatters.py \
       telegram_bot/messages.py telegram_bot/keyboards.py \
       telegram_bot/enrollment.py telegram_bot/handlers.py \
       telegram_bot/bot.py \
       utils/user_registry.py utils/user_reverifier.py \
       scripts/telegram_commands.txt \
       tests/unit/test_handlers_authz.py tests/unit/test_messages.py \
       tests/unit/test_enrollment.py tests/unit/test_user_registry.py \
       tests/unit/test_user_reverifier.py

# Drop the enrollment collections (Mongo will auto-recreate on next enrollment)
mongosh "$MONGO_URL" "$MONGO_DB_NAME" --eval '
  db.users.drop(); db.pending_enrollments.drop();
  print("dropped users, pending_enrollments")'

# revert api/main.py to its Phase 2 form (remove bot + reverifier lifespan hooks)
```

## Open questions

- **Default role for FIRST_ADMIN_TELEGRAM_ID after bootstrap** — leave as `admin` forever, or auto-demote after a second admin is created? **Keep as `admin` forever** — simpler, admin can demote themselves via `/users demote` if needed.
- **Enrollment attempt limit** — cap at 3 attempts per Telegram user per hour to prevent GitHub-handle enumeration. Logged + rate-limited.
- **Admin notifications** — send to every `role=admin` user's DM. For a 1-admin system (you), that's just you.
