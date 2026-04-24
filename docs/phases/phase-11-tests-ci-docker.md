# Phase 11 — Tests, CI, Dockerfile, docker-compose

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phases 1–10 (everything that the CI pipeline needs to lint, typecheck, test, and containerize) |
| **Blocks** | Phase 12 (prod deployment uses the compose + image shipped here) |
| **Spec references** | `docs/PROJECT_V2.md` §3 (test stack), §17 (structure), §22 (setup), §24 (verification checklist) |

---

## Objective

Close the loop: exhaustive test coverage, a GitHub Actions CI, a hardened production `Dockerfile`, a `docker-compose.yml` that brings up the agent + Mongo, and one pass through the spec's §24 verification checklist (20 items) before prod.

## Design choices

| Choice | Why |
|---|---|
| **Multi-stage Dockerfile: builder → slim runtime** | Smaller image, faster push/pull (§16.1). |
| **Distroless or slim Python base (`python:3.12-slim`)** | Fewer CVEs, smaller surface. |
| **Non-root user inside container (`USER agent`)** | §14.5 — agent hardens its own containers, must harden itself. |
| **`docker-compose.yml` ships agent + mongo** | Single `docker compose up -d` on prod (§22). Mongo is a sibling service with a named volume. |
| **Socket mount: `/var/run/docker.sock:/var/run/docker.sock`** | Required for `connection: local` targets (§6). |
| **PEM mount: `/devops_agent/pem:/devops_agent/pem:ro`** | Agent reads, never writes. |
| **GitHub Actions CI: ruff → mypy → pytest** | §3 — every PR must pass all three. |
| **Fail CI on coverage <70% of first-party code** | Keeps us honest; doesn't demand 100% because tool wrappers are hard to test without network. |
| **Integration tests skipped if `DOCKER_HOST` or `MONGO_URL` unset** | CI runs unit tests only; integration runs locally. |
| **`tests/eval/agent_eval_set.json` fixture** | §17 — seed for future eval runs (free-text intent parse accuracy). |

## Deliverables

### Files created

- `Dockerfile` — multi-stage, non-root, sets `USER agent`, `HEALTHCHECK`, exposes `AGENT_PORT`.
- `docker-compose.yml` — `agent` + `mongo` services, named volumes, env file, socket + PEM mounts, `restart: unless-stopped`.
- `.github/workflows/ci.yml` — lint + typecheck + test + coverage; runs on every PR and push to main.
- `docs/security.md` — threat model per §23.
- `docs/architecture.md` — pointer + diagram index to PROJECT_V2.
- `docs/runbook.md` — one-pager: what to do when X breaks.
- `MongoDB-Setup.md` — local + Atlas paths.
- `tests/eval/agent_eval_set.json` — at least 20 free-text prompts with expected intents.
- Any unit tests still missing from §17 (`test_github_tools.py`, `test_docker_tools.py`, `test_fuzzy_resolver.py`, `test_deploy_config_schema.py`, etc. if earlier phases left gaps).

### Folder tree delta

```
.github/workflows/ci.yml
Dockerfile
docker-compose.yml
MongoDB-Setup.md
docs/security.md
docs/architecture.md
docs/runbook.md
tests/eval/agent_eval_set.json
```

## Verification — spec §24 checklist

Every item below must be green:

- [ ] 1 · **Guardrails**: `/stop mongo` refused; non-allowlisted user's `/deploy` refused
- [ ] 2 · **Approval**: `/stop test-dep` → button → approve → typed-confirm → stops
- [ ] 3 · **Inline mode**: `@yourbot tra` returns `trading-dashboard` in top result <200 ms
- [ ] 4 · **Fuzzy resolve**: `/deploy trding-dashbord main` → "did you mean `trading-dashboard`?"
- [ ] 5 · **Audit log**: every command writes an audit row
- [ ] 6 · **Checkpointing**: kill mid-deploy → restart → resumes
- [ ] 7 · **Metrics**: `/metrics` shows Prometheus counters
- [ ] 8 · **Container hardening**: `ReadonlyRootfs: true`, `CapDrop: [ALL]`
- [ ] 9 · **Multi-target**: deploy with `target_server: client-acme-prod` goes to EC2
- [ ] 10 · **Identifier resolution**: container name / repo / project all resolve
- [ ] 11 · **Auto-cleanup**: 6 deploys → 5 images remain
- [ ] 12 · **Rollback**: `/rollback` <10 s
- [ ] 13 · **`/images`**: shows last 5 versions
- [ ] 14 · **Layer 1**: `/report` <1 s, 0 tokens
- [ ] 15 · **Layer 2**: `/explain` returns hypothesis + token count
- [ ] 16 · **YAML validation**: typo'd field triggers "did you mean"
- [ ] 17 · **`.env` check**: `chmod 644 .env` logs a warning
- [ ] 18 · **Dev → prod**: `connection: ssh → local` requires no code change
- [ ] 19 · **AI toggles**: all three `false` → agent still deploys and diagnoses
- [ ] 20 · **CI**: a PR with a broken type fails CI

## Extra verification

```bash
# A. Image builds + runs
docker build -t devops-agent:dev .
docker run --rm -e MONGO_URL=<...> -e GITHUB_TOKEN=<...> devops-agent:dev python -c "import api.main; print('ok')"

# B. docker compose up
docker compose up -d
docker compose ps   # expect agent + mongo healthy
curl http://localhost:8000/health

# C. CI green
# Open a PR on a feature branch; GitHub Actions runs; all jobs green.

# D. Coverage gate
.venv/bin/pytest --cov=agents --cov=api --cov=telegram_bot --cov=tools --cov=utils --cov=config --cov-fail-under=70
```

## Acceptance criteria

- [ ] All 20 §24 items green
- [ ] `Dockerfile` builds a <200 MB image with non-root user
- [ ] `docker compose up -d` brings up agent + mongo; `/health` returns 200 within 30 s
- [ ] CI workflow green on a representative PR
- [ ] Coverage ≥70 % on first-party packages
- [ ] `docs/security.md`, `docs/runbook.md`, `MongoDB-Setup.md` all filled (no TODOs)

## What this phase does NOT do

- No prod deployment yet — Phase 12 uses these artifacts
- No E2E test against real EC2 — that's a manual step in Phase 12
- No advanced eval framework beyond the static fixture (§25 v3 roadmap)

## Rollback

```bash
rm -rf .github/workflows/ci.yml Dockerfile docker-compose.yml \
       MongoDB-Setup.md docs/security.md docs/architecture.md docs/runbook.md \
       tests/eval/agent_eval_set.json
```
