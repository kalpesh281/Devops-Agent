# Phase 7 — Rollback + Destructive Ops (HITL + Typed-Keyword Confirm)

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 6 |
| **Blocks** | Phase 11 (verification checklist needs this) |
| **Spec references** | `docs/PROJECT_V2.md` §11.9 (typed-confirm), §14.1 (tiers), §14.2 (denylist), §5.5 (image lifecycle), §16.2 (rollback <10 s), §24 (verification) |

---

## Objective

Deliver the approval-tier path. `/stop`, `/rollback`, `/remove-images`, `/cleanup`, `/delete-deployment` open a LangGraph interrupt → Telegram button → typed-keyword confirm (60 s window) → resume. Denylist blocks agent/mongo/traefik/existing client containers. Rollback in <10 s.

## Design choices

| Choice | Why |
|---|---|
| **`LangGraph.interrupt()` + `Command(resume=...)` pattern** | §7.1 — the only way to pause a graph across process restarts. Checkpointer (§7.4) makes it durable. |
| **Typed-keyword confirm in full `ACTION NAME` form** | §11.9 — button tap alone isn't enough; mistype is logged as `aborted_typed_confirm_mismatch`. |
| **60 s timeout measured server-side** | §11.9 — `typed_confirm_deadline` in state; `asyncio.wait_for` enforces. Timeout → `aborted_typed_confirm_timeout`. |
| **Denylist enforced in `guardrails.check_denylist()` BEFORE the interrupt** | §14.2 — never even present the confirm button for denied targets. |
| **Rollback uses `deployments.previous_image`, not `image_history[1]`** | `previous_image` is the last known-good; `image_history` may have been manually reordered. Cheaper guarantee. |
| **`/images` shows `image_history` with "current / previous / old" badges** | §11.5 — keyboard row offers "Remove old" and "Rollback". |
| **Audit log records `aborted_typed_confirm_*` as a distinct `result` value** | §14.6 — so the audit query `{result: {$regex: "^aborted"}}` surfaces every failed confirm. |
| **Denylist loaded from `config/tool_tiers.yml` → not hardcoded** | Lets prod server expand denylist without code change (see `docs/deployment/post-dev-deployment.md` §5). |

## Deliverables

### Files created

- `tools/image_tools.py` — `rollback`, `list_images` (as `/images`), `remove_images`, `cleanup`, `delete_deployment` all registered `@tool(tier="approval")`.
- `agents/nodes/request_approval.py` — `interrupt` with Telegram button keyboard.
- `agents/nodes/request_typed_confirmation.py` — §11.9 implementation.
- `agents/state.py` — extended: `pending_approval`, `approved`, `typed_confirm_expected`, `typed_confirm_received`, `typed_confirm_deadline`.
- `agents/graph.py` — adds the approval branch per §7.1.
- `telegram_bot/handlers.py` — `handle_typed_confirm_reply` message handler, `handle_approval_callback` for button taps.
- `telegram_bot/messages.py` — `build_typed_confirm_prompt`, `build_approval_result`, `build_images_message`.
- `tests/unit/test_typed_confirm.py` — timeout, mismatch, success paths.
- `tests/unit/test_denylist_enforcement.py` — denylist blocks before interrupt.
- `tests/integration/test_rollback_flow.py` — deploy → deploy → rollback cycle.

### Commands this phase delivers (all tier=approval unless noted)

| Command | Tier | Behavior |
|---|---|---|
| `/stop <name>` | approval | button → `STOP <name>` confirm → stop |
| `/rollback <name>` | approval | button → `ROLLBACK <name>` confirm → swap to `previous_image` |
| `/remove-images <name>` | approval | button → `REMOVE-IMAGES <name>` confirm → delete all but current + previous |
| `/cleanup <server>` | approval | button → `CLEANUP <server>` confirm → manual cleanup pass |
| `/delete-deployment <name>` | approval | button → `DELETE-DEPLOYMENT <name>` confirm → stop + remove record |
| `/images <name>` | auto | list-only; the destructive buttons within it still go through approval flow |

### Folder tree delta

```
tools/
└── image_tools.py                    ← new
agents/
├── state.py                          ← extended
├── graph.py                          ← extended
└── nodes/
    ├── request_approval.py           ← new
    └── request_typed_confirmation.py ← new
tests/unit/
├── test_typed_confirm.py
└── test_denylist_enforcement.py
tests/integration/
└── test_rollback_flow.py
```

## Verification

```bash
# 1. Unit tests
make test

# 2. Denylist blocks
# Telegram: /stop mongo
# expect: "⛔ Denied — `mongo` is on the denylist." No button presented.

# 3. Happy-path stop
# Telegram: /stop <test-container>
# expect: approval card with button. Tap "approve" → typed-confirm prompt.
#         Reply "STOP <test-container>" exactly → container stops.

# 4. Mismatch aborts
# Telegram: /stop <test-container>
# Tap approve → reply "stop <lower-case-name>"
# expect: "❌ Aborted — confirmation didn't match." Container still running.
mongosh "$MONGO_URL" devops_agent --eval '
  db.audit_log.find({result: "aborted_typed_confirm_mismatch"}).count()'
# expect: 1

# 5. Timeout aborts
# /stop ... → tap approve → wait 61 s
# expect: "❌ Aborted — 60 s elapsed." 
mongosh ... --eval 'db.audit_log.find({result: "aborted_typed_confirm_timeout"}).count()'
# expect: >= 1

# 6. Rollback in <10 s
# Deploy twice (two SHAs), then:
# Telegram: /rollback <name> → approve → type ROLLBACK → should complete <10 s
# Inspect: current_image equals what was previous before the rollback.

# 7. Checkpoint resumes interrupt
# /stop ... → approve → kill agent BEFORE typing confirm.
# Restart agent. Type "STOP <name>" → container stops (graph resumed).

# 8. /images shows history
# /images <name> → see 5 tags, first marked "current", second "previous", rest "old"
# Tap "Remove old" → approval flow → only current + previous remain

# 9. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [ ] `/stop mongo` (or any denylisted name) is refused before any button is shown
- [ ] Happy-path stop, rollback, remove-images, cleanup, delete-deployment all work
- [ ] Mismatch typed-confirm logs `aborted_typed_confirm_mismatch`
- [ ] Timeout typed-confirm logs `aborted_typed_confirm_timeout`
- [ ] Rollback completes in <10 s end-to-end
- [ ] Checkpointer restores an interrupt across agent restart
- [ ] `/images` shows current / previous / old; "Remove old" keyboard routes through approval
- [ ] `make lint` + `make typecheck` + unit + integration tests clean

## What this phase does NOT do

- No production denylist (that's Phase 12's job — expand with existing client containers on the server)

## Rollback

```bash
rm -rf tools/image_tools.py \
       agents/nodes/request_approval.py agents/nodes/request_typed_confirmation.py \
       tests/unit/test_typed_confirm.py tests/unit/test_denylist_enforcement.py \
       tests/integration/test_rollback_flow.py
# revert agents/state.py and agents/graph.py to Phase 6 form
# revert telegram_bot/handlers.py (remove typed-confirm + approval handlers)
```
