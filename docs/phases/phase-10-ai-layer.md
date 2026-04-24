# Phase 10 — AI Layer (Free-Text, Pre-Deploy, `/explain`)

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 6 (graph), Phase 8 (Layer 1 output consumed by `/explain`) |
| **Blocks** | Phase 11 (verification checklist includes AI-off mode) |
| **Spec references** | `docs/PROJECT_V2.md` §7.1 (graph), §9.2 (`/explain`), §12 (token budget), §13 (toggles), §16.1 (prompt caching) |

---

## Objective

Add the three opt-in AI features — **all flag-controlled**:

1. **Free-text intent parsing** (`ENABLE_FREE_TEXT_CHAT`, ~230 tok) — "deploy the trading dashboard" → `/deploy trading-dashboard main`
2. **Pre-deploy config review** (`ENABLE_PREDEPLOY_ANALYSIS`, ~550 tok) — Dockerfile + `deploy.config.yml` sanity pass
3. **`/explain <name>`** (`ENABLE_EXPLAIN_COMMAND`, ~250 tok) — Layer 1 report + LLM hypothesis

Setting all three to `false` must leave every core command working unchanged.

## Design choices

| Choice | Why |
|---|---|
| **Single `utils/llm.py` wrapper** | Token tracking, prompt caching, budget enforcement, retry logic all centralised. |
| **Prompt caching on the system prompt (≥1024 tokens)** | §16.1 — 50 % discount on input tokens once system prompt stabilises. |
| **Token budget enforced BEFORE the call** | §12.3 — `TOKEN_BUDGETS` caps input; longer inputs are truncated (with a warning in logs). |
| **`/explain` receives the Layer 1 structured summary, not raw logs** | §9.2 — ~150 input tokens vs. ~6000 for raw logs. |
| **Output metrics: `llm_tokens_total{feature=...}` counter + `llm_cost_usd_total` gauge** | §15 — observable spend; catches runaway prompts early. |
| **OpenAI model name is a config var (default `gpt-4o-mini`)** | Spec's `gpt-5.4-nano` is not a real OpenAI model. `gpt-4o-mini` is the closest stable equivalent: $0.15 in / $0.60 out per 1M. |
| **Free-text path adds a branch to the graph (`route_input → parse_intent → classify_tier`)** | §7.1 — grafts onto the Phase 6 skeleton without touching the command path. |
| **Pre-deploy check runs as an in-graph node just before `execute_tool` for `/deploy`** | §7.1 — warnings attached to `state.predeploy_warnings` and rendered in the deploy message. |
| **Every LLM feature short-circuits to Phase 6 behavior when its flag is off** | §13 — the whole point. |

## Deliverables

### Files created

- `utils/llm.py` — `LLMClient` wrapper, `count_tokens(text, model)`, `truncate_to_budget(text, budget)`, token + cost metric hooks.
- `agents/prompts.py` — canonical prompt strings for intent parsing, pre-deploy review, explain. Stable (≥1024 tok) to trigger prompt cache.
- `agents/nodes/parse_intent.py` — LLM-powered intent parser (only executes when `ENABLE_FREE_TEXT_CHAT=true` AND `input_mode=free_text`).
- `agents/nodes/pre_deploy_check.py` — runs when `tool_name == "deploy"` AND `ENABLE_PREDEPLOY_ANALYSIS=true`.
- `tools/explain_tool.py` — `/explain <name>` registered as `@tool(tier="auto")`, only enabled when `ENABLE_EXPLAIN_COMMAND=true`.
- `agents/graph.py` — extended: adds `parse_intent` branch and `pre_deploy_check` node.
- `agents/nodes/route_input.py` — extended: if text doesn't start with `/`, mode = `free_text`.
- `telegram_bot/messages.py` — extended with `build_explain_message` (§11.7 with token footer).
- `tests/unit/test_llm_client.py` — token counting, truncation, metric hooks with mocked OpenAI.
- `tests/unit/test_parse_intent.py` — happy paths + disambiguation.
- `tests/unit/test_predeploy_check.py` — warning generation.
- `tests/unit/test_flags_off_path.py` — with all `ENABLE_*=false`, all commands still work.

