# Post-Development — Physical Server Deployment

**Server:** `server@122.172.241.96`
**Assumes:** development is finished on your Mac and the local terminal + Telegram tests pass. This document describes the one-time move from "works on my Mac" to "runs on the server alongside 20 client containers."

> Read `pre-dev-server-setup.md` first. It confirms the base dependencies are in place and flags the port / disk / deny-list issues you must respect.

---

## 0. Before you start

Verify these are true:

- [ ] Agent code is in a git remote you can clone from the server (GitHub)
- [ ] `.env` on your Mac works — `make dev` on your Mac connected to this server's Docker daemon successfully deployed a test container and rolled it back
- [ ] Telegram bot is created via @BotFather and the token is in your local `.env`
- [ ] BotFather `/setcommands`, `/setprivacy enable`, `/setinline enable` all done
- [ ] MongoDB is reachable at `mongodb://localhost:27017` from the server (host-level mongo is already running there per the pre-dev audit)
- [ ] You know the deploy port you picked (**NOT 8000** — `voice-auth-backend` owns that)

If any of those is false, go fix it on your Mac first. The server is the last step, not the debugging arena.

> **Security note:** the physical server's host MongoDB (`mongod`, used by `gradscaler-next-container`) was observed listening on `0.0.0.0:27017` with a ufw rule `27017/tcp ALLOW Anywhere`. This is unrelated to the DevOps agent (agent uses its own hosted Mongo), but it's a long-standing security gap. If you haven't already tightened it, limit 27017 to `127.0.0.1` + `172.17.0.0/16` before the agent's Telegram bot token lives on the same host:
> ```bash
> sudo ufw allow from 127.0.0.1 to any port 27017
> sudo ufw allow from 172.17.0.0/16 to any port 27017
> sudo ufw delete allow 27017/tcp
> sudo ufw reload
> ```

---

## 1. Ship the PEM keys

All SSH keys for client servers live in one folder on this host, outside the repo.

```bash
# on the server, as `server` user (already done in pre-dev checklist)
[ -d /devops_agent/pem ] || { sudo mkdir -p /devops_agent/pem && sudo chown server:server /devops_agent/pem && chmod 700 /devops_agent/pem; }
```

From your Mac, SCP each client PEM to it:

```bash
# for every project/client you deploy on behalf of
scp ./acme.pem        server@122.172.241.96:/devops_agent/pem/acme.pem
scp ./trading-co.pem  server@122.172.241.96:/devops_agent/pem/trading-co.pem
# … one per client
```

Lock them down on the server:

```bash
ssh server@122.172.241.96 "chmod 600 /devops_agent/pem/*.pem && ls -la /devops_agent/pem"
```

⚠️ **Do NOT copy your Mac's key-for-this-server** (`physical.pem`) to the server itself. Once the agent runs on this host, it talks to the local Docker daemon directly — no SSH loopback needed. The agent's `servers.yml` will set `connection: local` for `physical-main`.

---

## 2. Clone the agent code

```bash
ssh server@122.172.241.96
cd ~
git clone <your-github-url> devops-agent
cd devops-agent
```

The spec §17 folder structure will appear after `make install` populates dependencies.

---

## 3. Configure `.env` on the server

```bash
cp .env.example .env
nano .env   # fill real values
chmod 600 .env
```

### Values that differ from your Mac `.env`

| Var | On Mac | On server | Why |
|---|---|---|---|
| `MONGO_URL` | `mongodb://localhost:27017` | `mongodb://localhost:27017` | Same — host-level mongo on the server works |
| `MONGO_DB_NAME` | `devops_agent` | `devops_agent` | Isolated DB |
| `AGENT_PORT` | `8100` | `8100` | Unified everywhere — `voice-auth-backend` owns 8000 on this host, so 8100 is used on Mac dev too |
| `TELEGRAM_BOT_TOKEN` | your Mac test bot | same token (or a separate prod bot) | your call |
| `ALLOWED_TELEGRAM_USERS` | your TG ID | same | |
| `PEM_DIR` | `/devops_agent/pem` | `/devops_agent/pem` | Same convention |

Set `AGENT_PORT=8100` in `.env` and use it in the Makefile / docker-compose overrides below.

---

## 4. Configure `secrets/servers.yml`

```bash
mkdir -p secrets
cp config/servers.example.yml secrets/servers.yml
nano secrets/servers.yml
chmod 600 secrets/servers.yml
```

**Critical change for the server-side deploy:** the `physical-main` entry must switch from `ssh` (Mac → server) to `local` (agent → local Docker daemon).

```yaml
servers:
  - id: physical-main
    type: physical
    connection: local       # ← was "ssh" during Mac dev. Change to "local" here.
    labels: [internal, default]

  - id: client-acme-prod
    type: ec2
    connection: ssh
    host: ec2-xxxx.compute.amazonaws.com
    ssh_user: ubuntu
    pem: acme               # resolves to /devops_agent/pem/acme.pem
    region: ap-south-1
    labels: [client:acme, prod]

  # … one entry per client EC2
```

This is the **only code/config difference** between dev and prod (spec §6).

---

## 5. Deny-list must include existing containers

Before first run, edit `config/tool_tiers.yml` (or wherever the deny-list lives) to include every container currently running on this host so the agent cannot accidentally touch them:

