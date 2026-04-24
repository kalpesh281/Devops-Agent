# Phase 12 — Physical Server Deployment

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 11 (needs the Docker image + compose file + docs) |
| **Blocks** | nothing — this is the project's shipping phase |
| **Spec references** | `docs/PROJECT_V2.md` §6 (dev → prod), §22 (setup steps), `docs/deployment/post-dev-deployment.md` (full runbook) |

---

## Objective

Move the agent from "works on my Mac" to "runs as a first-class service on `server@122.172.241.96`", alongside the existing 20 client containers — without breaking any of them.

## Design choices

| Choice | Why |
|---|---|
| **Run mode: systemd unit** | `docs/deployment/post-dev-deployment.md` §7 option C — survives reboots, gives journalctl out of the box. |
| **Port 8100 (not 8000)** | `voice-auth-backend` owns 8000 on that host — documented in the deployment doc. |
| **`connection: local` for `physical-main`** | §6 — single-line change from dev form. |
| **Denylist expanded** | `docs/deployment/post-dev-deployment.md` §5 — every existing container on the host added so `/stop` can never touch them by accident. |
| **No `physical.pem` on the server** | §6 — agent talks to local Docker daemon, no SSH loopback. |
| **Mongo: use the host's existing `mongodb://localhost:27017`** | Pre-dev server audit confirms it's already running; `devops_agent` DB is isolated. |
| **UFW-tighten 27017** | Pre-dev audit flagged it as globally open. Restrict to `127.0.0.1` + `172.17.0.0/16` before the bot token lives on this host. |
| **Daily mongodump cron + 30-day retention** | Only irreplaceable state is Mongo; the TTL indexes handle pruning. |
| **Heartbeat cron** | Cheapest possible liveness signal; no Prometheus server needed day one. |

## Deliverables

### Files / changes

- `/etc/systemd/system/devops-agent.service` — the unit from `docs/deployment/post-dev-deployment.md` §7 option C, adjusted for our paths.
- `/etc/cron.daily/devops-agent-backup` — `mongodump` with 30-day retention.
- `/etc/cron.d/devops-agent-heartbeat` — 5-minute `/health` check → syslog on fail.
- `config/tool_tiers.yml` — denylist expanded with the 20 existing containers (docs/deployment §5).
- `secrets/servers.yml` (on server only) — `physical-main: connection: local`, client EC2 entries appended per customer.
- `/devops_agent/pem/<project>.pem` files — one per client, `chmod 600`, owned by `server`.
- `.env` on server — Stage 1+2+3 values, `AGENT_PORT=8100`, `chmod 600`.

### No repo-side code changes

This phase is all configuration + deployment plumbing. The only repo-side change is updating `config/tool_tiers.yml` denylist — which happens in a PR.

## Prerequisites

- [ ] Phase 11 completed (image + compose available)
- [ ] UFW rule audit done (pre-dev checklist)
- [ ] All client PEMs SCP'd to `/devops_agent/pem/`
- [ ] Telegram bot verified working on Mac first
- [ ] `.env` values for prod drafted locally (especially `TELEGRAM_BOT_TOKEN` — consider a separate prod bot token)

## Verification

Follow `docs/deployment/post-dev-deployment.md` §8 end-to-end. Additionally:

```bash
# 1. Service active
ssh server@122.172.241.96 "systemctl is-active devops-agent"
# expect: active

# 2. /health reachable on 8100
ssh server@122.172.241.96 "curl -s http://localhost:8100/health"
# expect: {"status":"ok","mongo":"connected",...}

# 3. Metrics scraped
ssh server@122.172.241.96 "curl -s http://localhost:8100/metrics | head -5"

# 4. UFW tight
ssh server@122.172.241.96 "sudo ufw status | grep 27017"
# expect: only 127.0.0.1 + 172.17.0.0/16 rules

# 5. Telegram smoke tests
# DM the prod bot:
# /repos          → <200 ms
# /servers        → shows physical-main + any client EC2s
# /status         → the existing 20 containers DO NOT appear (they are not our deployments)

# 6. Denylist enforcement
# /stop voice-auth-backend
# expect: "Denied — denylisted"

# 7. Backup runs
ssh server@122.172.241.96 "sudo /etc/cron.daily/devops-agent-backup && ls -la /var/backups/devops_agent/"
# expect: today's gzipped dump present

# 8. Heartbeat cron installed
ssh server@122.172.241.96 "cat /etc/cron.d/devops-agent-heartbeat"

# 9. Restart survives reboot
ssh server@122.172.241.96 "sudo reboot"
# Wait ~1 min
ssh server@122.172.241.96 "systemctl is-active devops-agent"
# expect: active

# 10. Roll-forward update works
# Push a change to GitHub → on server: git pull → systemctl restart → /health still green
```

## Acceptance criteria

- [ ] `devops-agent.service` is `active (running)` and `enabled`
- [ ] `/health` green on port 8100 locally on the server
- [ ] Bot responds on Telegram within 1 s of a command
- [ ] Existing 20 client containers still running, untouched
- [ ] Denylist blocks every existing container name from destructive ops
- [ ] Daily backup cron executed at least once and retained ≤30 days
- [ ] 5-minute heartbeat cron installed and running
- [ ] UFW 27017 rule tightened
- [ ] Reboot survived without manual intervention
- [ ] Rollback procedure (docs/deployment/post-dev-deployment.md §12) validated against a known-good SHA

## What this phase does NOT do

- No HA / failover — single-host by design (§25 v3)
- No Vault integration for secrets — `.env` + PEM folder is the v2 model (§25)
- No web dashboard — Telegram-only (§25)

## Rollback

If the new install misbehaves:

```bash
# Immediate
ssh server@122.172.241.96 "sudo systemctl stop devops-agent"
# Existing 20 client containers keep running — agent is just a sidecar.

# Code rollback to last good SHA (per post-dev §12)
ssh server@122.172.241.96
cd ~/devops-agent
git log --oneline -10
git checkout <last-good-sha>
sudo systemctl restart devops-agent
```

## Post-phase

With this merged, the project is in its v2 steady state. v3 roadmap items from §27 (web dashboard, webhook refresh, Vault, auto-scaling) become backlog candidates.
