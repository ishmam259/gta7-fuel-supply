# GTA 7 — Fuel Supply Intelligence & Resilience Platform (BUP CSE FEST 26 finals)
Read `docs/BRIEF.md` (judging + requirements), `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/TASKS.md` before working.
Simulator reference: `docs/BUP_Fuel_Supply_Simulator_Integration_Guide_Final.pdf` (REST is truth, SSE is a hint).

## Ownership (stay in your folder)
| Folder | Owner |
|---|---|
| `backend/app/` (except `intel/`), `docker-compose.yml`, `.github/`, `docs/API_CONTRACT.md` | Ishmam |
| `backend/app/intel/`, `backend/tests/intel/` | Farhan |
| `web/` | Sakib |
| `ops/`, `scripts/`, `loadtest/`, `docs/RESILIENCE.md`, `docs/LOAD_TEST.md`, `docs/DEMO_SCRIPT.md` | Badrul |

## Run
- Simulator: `docker compose up -d simulator-api` → http://localhost:8000/docs, admin console http://localhost:8000/admin
- Backend: `cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && fastapi dev app/main.py --port 8090`
- Web: `cd web && npm install && npm run dev` (http://localhost:3000, `NEXT_PUBLIC_API_URL=http://localhost:8090`)
- Everything: `docker compose up --build`

## Rules
- The API contract is the source of truth; only Ishmam changes it.
- Quantities and allocation decisions come from deterministic code in `intel/`; the LLM only explains, summarizes and assists. Every LLM call has a template fallback.
- Every simulator call goes through the resilient client (timeouts, retries, circuit breaker, validation). Never crash on a bad response.
- Allocation POSTs always carry an idempotency key. Consequential actions need operator approval (`X-Operator-Key`).
- Secrets only in `.env` (git-ignored); list names in `.env.example`. Never commit keys.
- Verify before saying done: run the server/tests and show output; for UI, open it in the browser.
- Commit messages: plain, no AI/Claude attribution lines.
