# Phase 5 — Deploy Pipeline (Build → Push → Pull → Run)

| Field | Value |
|---|---|
| **Status** | ⚪ QUEUED |
| **Started on** | — |
| **Completed on** | — |
| **Depends on** | Phase 4 |
| **Blocks** | Phase 7 (rollback depends on image_history), Phase 8 (diagnostics need deployed containers), Phase 9 (scraper needs running containers) |
| **Spec references** | `docs/PROJECT_V2.md` §5.4 (pipeline), §5.5 (auto-cleanup), §11.6 (self-updating message), §14.5 (hardening), §16 (timings), §20 (`deployments` collection) |

---

## Objective

The core value prop: `/deploy <repo> <branch>` clones, builds with BuildKit cache, pushes to Docker Hub, pulls on the target server, runs the container with hardening defaults, performs a healthcheck, auto-cleans old images, and streams progress into a single Telegram message via `edit_message_text`.

## Design choices

| Choice | Why |
|---|---|
| **Shallow clone (`git clone --depth 1`)** | §16.1 — 5–10x faster than full clone; we only build the tip commit. |
| **BuildKit cache mounts (`DOCKER_BUILDKIT=1`)** | §16.1 — 3–10x faster rebuilds; layer ordering (deps before code) maximises hit rate. |
| **Idempotent: skip build if `image_name:commit_sha` already exists on Docker Hub** | §16.1 — saves 30–90 s on no-op redeploys. |
| **Skip push when `target_server.connection == "local"`** | §16.1 — image is already on the daemon we'll run against. |
| **Commit SHA + `:latest` dual tag** | §"Conventions" in CLAUDE.md — commit SHA is the rollback anchor, `:latest` is a convenience pointer. |
| **Hardening defaults injected on every `docker run`** | §14.5: `--read-only` + `tmpfs /tmp`, `--cap-drop=ALL`, `--security-opt no-new-privileges`, `--memory`, `--cpus`, `--pids-limit`. |
| **Warn (not block) if Dockerfile has no `USER`** | §14.5 — we can't validate every base image's user story; a warning surfaces the risk. |
| **`image_history` capped at 5 entries (FIFO)** | §5.5 + §20 — keeps rollback fast and Docker Hub storage bounded. |
| **Auto-cleanup scoped per-repo only** | §"Auto-cleanup invariants" in CLAUDE.md — never touch images from other repos. |
| **Every deletion audit-logged** | §5.5 — `deleted_images` with actor=`system:auto_cleanup`. |
| **Single self-updating Telegram message via `edit_message_text`** | §11.6 — no chat spam. |

## Deliverables

### Files created

- `tools/docker_tools.py` — `deploy`, `restart`, `redeploy`, `stop` registered as `@tool` (deploy+restart+redeploy = notify, stop = approval).
- `utils/git_ops.py` — `shallow_clone(repo_url, branch, dest)`, `get_head_sha(repo_dir)`.
- `utils/docker_ops.py` — `build_image`, `image_exists_remote`, `push_image`, `pull_image`, `run_container`, `stop_container`, `remove_container`, `inspect_container`.
- `utils/docker_hardening.py` — `build_run_args(config, env)` producing the §14.5 flag set.
- `utils/image_cleanup.py` — `cleanup_old_images(repo, server_id, keep_tags)` with per-repo scope, audit log hooks.
- `telegram_bot/messages.py` — extended with `build_deploy_progress_message(steps)` for §11.6 streaming.
- `tests/unit/test_image_cleanup.py` — keeps current + history, prunes older, never touches other repos.
- `tests/unit/test_docker_hardening.py` — every hardening flag present in produced args.
- `tests/integration/test_deploy_flow.py` — end-to-end against local Docker Desktop (skipped if `DOCKER_HOST` unset).

### `deployments` collection writes

