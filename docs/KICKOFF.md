# Kickoff — start here (everyone)

## 1. Setup (5 min)
```bash
git clone https://github.com/ishmam259/gta7-fuel-supply.git
cd gta7-fuel-supply
docker compose up -d simulator-api          # simulator at http://localhost:8000 (docs: /docs, console: /admin)
curl http://localhost:8000/v1/health        # expect {"status":"ok",...}
git checkout -b <your-branch>               # Farhan: intel · Sakib: web · Badrul: ops · Ishmam: be-core
cp .env.example .env                        # put YOUR OWN API keys in .env (never commit it)
claude                                      # start Claude Code inside the repo folder
```
Merge rhythm: every ~45 min → `git pull --rebase origin main`, then push your branch and tell Ishmam to merge (or open a PR).
Checkpoint at **12:00**: full loop working end-to-end. Feature freeze **14:00**.

## 2. Your first Claude prompt

### Farhan Tahsin Khan — intelligence (branch `intel`)
```
Read CLAUDE.md, docs/BRIEF.md, docs/ARCHITECTURE.md, docs/INTEL_INTERFACE.md, docs/API_CONTRACT.md and
docs/TASKS.md section B. You own backend/app/intel/ only. First write models.py and the function
signatures from INTEL_INTERFACE.md with simple working bodies, and push within 30 minutes so Ishmam
can call them. Then build forecast, risk, detect, planner (obey every simulator limit in the guide
PDF §5.2), fallback_plan, simulate and genai (Gemini with a template fallback). Use the running
simulator at localhost:8000 to fetch a real snapshot as a test fixture. Write pytest tests and run them.
```

### Mahmudul Hasan Sakib — operator dashboard (branch `web`)
```
Read CLAUDE.md, docs/BRIEF.md, docs/API_CONTRACT.md and docs/TASKS.md section C. You own web/ only.
Scaffold Next.js + shadcn with official CLIs (create-next-app, then shadcn init and add the
login/dashboard/sidebar blocks you need). Build a typed API client from API_CONTRACT.md with a mock
mode that returns the contract's example JSON, so the UI works before the backend is ready. Build pages
in the TASKS.md order: overview, stations/depots, alerts + recommendations inbox with inspect/what-if/
approve, decision history, system status, control panel. Label data as SIMULATED. After each page,
open it in the browser and fix issues.
```

### Kazi Badrul Hasan — crisis, resilience, observability, load test, pitch (branch `ops`)
```
Read CLAUDE.md, docs/BRIEF.md, the simulator guide PDF §7 (admin events/faults) and docs/TASKS.md
section D. You own ops/, scripts/, loadtest/ and the resilience/load-test docs. First write crisis
scenario scripts for all 5 crisis types plus a combined crisis, and fault drills, using the
simulator's /admin endpoints at localhost:8000. Test each script against the running simulator.
Then add Prometheus + Grafana provisioning in ops/ and a k6 load test in loadtest/.
```

### Ishmam Tahmid — backend core (branch `be-core`)
Backend skeleton, resilient simulator client, state sync, executor + approval flow, API, `/metrics`, docker-compose, CI.

## 3. Rules
- Stay inside your own folders (see CLAUDE.md ownership table). Contract changes go through Ishmam.
- No secrets in git. Plain commit messages.
- If Claude usage runs out → switch to Puku Editor/CLI (free from Poridhi).
