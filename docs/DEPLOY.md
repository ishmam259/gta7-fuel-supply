# Deploy & scale

## Architecture for scale
```
                 ┌────────────── gateway (nginx :80) ──────────────┐
 browser ──────► │ /            → web (operator console)            │
                 │ /api reads   → api replicas (round-robin) ───┐   │
                 │ /api writes, control, SSE → backend (engine) │   │
                 │ /grafana/, /prometheus/                      │   │
                 └──────────────────────────────────────────────┼───┘
   backend = ENGINE (1, single writer)                           │
     tick loop · approvals (serialized) · mode · chaos · stream  │
     writes snapshot + recommendations + audit ──► postgres ◄────┘ api replicas (N, stateless)
     ▲ resilient client                                             read snapshot (1 s cache),
     └── BUP Fuel Supply Simulator                                  what-if, status, AI assistant
```
- **Why one engine:** decisions and approvals must never be made twice. One writer keeps the tick loop, the approval queue
  and idempotency simple and correct (no distributed locking needed). The simulator is single-tenant anyway.
- **What scales:** all operator traffic (dashboard polling, what-if, status, AI assistant) is served by **stateless API
  replicas** that read the engine's snapshot from Postgres. Add replicas with one command; the gateway (Docker DNS,
  re-resolved every 10 s) and Prometheus (DNS service discovery) pick them up automatically.
- **Same-origin gateway:** the console calls relative `/api/...` URLs, so the same build works on localhost, a VM or a
  public tunnel without rebuilding.

## Run locally
```bash
cp .env.example .env              # set OPERATOR_KEY, OPENAI_API_KEY / GEMINI_API_KEY / GROQ_API_KEY
docker compose up -d --build      # engine + 2 API replicas + gateway + postgres + simulator + Prometheus + Grafana
docker compose up -d --scale api=4 --no-recreate   # scale reads (no restart of anything else)
```
Open http://localhost (console) · http://localhost/api/system/status · http://localhost/grafana/ · http://localhost/prometheus/

## Deploy on a Linux VM (e.g. Poridhi Starter Lab)
```bash
# 1. Docker (skip if the lab image already has it)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. Code (repo is private until the deadline: use a GitHub token or `gh auth login`)
git clone https://github.com/ishmam259/gta7-fuel-supply.git && cd gta7-fuel-supply

# 3. Configuration: secrets stay on the VM, never in git
cp .env.example .env && nano .env     # OPERATOR_KEY=<strong value>, LLM keys, POSTGRES_PASSWORD=<strong value>

# 4. Start and verify
docker compose up -d --build
curl -fsS http://localhost/gateway/health && curl -fsS http://localhost/api/system/status
```
Expose **port 80** in the lab's port-forward / security settings; judges open `http://<vm-address>/`.
Everything (console, API, Grafana, Prometheus) is on that one port.
Update after a new commit: `git pull && docker compose up -d --build` (the simulator and database keep their state).

## Verify scaling
```bash
docker compose ps api                                   # N replicas running
for i in 1 2 3 4 5 6; do curl -s -D - -o /dev/null http://localhost/api/state | grep -i x-gta7-upstream; done
# the X-GTA7-Upstream header rotates across replica IPs
```
Grafana → *GTA7 Fuel Ops – Platform Health* → "API replicas up", "Requests served per replica", CPU & memory per instance.
Load-test comparison (1 vs N replicas): see `docs/LOAD_TEST.md`.

## Rollback
Every push to `main` is built and smoke-tested by CI (build → test → deploy → health check → scale check).
Roll back with `git checkout <previous-tag> && docker compose up -d --build`.

## Deploy on Render (Blueprint)
Render runs one container per service (no compose), so the Blueprint (`render.yaml`) deploys a slimmer layout:
simulator image + backend (`ROLE=all`: engine and API in one process) + console + Render Postgres. Grafana/Prometheus
stay in the compose deployment.
1. Render dashboard → **New → Blueprint** → select `ishmam259/gta7-fuel-supply` → it reads `render.yaml`.
2. Fill the `sync: false` values (first pass: leave URLs blank, paste your LLM keys) → **Apply**.
3. When the services have URLs, set them and redeploy:
   - `gta7-backend` → `SIMULATOR_URL=https://<gta7-simulator>.onrender.com`, `CORS_ORIGINS=https://<gta7-web>.onrender.com`
   - `gta7-web` → `NEXT_PUBLIC_API_URL=https://<gta7-backend>.onrender.com` → **Manual Deploy → Clear build cache & deploy**
     (the value is baked in at build time).
4. Check `https://<gta7-backend>.onrender.com/api/system/status`, then open the console URL. The operator key is the
   generated `OPERATOR_KEY` on `gta7-backend` (Environment tab).
Plans: simulator and backend on **Starter** (free instances sleep after 15 min idle, which stops the tick loop and resets
the simulator); console can stay free. Scaling on Render: raise the backend's instance count only with `ROLE=api`
replicas plus a separate `ROLE=engine` service (paid; the compose deployment shows scaling end to end).
