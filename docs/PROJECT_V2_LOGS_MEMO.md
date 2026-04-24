# PROJECT_V2 — Persistent Logs + Readable Format + Typed Confirm Memo

**Purpose:** Plan (not execution). Four feature additions to `docs/PROJECT_V2.md`.

**How to use:** Each item has an ID (`P-01` …). Reply with `approve all`, `approve P-01..P-10`, per-item decisions, etc. I apply after your reply.

---

## 🚦 Status overview — DONE ✅

Total items: **17**
Applied: **13** · Skipped (by your decision): **4** · Pending: **0**

| ID | Area | Title | Status |
|---|---|---|---|
| **P-01** | NEW-1 Typed confirm | §7.1 graph — `request_typed_confirmation` node | 🟢 **APPLIED** |
| **P-02** | NEW-1 Typed confirm | §7.2 State — typed-confirm fields | 🟢 **APPLIED** |
| **P-03** | NEW-1 Typed confirm | §14.1 approval tier — updated behavior | 🟢 **APPLIED** |
| **P-04** | NEW-1 Typed confirm | §11.9 subsection — typed-confirm UI | 🟢 **APPLIED** |
| **P-05** | NEW-1 Typed confirm | §24 verification items | ⚪ **SKIPPED** |
| **P-06** | NEW-2 Persistent logs | §9.3 subsection — log scraper architecture | 🟢 **APPLIED** |
| **P-07** | NEW-2 Persistent logs | §13 `ENABLE_LOG_ALERTS` toggle | 🟢 **APPLIED** |
| **P-08** | NEW-2 Persistent logs | §15 observability line | ⚪ **SKIPPED** |
| **P-09** | NEW-2 Persistent logs | §17 folder — scraper + event_detector | ⚪ **SKIPPED** |
| **P-10** | NEW-2 Persistent logs | §20 — `container_logs`, `diagnostic_events` | 🟢 **APPLIED** |
| **P-11** | NEW-3 /history | §8 Diagnostics — `/history` row | 🟢 **APPLIED** |
| **P-12** | NEW-3 /history | §11.8 subsection — `/history` UI | 🟢 **APPLIED** |
| **P-13** | NEW-3 /history | §8 identifier resolution note | ⚪ **SKIPPED** |
| **P-14** | NEW-4 Readable format | §11.2 rewrite `build_report_message` | 🟢 **APPLIED** |
| **P-15** | NEW-4 Readable format | §11.3 rewrite `/logs` + filter keyboard | 🟢 **APPLIED** |
| **P-16** | NEW-4 Readable format | §11.8 history readable style | 🟢 **APPLIED** (inline in P-12) |
| **P-17** | NEW-4 Readable format | §11.9 typed-confirm readable style | 🟢 **APPLIED** (inline in P-04) |

---

## Open decisions — ALL DECIDED ✅

| ID | Decision | Final value |
|---|---|---|
| **OD-L1** | Log scraper polling interval | **60s** (revised from 30s — small-startup friendly) |
| **OD-L2** | `container_logs` TTL | **7d** |
| **OD-L3** | `diagnostic_events` TTL | **30d** |
| **OD-L4** | Auto-alert on error events | **above threshold** (error+, rate-limited 1/min per deployment) |
| **OD-L5** | Typed-confirm keyword format | **`ACTION NAME`** (full form, e.g. `STOP trading-dashboard`) |
| **OD-L6** | Typed-confirm timeout | **60s** |

Bonus: `/logs` and `/report` may bypass the 60s cache with a live `docker logs` call when freshness matters.

---

## Change list

### NEW-1 · Typed-keyword confirmation (destructive ops)

---

#### P-01 ⏳ PENDING · §7.1 graph diagram — add `request_typed_confirmation` node
**Current:** `classify_tier → (approval interrupt | pre_deploy_check) → execute_tool`
**Proposed:** `classify_tier → (approval interrupt → typed_confirm_interrupt | pre_deploy_check) → execute_tool`
**Why:** Approval now requires both button tap AND typed confirmation before execution.
**Effort:** moderate (diagram edit + one new node file)
**Blocked on:** OD-L5, OD-L6

---

#### P-02 ⏳ PENDING · §7.2 State — add typed-confirm fields
**Proposed:** Add to `AgentState`:
```python
typed_confirm_expected: Optional[str]   # e.g. "STOP trading-dashboard"
typed_confirm_received: Optional[str]   # None until user replies
typed_confirm_deadline: Optional[datetime]
```
**Effort:** trivial