```yaml
denylist_containers:
  - mongo
  - agent
  - traefik
  # existing client workloads — from the pre-dev server audit
  - datasetsmith_frontend
  - datasetsmith_backend
  - brandsmith_frontend
  - brandsmith_backend
  - voice-agent-worker
  - voice-auth-backend
  - voice-frontend
  - voice-mongo
  - livekit-redis
  - ai_backend
  - ai_frontend
  - gradscaler-next-container
  - anno-backend-container
  - anno-frontend-container
  - nyayos_backend
  - nyayos_frontend
  - nyayos_website
  - recording_backend
  - recording_frontend
  - recording_db
```

Any future client container added on this host should be appended here at onboarding time. The agent should NEVER be able to `/stop` a container it didn't deploy itself.

---

## 6. Install dependencies

```bash
make install
# or manually:
python3.11 --version 2>/dev/null || python3 --version  # confirm >=3.11
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

The pre-dev audit confirmed Python 3.12.3 is present, so `python3 -m venv` works out of the box.

---

## 7. Pick a run mode

### Option A — Direct `make dev` / `make run` (simplest)

For initial verification only. Not a production pattern.

```bash
. .venv/bin/activate
AGENT_PORT=8100 uvicorn api.main:app --host 0.0.0.0 --port 8100 &
# or
make run   # after updating the Makefile to use AGENT_PORT
```

### Option B — Docker Compose (recommended)

The spec §22 says `docker compose up -d`. Make sure your `docker-compose.yml` on this server:

- Exposes the FastAPI on `AGENT_PORT` (8100 on this host)
- Mounts `/devops_agent/pem` read-only into the container: `- /devops_agent/pem:/devops_agent/pem:ro`
- Mounts the host Docker socket so the agent can control local Docker: `- /var/run/docker.sock:/var/run/docker.sock`
- Uses `restart: unless-stopped`

```bash
docker compose up -d
docker compose logs -f agent
```

### Option C — systemd (best for a box that reboots rarely)

Create `/etc/systemd/system/devops-agent.service`:

```ini
[Unit]
Description=DevOps Agent
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=server
WorkingDirectory=/home/server/devops-agent
EnvironmentFile=/home/server/devops-agent/.env
ExecStart=/home/server/devops-agent/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8100
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now devops-agent
sudo systemctl status devops-agent
```

---

## 8. Verify it's running

```bash
# liveness
curl -s http://localhost:8100/health | jq
# metrics (Prometheus format)
curl -s http://localhost:8100/metrics | head
# process
ss -tlnp | grep :8100
```

Then on Telegram, DM your bot:

- `/repos` — should return cached org repos within 100 ms
- `@yourbot trad` — inline mode should show fuzzy matches
- `/status` — should show an empty table (no deployments yet) or just the agent itself

---

## 9. Backup the one thing worth backing up

The only irreplaceable state the agent owns is Mongo. Everything else (PEMs, `.env`, `servers.yml`) you already have copies of on your Mac.

Add a daily mongodump cron (or use Atlas snapshots if you migrated there):

```bash
# /etc/cron.daily/devops-agent-backup
#!/bin/bash
mongodump --db devops_agent --gzip --archive=/var/backups/devops_agent/$(date +%Y%m%d).gz
find /var/backups/devops_agent -name '*.gz' -mtime +30 -delete
```

```bash
sudo mkdir -p /var/backups/devops_agent
sudo chown server:server /var/backups/devops_agent
chmod +x /etc/cron.daily/devops-agent-backup
```

30-day retention is plenty — the TTL indexes (§20) are already pruning old state automatically.

---

## 10. Updates after the first deploy

When you push a new version from your Mac:

```bash
ssh server@122.172.241.96
cd ~/devops-agent
git fetch origin
git pull origin main
. .venv/bin/activate
pip install -e ".[dev]"   # only if deps changed

# restart depending on run mode
sudo systemctl restart devops-agent      # systemd
docker compose up -d --build              # compose
# or kill + re-run manually
```

If the update touches Mongo schemas or the LangGraph state, **stop the agent first, run the migration, then start.** Never update while approval interrupts are pending (the checkpointer will recover correctly, but a schema change mid-interrupt will confuse you).

---

## 11. Monitoring — minimum viable

The agent already exposes `/metrics`. Scrape it with a tiny Prometheus container on this box or (cheaper) just have a cron curl it and alert on missing scrapes:

```bash
# /etc/cron.d/devops-agent-heartbeat
*/5 * * * * server curl -fs http://localhost:8100/health >/dev/null || /usr/bin/logger -t devops-agent "HEALTHCHECK FAILED"
```

With `ENABLE_LOG_ALERTS=true` in `.env`, the agent's own scraper (§9.3) will also Telegram-alert you on any error-severity event in deployed workloads. That's enough for a single-user setup.

---

## 12. Rollback plan for the agent itself

If a new agent version breaks:

```bash
ssh server@122.172.241.96
cd ~/devops-agent
git log --oneline -10                    # find the last good commit
git checkout <last-good-sha>
sudo systemctl restart devops-agent
```

Mongo schema is append-only in the spec — TTL indexes handle cleanup, nothing "migrates" that you'd need to revert. If that ever changes, document the down-migration here.

---

## Quick reference card

| Action | Command |
|---|---|
| SSH in | `ssh server@122.172.241.96` |
| Agent logs (systemd) | `sudo journalctl -u devops-agent -f` |
| Agent logs (compose) | `cd ~/devops-agent && docker compose logs -f agent` |
| Restart agent | `sudo systemctl restart devops-agent` |
| Health check | `curl -s http://localhost:8100/health` |
| Disk check | `df -h / && docker system df` |
| Running containers | `docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'` |
| Mongo shell | `mongosh mongodb://localhost:27017/devops_agent` |
| Emergency stop | `sudo systemctl stop devops-agent` (other client containers keep running) |