### Env / config this phase introduces

```
# .env
OPENAI_MODEL=gpt-4o-mini
ENABLE_FREE_TEXT_CHAT=true
ENABLE_PREDEPLOY_ANALYSIS=true
ENABLE_EXPLAIN_COMMAND=true
```

### Folder tree delta

```
utils/
└── llm.py                          ← new
agents/
├── prompts.py                      ← filled in (was empty stubs)
├── graph.py                        ← extended
└── nodes/
    ├── parse_intent.py             ← new
    ├── pre_deploy_check.py         ← new
    └── route_input.py              ← extended
tools/
└── explain_tool.py                 ← new
tests/unit/
├── test_llm_client.py
├── test_parse_intent.py
├── test_predeploy_check.py
└── test_flags_off_path.py
```

## Verification

```bash
# 1. Unit tests
make test

# 2. Free-text parse
# Telegram: "deploy the trading dashboard to physical"
# expect: parsed → /deploy <match> main → confirm keyboard if ambiguous

# 3. Pre-deploy warnings
# Push a test repo whose Dockerfile is rootful and has no .dockerignore
# /deploy <that-repo> main
# expect: deploy message includes "Warnings: no USER directive, no .dockerignore"
# expect: deploy still proceeds (warnings don't block)

# 4. /explain <name>
# expect: Layer 1 report is built (0 tok), then LLM hypothesis (~250 tok)
# expect: message footer: "GPT-4o-mini • 247 tokens • ~$0.00015"

# 5. Token metric increments
curl -s http://localhost:8100/metrics | grep llm_tokens_total
# expect: counter > 0 after /explain

# 6. Flag-off path
# Edit .env: ENABLE_FREE_TEXT_CHAT=false, ENABLE_PREDEPLOY_ANALYSIS=false, ENABLE_EXPLAIN_COMMAND=false
# Restart agent.
# Telegram: /repos              → works
# Telegram: /deploy <r> main    → works (no pre-check warnings)
# Telegram: "deploy trading"    → "⚠️ free-text chat disabled; use /deploy <repo> <branch>"
# Telegram: /explain <name>     → "❌ /explain is disabled in settings."

# 7. Token budget enforcement
# Manufacture a pre-deploy call with a >10 KB Dockerfile.
# expect: structlog line "llm.input_truncated" with `budget=2000`; LLM call still succeeds.

# 8. Prompt caching hit-rate
# Call /explain three times in a row on the same container.
# expect: OpenAI response metadata shows cached_tokens > 0 on calls 2 and 3

# 9. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [ ] Free-text "deploy the trading dashboard" parses and routes to `/deploy`
- [ ] Pre-deploy check produces actionable warnings (USER, .dockerignore, resource limits)
- [ ] `/explain` returns a 🟣 message with token + cost footer
- [ ] All three flags respected: setting `false` disables that feature but core commands still work
- [ ] Token budget enforcement truncates overlong inputs with a log warning
- [ ] Prompt cache hit rate >0 % on stable system prompts
- [ ] Daily spend estimate <$0.20 at the §12.2 usage levels
- [ ] `make lint` + `make typecheck` + unit tests clean

## What this phase does NOT do

- No multi-provider LLM (§25 v3 roadmap)
- No fine-tuning; zero-shot only
- No AI-driven image-cleanup suggestions or auto-scaling

## Rollback

```bash
rm -rf utils/llm.py \
       agents/nodes/parse_intent.py agents/nodes/pre_deploy_check.py \
       tools/explain_tool.py \
       tests/unit/test_llm_client.py tests/unit/test_parse_intent.py \
       tests/unit/test_predeploy_check.py tests/unit/test_flags_off_path.py
# revert agents/prompts.py to empty-stub form
# revert agents/graph.py (remove parse_intent + pre_deploy_check nodes)
# revert agents/nodes/route_input.py (always set mode=command)
# revert telegram_bot/messages.py (remove build_explain_message)
```

## Open questions

- **Default model** — `gpt-4o-mini` unless you say otherwise. Can be swapped via `OPENAI_MODEL` env var without code change.