---

#### P-03 ⏳ PENDING · §14.1 approval tier — update behavior
**Current:** `HITL interrupt → Telegram button → resume`
**Proposed:** `HITL interrupt → Telegram button → typed-keyword confirm (60s timeout) → resume`
**Effort:** trivial

---

#### P-04 ⏳ PENDING · §11 new subsection 11.9 — typed-keyword confirmation UI
**Proposed:** New subsection showing the prompt + code sketch:
```
🔴 Stop request — trading-dashboard

This will stop the container on physical-main.
Active connections: 3 · Uptime: 2h 14m

To confirm, type exactly:
STOP trading-dashboard

(case-sensitive · 60s to respond)

[❌ Cancel]
```
With matching handler code (regex on next message, timeout via `asyncio.wait_for`).
**Effort:** moderate (new subsection, ~40 lines)

---

#### P-05 ⏳ PENDING · §24 verification — new items
**Proposed:** Add two items:
- Typed confirm — happy path: `/stop test-dep` → button tap → prompt → type `STOP test-dep` → container stops.
- Typed confirm — abort path: same flow, type wrong text → operation aborts, audit_log records `result: "aborted_typed_confirm_mismatch"`.
**Effort:** trivial

---

### NEW-2 · Persistent log ingestion

---

#### P-06 ⏳ PENDING · §9 new subsection 9.3 — Persistent Log Ingestion
**Proposed:** New subsection with:
- Architecture: per-deployment background task, 30s polling, incremental `docker logs --since=<last_flush_ts>`
- Storage flow: raw lines → `container_logs` + rule engine on delta → `diagnostic_events` on match
- Telegram alert on error-severity events (rate-limited per OD-L4)
- Code sketch for `utils/log_scraper.py`
**Effort:** large (~80 lines + code block)
**Blocked on:** OD-L1, OD-L2, OD-L3, OD-L4

---

#### P-07 ⏳ PENDING · §13 AI Toggles — new flag `ENABLE_LOG_ALERTS`
**Proposed:** Add to `Settings`:
```python
ENABLE_LOG_ALERTS: bool = True   # disable → scraper still runs, but no Telegram alerts
```
Note: scraper uses rule engine (heuristic, 0 tokens) — the flag only controls Telegram notifications, not the LLM.
**Effort:** trivial

---

#### P-08 ⏳ PENDING · §15 Observability — add scraper to the list
**Proposed:** Add bullet: "Background log scraper runs per running deployment at 30s cadence; flushes to Mongo; event-driven Telegram alerts on error-severity matches"
**Effort:** trivial

---

#### P-09 ⏳ PENDING · §17 folder structure — two new utils
**Proposed:** Add:
```
├── utils/
│   ├── log_scraper.py           # per-deployment polling + Mongo flush
│   └── event_detector.py        # rule engine over recent window
```
**Effort:** trivial

---

#### P-10 ⏳ PENDING · §20 data model — two new collections
**Proposed:** Add schemas:
```json
// container_logs  — TTL 7 days
{
  "_id": ObjectId,
  "deployment": "trading-dashboard",
  "target_server": "physical-main",
  "timestamp": "2026-04-24T12:34:56.123Z",
  "stream": "stdout" | "stderr",
  "line": "ERROR Mongo connection timeout",
  "level": "ERROR",        // INFO | WARN | ERROR | FATAL
  "cluster_id": "mongo_timeout_<hash>",
  "created_at": ISODate
}

// diagnostic_events  — TTL 30 days
{
  "_id": ObjectId,
  "deployment": "trading-dashboard",
  "triggered_at": "2026-04-24T12:35:00Z",
  "rule": "mongo_timeout_spike",
  "severity": "error",
  "message": "42 mongo timeouts in last 5 min",
  "context_logs": [/* 20 surrounding lines */],
  "alerted": true,
  "created_at": ISODate
}
```
Indexes: `container_logs` compound `(deployment, timestamp DESC)` + TTL on `created_at`; `diagnostic_events` compound `(deployment, triggered_at DESC)` + TTL on `created_at`.
**Effort:** trivial (schema block)

---

### NEW-3 · `/history` command

---

#### P-11 🟢 APPLIED · §8 Diagnostics table — `/history <name>` row
**Applied:** Added row `| /history <name> | inline mode · keyboard | Browsable diagnostic event timeline (§11.8) |` to the Diagnostics table.
**No further action needed.** Revertible if you change your mind.

---

