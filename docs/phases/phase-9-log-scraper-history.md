# Phase 9 — Persistent Log Scraper + `/history`

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 8 (shares the rule engine) |
| **Blocks** | Phase 10 (`/explain` can optionally consume diagnostic_events) |
| **Spec references** | `docs/PROJECT_V2.md` §9.3 (persistent ingestion), §11.8 (`/history` UI), §20 (TTL-indexed collections), §13 (`ENABLE_LOG_ALERTS`) |

---

## Objective

Each running deployment gets a 60-second background log scraper that flushes lines into `container_logs` (TTL 7 d), runs the rule engine on the delta to produce `diagnostic_events` (TTL 30 d), and Telegram-alerts on error-severity events (rate-limited to 1/min/deployment). Expose the event stream as a browsable `/history` timeline.

## Design choices

| Choice | Why |
|---|---|
| **One `asyncio.Task` per running deployment** | §9.3 — simple ownership model. Task is spawned on deploy, cancelled on stop/delete. |
| **Poll cadence: 60 s (`POLL_INTERVAL`)** | §9.3 OD-L1 — balances freshness vs. load. |
| **`since=last_flush_ts` + `timestamps=True`** | Never re-ingest lines. Idempotent. |
| **Rule engine runs on the delta only, not the full buffer** | Avoids re-alerting on the same mongo-timeout cluster every 60 s. |
| **Alert rate limit: 1/min/deployment in-memory** | §9.3 — a 60 s "silence window" after each alert per deployment. |
| **`ENABLE_LOG_ALERTS` flag gates Telegram alerts only** | §13 — scraping + event creation still happens; only the alert message is suppressed. |
| **`/history` reads from `diagnostic_events` DESC by `triggered_at`** | §11.8 — cheapest browse; context logs expand on tap. |
| **Context logs stored inline on the event (20 lines)** | §11.8 — no extra query needed on tap. |
| **Scraper lifecycle hooked into the `deployments` write from Phase 5** | On successful deploy, `spawn_scraper(deployment_id)`; on `stop`/`delete`, `cancel_scraper(deployment_id)`. |

## Deliverables

### Files created

- `utils/log_scraper.py` — `LogScraper` class per §9.3, `SCRAPERS: dict[str, asyncio.Task]`, `spawn_scraper()`, `cancel_scraper()`, `cancel_all()`.
- `utils/event_detector.py` — `detect_events(delta_lines, deployment)` wrapping the Phase 8 rule engine, returning `diagnostic_events`-shaped dicts.
- `utils/alert_dispatcher.py` — Telegram alert with rate-limit + `ENABLE_LOG_ALERTS` gate.
- `tools/history_tools.py` — `/history` `@tool(tier="auto")`.
- `telegram_bot/messages.py` — extended: `build_history_message`, `build_history_event_detail`.
- `telegram_bot/handlers.py` — callback handlers `hist:{name}:f:<severity>`, `hist:{name}:w:<window>`, `hist:{name}:open:<event_id>`.
- `api/main.py` lifespan — on shutdown, `cancel_all()` for graceful drain.
- `tests/unit/test_log_scraper.py` — delta ingest, no re-insertion, TTL sanity.
- `tests/unit/test_event_detector.py` — shares rule-engine fixtures with Phase 8.
- `tests/unit/test_alert_dispatcher.py` — rate-limit + flag-off behavior.

### Folder tree delta

```
utils/
├── log_scraper.py        ← new
├── event_detector.py     ← new
└── alert_dispatcher.py   ← new
tools/
└── history_tools.py      ← new
tests/unit/
├── test_log_scraper.py
├── test_event_detector.py
└── test_alert_dispatcher.py
```

## Verification

```bash
# 1. Unit tests
make test

# 2. Deploy a test container that emits error lines on a timer
# Wait 3 minutes.

# 3. container_logs populated
mongosh "$MONGO_URL" devops_agent --eval '
  db.container_logs.find({deployment: "<name>"}).count()'
# expect: >= 20 lines (3 flushes × some error volume)

# 4. diagnostic_events populated
mongosh ... --eval '
  db.diagnostic_events.find({deployment: "<name>"}).pretty()'
# expect: at least one event with severity, rule, message, context_logs

# 5. TTL indexes exist
mongosh ... --eval '
  db.container_logs.getIndexes().filter(i => i.expireAfterSeconds);
  db.diagnostic_events.getIndexes().filter(i => i.expireAfterSeconds);'
# expect: 604800 (7 d) and 2592000 (30 d) respectively

# 6. /history <name>
# expect: timeline with severity icons; tapping an event expands to 20-line context
# expect: severity filter (errors-only / all) works; time window (24h / 7d / 30d) works

# 7. Alert fires once per minute
# Trigger a burst of errors; check Telegram — should get 1 alert, not 10.

# 8. ENABLE_LOG_ALERTS=false → no alerts, events still written
# Flip flag, restart agent, re-trigger burst.
mongosh ... --eval 'db.diagnostic_events.find({alerted: false}).count()'
# expect: > 0

# 9. Lifecycle: /stop <name> cancels the scraper
# Telegram: /stop <name>
# Observe structlog: "scraper.cancelled" line

# 10. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [ ] Scraper writes `container_logs` every 60 s for every running deployment
- [ ] Delta-only ingestion — no duplicates across runs
- [ ] Rule engine populates `diagnostic_events` on matches
- [ ] TTL indexes honored: `container_logs` 7 d, `diagnostic_events` 30 d
- [ ] `/history` timeline browsable with severity/time filters and event expansion
- [ ] Alert rate-limited to 1/min/deployment
- [ ] `ENABLE_LOG_ALERTS=false` suppresses alerts but keeps event ingestion
- [ ] `/stop` / `/delete-deployment` cancels the scraper task cleanly
- [ ] `make lint` + `make typecheck` + unit tests clean

## What this phase does NOT do

- No LLM-side alerting (`/explain` alert integration is a v3 idea)
- No backfill for pre-Phase-9 containers — only containers deployed AFTER the phase lands get a scraper
- No disk-based archive (§25 — v3 roadmap item)

## Rollback

```bash
rm -rf utils/log_scraper.py utils/event_detector.py utils/alert_dispatcher.py \
       tools/history_tools.py \
       tests/unit/test_log_scraper.py tests/unit/test_event_detector.py \
       tests/unit/test_alert_dispatcher.py
# revert api/main.py (remove cancel_all() call on shutdown)
# revert telegram_bot/messages.py + handlers.py (remove history builders + hist: callbacks)
# revert tools/docker_tools.py if it was changed to spawn scrapers on deploy
```
