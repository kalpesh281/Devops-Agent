# PROJECT_V2 — Telegram Migration Memo

**Purpose:** Plan (not execution). Lists every change needed to move `docs/PROJECT_V2.md` from Discord to Telegram before any rewrite happens.

**Status:** `docs/PROJECT_V2.md`, `CLAUDE.md`, `README.md`, `.claude/agents/devops-agent-auditor.md` — all **untouched** until you approve items in this memo.

**How to use:** Each change has an ID (`M-01` …). Reply with `approve all`, `approve M-01..M-12 skip M-18`, or per-item edits. I rewrite the spec only after your reply.

---

## Open decisions (answer these first — they unblock several items)

| ID | Decision | Options | My recommendation |
|---|---|---|---|
| **OD-1** | Telegram library | `python-telegram-bot` v21+ · `aiogram` v3+ | **python-telegram-bot** — more mature, closer to the `discord.py` mental model you already have in the spec |
| **OD-2** | Entity selection UX (pick repo / branch / deployment name) | A) Inline mode only (`@bot tra…`)  ·  B) Inline keyboard only  ·  C) Hybrid | **C) Hybrid** — inline mode when user is typing a `/command`; inline keyboard (top-10 fuzzy matches) when user is in a conversational flow |
| **OD-3** | Keep Discord as an alternate channel or remove entirely? | A) Replace Discord (simpler)  ·  B) Abstract a `channel_adapter` layer with both | **A) Replace** — single-user bot, dual-channel is over-engineering |
| **OD-4** | Chat scope | A) DM only  ·  B) Private group allowed  ·  C) Both | **A) DM only** — single-user tool |
| **OD-5** | Command registration | A) `BotFather /setcommands` bootstrap + code handlers  ·  B) Code only | **A)** — users get a command menu in Telegram UI |
| **OD-6** | Status color semantics (today: Discord embed colors — green/yellow/red) | A) Emoji prefixes (🟢🟡🟠🔴) + bold text  ·  B) Drop color semantics | **A)** — same §11.1 palette, translated to emoji |

---

## Change list

### M-01 · §2 Goals — "Discord-first UX" wording
**Current:** "Discord-first UX — slash commands with fuzzy-matched autocomplete, buttons, embeds, paginated logs"
**Proposed:** "Telegram-first conversational UX — inline keyboards for selection, message-edit for streaming progress, inline mode for entity search"
**Effort:** trivial
**Blocked on:** OD-2

---

### M-02 · §3 Tech Stack — replace Discord client
**Current:** `Discord | discord.py 2.x | Slash commands + autocomplete + buttons + Embeds`
**Proposed:** `Telegram | python-telegram-bot v21+ | Commands + inline keyboards + callback queries + inline mode`
**Effort:** trivial
**Blocked on:** OD-1

---

### M-03 · §4 Architecture diagram — relabel Discord boxes
**Current:** ASCII block `Discord (you chat)` → `Discord bot discord.py`
**Proposed:** `Telegram (DM)` → `Telegram bot python-telegram-bot`; inner bullets change from `Slash cmds (autocomplete) / Buttons / Embeds / Paginators` to `Commands / Inline keyboards / Inline mode / HTML messages`
**Effort:** trivial

---

### M-04 · §7.2 AgentState — rename Discord-specific fields
**Current:** `discord_user_id: str`, `discord_channel_id: str`
**Proposed:** `platform_user_id: str`, `platform_chat_id: str` (+ optional `platform: Literal["telegram"] = "telegram"` for future-proofing)
**Why:** Not forcing `telegram_*` naming leaves the state model reusable.
**Effort:** trivial
**Blocked on:** OD-3 (if replacing Discord entirely, we could just use `telegram_*` for clarity — I prefer `platform_*`)

---

### M-05 · §8 Commands table — rework the "Autocomplete" column
**Current:** Every command row has an "Autocomplete" column listing which args have per-keystroke fuzzy completion
**Proposed:** Rename column to **"Selection UX"** — values become `keyboard` (inline keyboard of matches), `inline mode` (typed `@bot <query>` triggers inline results), or `free-text` (no picker, accepts raw). Command set itself is unchanged.
**Effort:** moderate (table-wide edit)
**Blocked on:** OD-2

---

### M-06 · §10 — replace "Slash Command Autocomplete + Fuzzy Resolution" entirely
**Current:** Entire §10 is Discord-specific: `autocomplete` decorators, `app_commands.Choice`, per-arg live completion
**Proposed:** New §10 titled **"Entity Selection — Inline Mode + Fuzzy Keyboard"**. Contents:
  1. The GitHub cache (from §10.2) stays identical — in-memory + 5-min background refresh via rapidfuzz
  2. **Inline mode handler**: `@bot tra` → bot returns top-25 matching repos as `InlineQueryResultArticle` items, user taps → inserted into their message
  3. **Keyboard fallback**: when bot replies to a conversational turn needing entity selection, it sends a top-10 keyboard (`InlineKeyboardMarkup`) with an "others…" button that paginates the rest
  4. Fuzzy resolver stays — on free-text commands like `/deploy trding-dashbord main`, if no exact match, bot replies with "did you mean `trading-dashboard`?" + confirm button