On successful deploy, upsert by `_id = config.name`:
```json
{
  "_id": "<name>",
  "repo": "<owner>/<repo>",
  "branch": "<branch>",
  "project": "<project>",
  "target_server": "<server_id>",
  "current_image": "<hub>/<repo>:<sha>",
  "previous_image": "<prev-sha tag or null>",
  "image_history": ["<sha1>", "<sha2>", ..., "<sha5>"],   // capped FIFO
  "container_id": "<docker id>",
  "port": <int>,
  "status": "running",
  "deployed_at": <ISODate>,
  "deployed_by": "telegram:<user>"
}
```

### Folder tree delta

```
tools/
└── docker_tools.py      ← new
utils/
├── git_ops.py           ← new
├── docker_ops.py        ← new
├── docker_hardening.py  ← new
└── image_cleanup.py     ← new
tests/unit/
├── test_image_cleanup.py
└── test_docker_hardening.py
tests/integration/
└── test_deploy_flow.py
```

## Prerequisites

- `docker login` completed on the dev machine (Docker Hub credentials in keychain)
- `.env` has `DOCKER_HUB_USER` and `DOCKER_HUB_TOKEN`
- At least one test repo under `GradScalerTeam` has a `deploy.config.yml` + `Dockerfile`

## Verification

```bash
# 1. Unit tests
make test

# 2. Deploy a real test repo to local Docker Desktop
# On Telegram: /deploy <test-repo> main
# Expect the message to update in place:
#   ✅ Cloned (1s)
#   ✅ Built (12s)
#   (skipped push — local target)
#   ✅ Pulled (skipped — local)
#   ✅ Running → http://localhost:<port>
#   ✅ Cleaned up N old images

# 3. Container hardening applied
docker inspect <deployed-name> --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.SecurityOpt}}'
# expect: true [CAP_DROP_ALL] [no-new-privileges]

# 4. Deployments collection populated
mongosh "$MONGO_URL" devops_agent --eval 'db.deployments.find().pretty()'

# 5. Deploy 6 times in a row → image_history stays capped at 5
for i in 1 2 3 4 5 6; do
  # trigger /deploy test-repo main via telegram or CLI
done
mongosh "$MONGO_URL" devops_agent --eval 'db.deployments.findOne({}).image_history.length'
# expect: 5

# 6. Cleanup only touched this repo's images
docker images | grep <other-repo>
# expect: untouched

# 7. Audit log has deploy + cleanup rows
mongosh "$MONGO_URL" devops_agent --eval 'db.audit_log.find({action: {$in: ["deploy","cleanup_image"]}}).count()'
# expect: >= (1 deploy + N cleanup)

# 8. Lint + typecheck
make lint && make typecheck
```

## Acceptance criteria

- [ ] `/deploy <repo> <branch>` runs a real container on Mac Docker Desktop in <30 s (warm cache)
- [ ] Hardening flags applied: `ReadonlyRootfs=true`, `CapDrop=[CAP_DROP_ALL]`, `no-new-privileges=true`, memory/cpu/pids limits set
- [ ] Single Telegram message updates in place across all 5+ steps
- [ ] `deployments` upsert includes `image_history` capped at 5
- [ ] Idempotent redeploy on same commit takes <10 s (skips build + push)
- [ ] Dockerfile without `USER` triggers a warning in the deploy message
- [ ] Auto-cleanup deletes only this repo's non-history tags; every deletion audit-logged
- [ ] Integration test passes on local Docker Desktop
- [ ] `make lint` + `make typecheck` + unit tests clean

## What this phase does NOT do

- No rollback (Phase 7)
- No approval flow for `stop` yet — stop is registered but using the plain notify path; proper HITL comes with Phase 7
- No `/images` command yet (Phase 7 — it belongs with the destructive ops surface)
- No pre-deploy AI review (Phase 10)

## Rollback

```bash
rm -rf tools/docker_tools.py \
       utils/git_ops.py utils/docker_ops.py \
       utils/docker_hardening.py utils/image_cleanup.py \
       tests/unit/test_image_cleanup.py tests/unit/test_docker_hardening.py \
       tests/integration/test_deploy_flow.py
# clean up any test containers: docker ps -a | grep <test-name> | awk '{print $1}' | xargs docker rm -f
# clean up any test images: docker images | grep <test-repo> | awk '{print $3}' | xargs docker rmi
```