#### P-12 ⏳ PENDING · §11 new subsection 11.8 — `/history` UI
**Proposed:** New subsection with:
```
📜 History — trading-dashboard
Last 24 hours · 7 events

🔴 12:35  Mongo timeout spike (42 in 5 min)
🟡 11:20  Memory spike (480/512 MB)
🔴 10:03  Container restart loop (3 restarts)
🟡 09:15  Slow response time (>2 s)
🔵 08:00  Deploy success (a3f21c9)
🟡 06:44  Cold start
🔵 00:00  Daily health summary

Tap an event → expand to 20 lines of context

[🔴 Errors only] [🟡 All incidents]
[⏱ 24h] [⏱ 7d] [⏱ 30d]
```
Plus code sketch for `build_history_message` reading from `diagnostic_events`.
**Effort:** moderate

---

#### P-13 ⏳ PENDING · §8 Identifier resolution — `/history` reuses the same resolution order
**Proposed:** One-line note confirming `/history <name>` uses the §8 resolution order (container name → repo → project → fuzzy).
**Effort:** trivial

---

### NEW-4 · Readable formatting

---

#### P-14 ⏳ PENDING · §11.2 rewrite `build_report_message` — structured sections
**Current:** single long message, inline field list.
**Proposed:**
```
🟡 trading-dashboard — Running with errors

📊 Health snapshot
• Target:  physical-main
• Uptime:  2h 14m · Restarts: 0
• Memory:  340/512 MB (66%)
• CPU:     12.3%
• Health:  passing (5/5)

⚠️ Recent issues (last 10 min)
• 🔴 42× MongoDB connection timeout
• 🟡  3× Unhandled rejection

💡 Suggested actions
1. /report mongo — check mongo health
2. /restart mongo — if mongo is unhealthy
3. /explain trading-dashboard — AI root-cause

Layer 1 · 623 ms · 0 tokens

[🤖 Explain with AI] [📜 Raw logs]
[🔄 Restart]        [↩ Rollback]
```
Code block rewrites `build_report_message` to emit this layout.
**Effort:** moderate

---

#### P-15 ⏳ PENDING · §11.3 rewrite `/logs` — readable line format + filter keyboard
**Current:** `<pre>` block of raw docker log lines.
**Proposed:**
```
📜 Logs — trading-dashboard
⏱ Last 5 min · 🔴 4 · 🟡 2 · 🔵 12 · 📊 18 lines

🔴 12:34:57  MongoDB connection timeout
🟡 12:34:58  Retrying mongo connection (2/5)
🔴 12:35:02  MongoDB connection timeout
🟡 12:35:03  Circuit breaker opened
🔵 12:35:05  Fallback to cache (3 items)
...

Patterns
▸ 4× MongoDB connection timeout
▸ 2× Retrying mongo
▸ 1× Circuit breaker opened

[🔴 Errors only] [🟡 Warn+] [🔵 All]
[⏱ 5m] [⏱ 1h] [⏱ 24h]
[⏮] [◀] 1/4 [▶] [⏭]
```
Reads from `container_logs` (P-06) instead of live `docker logs`. Filter keyboard drives re-query. Cluster summary from rule engine.
**Effort:** moderate

---

#### P-16 ⏳ PENDING · §11.8 `/history` adopts the same readable style
**Proposed:** `/history` uses the P-15 visual rules (emoji level · short timestamp · trimmed message) and the same filter-keyboard conventions.
**Effort:** trivial (follows from P-12)

---

#### P-17 ⏳ PENDING · §11.9 typed-confirm prompt adopts the same readable style
**Proposed:** P-04's prompt uses the same emoji + section conventions (🔴 title, body, explicit instruction, [❌ Cancel] keyboard).
**Effort:** trivial (follows from P-04)

---

## Summary

| Area | Items | Applied | Pending |
|---|---|---|---|
| NEW-1 Typed-keyword confirm | P-01..P-05 | 0 | 5 |
| NEW-2 Persistent log ingestion | P-06..P-10 | 0 | 5 |
| NEW-3 `/history` | P-11..P-13 | 1 | 2 |
| NEW-4 Readable formatting | P-14..P-17 | 0 | 4 |
| **Total** | **17** | **1** | **16** |

---

## Reply template

Please answer:

1. **OD-L1..OD-L6** — `agree ODs` or per-ID override
2. **Which P-\* items** — `approve all` · `approve all except P-13` · etc.

Shortest valid reply: **`agree ODs, approve all`** — and I apply the remaining 16 items in one pass.