**Effort:** large (new content; ~Discord §10 length)
**Blocked on:** OD-2

---

### M-07 · §11 Discord UI Layer — full rewrite as "Telegram UI Layer"
The whole section must be rewritten. Breaking into sub-items so you can approve piece by piece:

| Sub-ID | Today (Discord) | Proposed (Telegram) |
|---|---|---|
| **M-07a** | §11.1 color palette `Colors.SUCCESS = 0x34C759` etc. (integer hex) | Keep class name `Colors`, values become emoji prefixes: `SUCCESS = "🟢"`, `WARNING = "🟡"`, `ORANGE = "🟠"`, `ERROR = "🔴"`, `INFO = "🔵"`, `AI = "🟣"`, `MUTED = "⚪"` |
| **M-07b** | §11.2 `build_report_embed` returns `discord.Embed` with fields, inline flags, color | `build_report_message` returns `(html_text, inline_keyboard)`. Uses HTML mode, line-formatted key/value pairs, emoji status prefix |
| **M-07c** | §11.3 `LogsPaginator(discord.ui.View)` with ⏮◀▶⏭ buttons | `LogsPaginator` class with `InlineKeyboardMarkup` + callback handlers; same page model, same buttons. Pattern is 1:1. |
| **M-07d** | §11.4 `/status` ASCII table via `tabulate` inside a code block | **Unchanged** — `tabulate` output works identically inside Telegram `<pre>` blocks |
| **M-07e** | §11.5 `ImageManagementView(discord.ui.View)` with `[Remove old] [Rollback]` buttons | `build_images_keyboard` returns `InlineKeyboardMarkup`; callback handlers wired to tool funcs |
| **M-07f** | §11.6 self-updating deploy message via `message.edit` | **Unchanged in pattern** — `context.bot.edit_message_text(chat_id, message_id, …)` is the Telegram equivalent |
| **M-07g** | §11.7 `/explain` purple AI Embed with token count footer | Same info, rendered as HTML message: title with 🟣, diagnostic stats line, footer line with token count + cost |

**Effort:** large
**Blocked on:** OD-1, OD-6

---

### M-08 · §12 Token Budget — reprice for conversational primary flow
**Current:** "Profile B — slash-first" table assumes 30 slash commands/day at 0 tokens each; free-text chat is rare (2/day)
**Proposed:** Rename to **"Conversational primary"**. Adjust the daily table — assume ~20 conversational messages/day at ~230 tokens (intent parse + reply formatting), 5 deploys with optional pre-check at ~550, 2 `/explain` at ~250. New daily total: **~7,700 tokens**, monthly **~230K**, cost **~$0.04–0.10/month** on `gpt-4o-mini`-class model.
**Why:** No more free "slash + autocomplete" shortcut — every conversational turn hits the LLM.
**Effort:** moderate
**Blocked on:** separate question below on model name

---

### M-09 · §13 AI Toggles — `ENABLE_FREE_TEXT_CHAT` becomes load-bearing
**Current:** "disable → slash-only mode" (a viable degraded mode)
**Proposed:** Note that with Telegram's conversational flow, disabling `ENABLE_FREE_TEXT_CHAT` reduces the bot to command-only operation. Still functional — commands work without LLM — but the "conversational" promise goes away. Keep the flag; clarify its impact.
**Effort:** trivial

---

### M-10 · §14.2 Allowlists — swap Discord user IDs → Telegram user IDs
**Current:** "Allowlist: Discord user IDs that may issue commands"
**Proposed:** "Allowlist: Telegram user IDs (integers from `message.from_user.id`)"
**Effort:** trivial

---

### M-11 · §16.2 Runtime timings — drop autocomplete row, add Telegram ones
**Current:** `Autocomplete: <50 ms per keystroke`
**Proposed:** Remove autocomplete row. Add: `Inline mode query: ~80–120 ms (cache hit)`, `Keyboard callback roundtrip: ~200–400 ms`
**Effort:** trivial

---

### M-12 · §17 Folder structure — rename `discord_bot/` to `telegram_bot/`
**Proposed mapping:**
```
discord_bot/bot.py       → telegram_bot/bot.py          (Application + dispatcher)
discord_bot/commands.py  → telegram_bot/handlers.py     (CommandHandler + MessageHandler + CallbackQueryHandler + InlineQueryHandler)
discord_bot/views.py     → telegram_bot/keyboards.py    (InlineKeyboardMarkup builders)
discord_bot/embeds.py    → telegram_bot/messages.py     (HTML message builders)
discord_bot/colors.py    → telegram_bot/colors.py       (emoji palette — renamed contents per M-07a)
discord_bot/formatters.py → telegram_bot/formatters.py  (unchanged — tabulate, uptime, size)
```
**Effort:** trivial (structural)
**Blocked on:** OD-1

