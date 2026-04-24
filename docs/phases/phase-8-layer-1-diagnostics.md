# Phase 8 — Layer 1 Diagnostics (0 LLM)

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 5 (need a running container to diagnose) |
| **Blocks** | Phase 9 (scraper shares the rule engine), Phase 10 (`/explain` consumes Layer 1 output) |
| **Spec references** | `docs/PROJECT_V2.md` §9.1 (Layer 1 code), §11.2 (`/report` UI), §11.3 (`/logs` UI), §16.2 (<1 s target) |

---

## Objective

Implement the offline, zero-token diagnostic layer. Parse `docker inspect`, regex + cluster logs, run a rule engine, and render `/logs`, `/inspect`, `/health`, `/report` as rich Telegram HTML messages in under 1 second.

## Design choices

| Choice | Why |
|---|---|
| **Pure Python, no external deps** | §9.1 — must work offline and when OpenAI is down. |
| **Regex + `Counter` for clustering** | §9.1 — simple, fast, deterministic. No ML overhead. |
| **`_normalize()` strips timestamps / IPs / hex IDs** | §9.1 — so "Mongo timeout" lines cluster regardless of variable tail. |
| **Rule engine is a flat list of `(predicate, message)` pairs** | §9.1 — easy to extend; every rule has a single output line. |
| **Exit-code dictionary hardcoded** | §9.1 — there are ~8 codes that matter, not worth making configurable. |
| **`/report` returns HTML + inline keyboard (Explain/Logs/Restart/Rollback)** | §11.2 — user can drill from diagnosis to action in one tap. |
| **`/logs` supports level filter + time window + pagination** | §11.3 — user can navigate without re-running the command. |
| **Callbacks edit the same message in place** | §11.3 — filter/time/page all mutate the existing message. |
| **Layer 1 runs against LIVE `docker logs` (not Mongo yet)** | Phase 9 adds the persistent scraper + `/history`; Layer 1 stays real-time for diagnostics. |

## Deliverables

### Files created

- `utils/docker_diagnostics.py` — `inspect_diagnose(inspect_data)`, `EXIT_CODE_MEANINGS`.
- `utils/log_analyzer.py` — `analyze_logs(text)`, `_normalize(line)`, `ERROR_RE`, `WARN_RE`, cluster helpers.
- `utils/report_builder.py` — `diagnose(inspect, logs)` (rule engine), `build_report(inspect, logs, name)` returns structured dict for the message builder.
- `tools/diagnose_tools.py` — `/logs`, `/inspect`, `/health`, `/report` all `@tool(tier="auto")`.
- `telegram_bot/messages.py` — extended with `build_logs_message`, `build_inspect_message`, `build_health_message`, `build_report_message` (§11.2 + §11.3 layouts).
- `telegram_bot/handlers.py` — callback handlers for `logs:{name}:f:<level>`, `logs:{name}:w:<window>`, `logs:{name}:p:<page>`.
- `tests/unit/test_docker_diagnostics.py` — exit codes, OOM, restart, health statuses.
- `tests/unit/test_log_analyzer.py` — regex matches, clustering, normalization.
- `tests/unit/test_report_builder.py` — rule engine coverage.

### Folder tree delta

```
utils/
├── docker_diagnostics.py   ← new
├── log_analyzer.py         ← new
└── report_builder.py       ← new
tools/
└── diagnose_tools.py       ← new
tests/unit/
├── test_docker_diagnostics.py
├── test_log_analyzer.py
└── test_report_builder.py
```

## Verification

```bash
# 1. Unit tests
make test

# 2. Deploy a test container that emits errors (e.g. connects to a non-existent Mongo)
# Let it run for 30 s.

# 3. /report <name>
# expect: HTML message in <1 s with sections: Health snapshot, Recent issues, Suggested actions
# expect: footer reads "Layer 1 · <N> ms · 0 tokens"
# Verify token metric:
curl -s http://localhost:8100/metrics | grep llm_tokens_total
# expect: no change after running /report

# 4. /logs <name>
# expect: 30 lines max; level filter buttons work; pagination works (⏮ ◀ ▶ ⏭)
# expect: "Patterns" block with top 3 clusters

# 5. /health <name>
# expect: one-liner with uptime, restart count, health status

# 6. /inspect <name>
# expect: concise HTML of the §9.1 parsed fields (not raw JSON dump)

# 7. Rule engine detects synthetic failures
# Kill mongo while container is running; /report <name>
# expect: "🟡 MongoDB timeouts detected — check mongo container" in the output

# 8. Restart-loop detection
# Start a container that crashes on boot (e.g. `image: alpine`, `cmd: exit 1`)
# Wait for 6+ restarts, then /report
# expect: "🔴 Restart loop (6 restarts)"

# 9. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [ ] `/report` returns in <1 s with 0 LLM tokens used (`llm_tokens_total` unchanged)
- [ ] `/logs` pagination, level filter, time window all work via callback edits
- [ ] Rule engine detects OOM, restart loop, mongo timeouts, high error rate, tracebacks
- [ ] Normalisation clusters related error lines into a single pattern
- [ ] Exit-code lookup translates codes 0, 1, 125, 126, 127, 137, 139, 143
- [ ] `make lint` + `make typecheck` + unit tests clean

## What this phase does NOT do

- No `/history` browsable timeline (Phase 9)
- No persistent log ingestion (Phase 9)
- No LLM hypothesis (`/explain` lands in Phase 10)

## Rollback

```bash
rm -rf utils/docker_diagnostics.py utils/log_analyzer.py utils/report_builder.py \
       tools/diagnose_tools.py \
       tests/unit/test_docker_diagnostics.py tests/unit/test_log_analyzer.py \
       tests/unit/test_report_builder.py
# revert telegram_bot/messages.py (remove build_logs/inspect/health/report)
# revert telegram_bot/handlers.py (remove logs: callback handlers)
```
