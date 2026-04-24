# Phase 6 — LangGraph Agent (Graph + Nodes, Command Path)

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 5 |
| **Blocks** | Phase 7 (HITL interrupts are graph features), Phase 10 (free-text node hooks into the graph) |
| **Spec references** | `docs/PROJECT_V2.md` §7 (agent), §7.1 (graph), §7.2 (state), §7.3 (registry), §7.4 (checkpointer), §14.1 (tier), §14.6 (audit log) |

---

## Objective

Route every Telegram command through a LangGraph state machine instead of calling tools directly. Introduces `AgentState`, Mongo-backed checkpointer, and the §7.1 graph with **command-path nodes only** (free-text and HITL come in Phases 7 and 10).

## Design choices

| Choice | Why |
|---|---|
| **Thin nodes, fat utilities** | Every node is a single function that reads `AgentState`, calls one or two utilities, writes back to state. Business logic lives in `utils/` and `tools/`, not in the graph. |
| **`MongoDBSaver` checkpointer** | §7.4 — reuses the existing `motor` client, 7-day TTL already set in Phase 1. |
| **Graph built once at app startup, cached module-level** | Cold-start of `StateGraph.compile()` is ~10 ms; caching is worth it. |
| **`audit_log` node is the graph's terminal node and runs even on error** | §7.1 — captures duration, result, and error_type every time. Side-effect isolation. |
| **`trace_id` propagates through state** | Bound into structlog context so every log line in a command invocation is filterable by trace id. |
| **Command path: `START → validate_auth → route_input → classify_tier → execute_tool → format_response → audit_log → END`** | Minimal spine from §7.1. Free-text branch and HITL branch added in later phases without re-wiring. |
| **Tool invocation via `REGISTRY[tool_name].func(**state.intent_args)`** | §7.3 — no hardcoded tool calls in the graph. |

## Deliverables

### Files created

- `agents/state.py` — `AgentState` TypedDict per §7.2 (without `pending_approval` / `typed_confirm_*` — those land in Phase 7).
- `agents/checkpointer.py` — `get_checkpointer()` returning a `MongoDBSaver` bound to the shared motor client.
- `agents/prompts.py` — empty stubs (prompts populated by Phase 10).
- `agents/guardrails.py` — `check_allowlist(user_id)`, `check_denylist(target)`, `assert_tool_exists(name)`.
- `agents/nodes/validate_auth.py` — rejects non-allowlisted users.
- `agents/nodes/route_input.py` — sets `input_mode = "command"` (free-text hook point for Phase 10).
- `agents/nodes/classify_tier.py` — `state.tool_tier = REGISTRY[state.tool_name].tier`.
- `agents/nodes/execute_tool.py` — dispatch via `REGISTRY`; on exception, write to `state.error` and short-circuit to `audit_log`.
- `agents/nodes/format_response.py` — maps tool result to Telegram HTML via existing `telegram_bot/messages.py` builders.
- `agents/nodes/audit_log.py` — writes a row per §14.6 to `audit_log` collection.
- `agents/nodes/error_handler.py` — formats user-facing error with trace_id.
- `agents/graph.py` — `build_graph()` + module-level `GRAPH` cache.
- `telegram_bot/handlers.py` — all command handlers now call `graph.ainvoke(state)` instead of invoking tools directly.
- `tests/unit/test_graph_command_path.py` — graph routes `/repos` through every node and writes an audit row.
- `tests/unit/test_guardrails.py`.

### Folder tree delta

```
agents/
├── __init__.py
├── state.py             ← new
├── checkpointer.py      ← new
├── prompts.py           ← new (stubs)
├── guardrails.py        ← new
├── graph.py             ← new
└── nodes/
    ├── __init__.py
    ├── validate_auth.py
    ├── route_input.py
    ├── classify_tier.py
    ├── execute_tool.py
    ├── format_response.py
    ├── audit_log.py
    └── error_handler.py
tests/unit/
├── test_graph_command_path.py
└── test_guardrails.py
```

## Verification

```bash
# 1. Unit tests
make test

# 2. Graph compiles at startup
make dev
# expect: "graph.compiled" structlog line with node count = 7

# 3. Run a command through the graph
# Telegram: /repos
# Behavior: identical output to Phase 3, BUT now:
#   - audit_log collection has a new row
#   - checkpoints collection has entries for this invocation
#   - structlog trace_id propagates across every log line of this run

# 4. Audit log content
mongosh "$MONGO_URL" devops_agent --eval '
  db.audit_log.find().sort({timestamp:-1}).limit(1).pretty()'
# expect: { actor: "telegram:<user>", action: "list_repos", tool_tier: "auto",
#           result: "success", duration_ms: <int>, trace_id: "<uuid>" }

# 5. Error path runs audit_log too
# Force failure: /branches <nonexistent-repo>
# expect: error message in Telegram; audit_log row with result="error"

# 6. Checkpoint resume works
# Start a /deploy; kill `make dev` mid-build; restart
# expect: graph continues from last completed node (visible in structlog)

# 7. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [ ] All commands go through `graph.ainvoke(state)` — no direct tool calls in handlers
- [ ] Audit log row written for every command (success AND error paths)
- [ ] Checkpoints persist to Mongo; 7-day TTL honored
- [ ] Non-allowlisted user: graph terminates at `validate_auth` with silent drop
- [ ] `trace_id` appears in every log line of a single invocation
- [ ] Graph compiles once at startup, not per-request
- [ ] `make lint` + `make typecheck` + unit tests clean

## What this phase does NOT do

- No free-text path — `route_input` always sets mode=command (Phase 10 adds parse_intent branch)
- No approval interrupt — approval-tier tools execute directly for now (Phase 7 adds the interrupt)
- No pre_deploy_check node — that's LLM-gated and lands in Phase 10

## Rollback

```bash
rm -rf agents/state.py agents/checkpointer.py agents/prompts.py \
       agents/guardrails.py agents/graph.py agents/nodes/ \
       tests/unit/test_graph_command_path.py tests/unit/test_guardrails.py
# revert telegram_bot/handlers.py to Phase 3 form (direct tool calls)
```