---

### M-13 · §18 `pyproject.toml` — dependency swaps
**Current:** `"discord.py>=2.4.0"`
**Proposed:** `"python-telegram-bot>=21.0.0"` · keep `tabulate`, `rapidfuzz`, `rich` as-is · no other deps change
**Effort:** trivial

---

### M-14 · §20 Data model — audit_log actor prefix
**Current:** `"actor": "discord:kalpesh#0001"`
**Proposed:** `"actor": "telegram:kalpesh281"` (username without `@`; falls back to `telegram:<user_id>` if no username)
**Effort:** trivial

---

### M-15 · §22 Setup steps — replace Discord bot creation with BotFather flow
**Current:** "DISCORD_BOT_TOKEN" env var; implied discord.com/developers flow
**Proposed:** `TELEGRAM_BOT_TOKEN` env var; setup steps:
  1. DM `@BotFather` → `/newbot` → name + username → receive token
  2. `/setcommands` on BotFather — paste the command menu (script in `scripts/set_telegram_commands.sh`)
  3. `/setprivacy` → Disable (for group mode) or leave enabled for DM-only
  4. `/setinline` → enable inline mode + set placeholder text
  5. `ALLOWED_TELEGRAM_USERS=123456,789012` in `.env`
**Effort:** moderate
**Blocked on:** OD-4, OD-5

---

### M-16 · §23 Threat model — swap Discord references
**Current:** "Random Discord user runs commands" · "Discord channel compromised"
**Proposed:** "Random Telegram user runs commands" · "Telegram chat compromised"; add: "Telegram bot token leak → immediate /revoke via BotFather + rotate"
**Effort:** trivial

---

### M-17 · §24 Verification checklist — replace autocomplete tests
**Current:** Item 3 `/deploy repo:tra → dropdown shows trading-dashboard at top. Typo trding still matches.`
**Proposed:** Two items:
  - `@bot tra` in inline mode → top result is `trading-dashboard` within 200ms
  - `/deploy trding-dashbord main` → bot replies "did you mean `trading-dashboard`?" with confirm button
**Effort:** trivial

---

### M-18 · §25 Trade-offs — add one, keep the rest
**Add row:**
| **No per-argument autocomplete** | Telegram lacks Discord-style live completion | Mitigated by inline mode + fuzzy "did you mean?" · users learn inline mode within a day |
**Effort:** trivial

---

### M-19 · §26 Resume bullet — full rewrite
**Current:** Mentions Discord, slash commands, rapidfuzz-powered slash command autocomplete
**Proposed (one sentence change):** Replace "Discord" → "Telegram", "slash command autocomplete over a cached repo/branch list" → "inline mode entity search + fuzzy keyboard fallback over a cached repo/branch list", "rich Discord UI with color-coded Embeds, paginated logs" → "Telegram HTML messages with emoji-coded status, inline-keyboard paginated logs"
**Effort:** trivial

---

### M-20 · §27 v3 Roadmap — update UI line
**Current:** "Web dashboard (React) alongside Discord"
**Proposed:** "Web dashboard (React) alongside Telegram" + add roadmap item: "Telegram Mini App for richer in-chat UI (charts, tables)"
**Effort:** trivial

---

### M-21 · Out-of-scope-for-memo but needed later (Step 4)
These files reference Discord and will need catch-up edits after `PROJECT_V2.md` is rewritten — **not part of this memo's approval**, just listed so you know they're coming:
- `README.md` — "Discord-first UX" in opening line, tech stack table row, security bullet
- `CLAUDE.md` — "Discord button" in tier enforcement section, "Discord long operations" convention, "Color palette is centralized in `discord_bot/colors.py`"
- `.claude/agents/devops-agent-auditor.md` — persona says "Discord-controlled" + description example mentions "Discord button"

---

## One separate question for you

**Model name** — §3 and §12 both name `OpenAI GPT-5.4-nano`. I don't believe that's a real OpenAI model ID. Telegram migration is the right moment to pick a real one. Options:
- `gpt-4o-mini` — stable, cheap, widely available
- `gpt-4.1-nano` — newer, cheaper per token
- Leave as `GPT-5.4-nano` placeholder and decide later

This is separate from the Telegram change but blocks the §12 token-budget reprice in M-08.

---

## After you approve

1. I rewrite `docs/PROJECT_V2.md` in one clean pass applying only the items you approved.
2. I then do Step 4 (update `README.md` + `CLAUDE.md` + agent file).
3. You read through; we're done.

**Reply with:** your decisions on OD-1..OD-6, the model name question, and which `M-*` items to include.
