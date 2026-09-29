# Team GTA 7: Team Board

Shared place to talk through GitHub. **How to use it**
1. `git pull origin main` before you edit.
2. Only edit **your own section** under "Open items" (tick `[x]` when done and add the commit hash), and **append** new
   messages at the **bottom** of the "Messages" log. Never rewrite other people's lines, so merges stay conflict-free.
3. Message format: `- **HH:MM · Name → Name/All:** message`
4. Commit with a plain message (e.g. `Team board: Farhan update`) and push to `main` or your branch.
   Ishmam merges branches into `main` regularly.

## Schedule (29 Sep)
| Time | What |
|---|---|
| 11:00 | Round 1 judging: problem understanding & approach (done) |
| 12:40 | Plan v2 (below) |
| **14:00** | **Feature freeze** (moved), then only demo-breaking fixes |
| **14:00** | **Round 2:** 4 min presentation + 3 min Q&A (selected teams) |
| 15:30 | Submission deadline (repo public after deadline) |

## Current status (verified live by Ishmam, 12:40)
- **Scale-out is live on `main`:** one address **http://localhost** (also :8090) through an nginx gateway → console,
  API, `/grafana/`, `/prometheus/`. The backend is split into **1 engine** (single writer: tick loop, approvals, mode,
  chaos, live stream) and **N stateless API replicas** (reads, what-if, status, AI assistant) sharing **Postgres**.
  Scale reads with `docker compose up -d --scale api=3 --no-recreate`. See `docs/DEPLOY.md`.
- **After pulling `main`, run `docker compose up -d --build` and open http://localhost** (the console is no longer on :3000).
- Verified: reads round-robin across replicas, writes go to the engine, replicas see engine state within ~1 s,
  approve works, LLM healthy (OpenAI), Prometheus auto-discovers replicas. 106 tests pass.
- Evidence: benchmark **100% vs 83.4%**, `docs/LOAD_TEST.md`, `docs/RESILIENCE.md` (all faults + screenshots).
- About the bug report (stations 0 / "0 L – L" / all "template fallback"): on Ishmam's laptop the API shows real stock
  and 0 template fallbacks. Likely causes on other laptops: **no LLM keys in your `.env`** (→ template fallback everywhere),
  `NEXT_PUBLIC_MOCK` set, or a simulator left **running with nobody approving** (stations really drain to 0).
  Still check each one in the UI below.

## Plan v2 (12:40 → 13:30 freeze → 14:00 Round 2)
Push small commits often. **Hard stop 13:20** for code; after that only demo-breaking fixes.

### Mahmudul Hasan Sakib: all frontend
- [ ] **Notifications clickable:** alert toasts → `/alerts` (highlight that alert), recommendation toasts →
      `/recommendations` with that card open (`components/live-provider.tsx` lines ~57/66; sonner `action`/`onClick`).
- [ ] **Stations & Depots shows "0 L – L":** a value renders as empty/undefined; find the formatter and never print a
      bare "– L" (show "—" when a value is missing). Check against live `http://localhost/api/state`.
- [ ] **Overview network map shows 0 for all stations:** compare with `/api/state` (real stock there). If the API has
      values but the map shows 0, fix the fill-% mapping (inventory ÷ capacity per fuel).
- [ ] **Situation briefing only shows "Top risks":** show summary + top risks + recommended actions, and link each action
      to the matching recommendation in the inbox. Badge must read "AI (LLM)" vs "template fallback" from `source`.
- [ ] Carry-over: System Status wording ("If LLM fails → template fallback", badge = current state); empty fuel
      "STOCKOUT" not "OUTAGE"; fallback text 35% → **50%**; duplicate "New recommendation" toast; label p as
      "24 h stockout risk if no action"; quick phone-width check.
- [ ] Test everything on **http://localhost** (the gateway, same-origin URLs), not :3000.

### Farhan Tahsin Khan: reinforcement learning (+ intel)
- [ ] **RL, timeboxed to 13:20** (brief §8: optional, but must show why it helps vs the heuristic). Suggested:
      an **RL-tuned hybrid**: tabular Q-learning / bandit that picks the planner's **target cover level** (e.g. 12/18/24/30 h)
      per station × fuel from a small state (cover-hours bucket, depot-stock ratio, active event, route status);
      reward = −unmet L − small transport cost − overflow penalty. Train **offline** on the documented dynamics your
      forecast already encodes (not on the live simulator; too slow). Expose `intel/rl.py → rl_plan(...)` returning
      `RecommendationDraft(mode="rl")`, keep LP as default.
- [ ] Deliver numbers: **no-action vs LP vs RL** on the same scenario (Ishmam adds `policy` to the benchmark).
      If RL doesn't beat LP by 13:20, stop and say so honestly in Q&A: "evaluated; LP is used because …".
- [ ] Read Q&A answers Q5–Q19 (Ishmam sends the PDF) and correct anything about your code.

### Ishmam Tahmid: backend, DevOps, merges
- [x] Scale-out: engine + API replicas + gateway + Postgres, verified (`docs/DEPLOY.md`).
- [ ] Load test **1 vs 3 API replicas** at 100 VUs → "Scaling" section in `docs/LOAD_TEST.md`.
- [ ] Benchmark `policy` switch (`none | lp | rl`) for Farhan's RL comparison.
- [ ] Farhan's asks: `GROQ_MODEL_PRIMARY` / `GROQ_MODEL_FALLBACK` in `.env.example`; fallback ETA = tick + transit
      (trucks depart the tick they're ordered); send Q&A PDF.
- [ ] README with setup, architecture, results and **Credits** (required deliverable).
- [ ] Merge at 13:00 and 13:25; tag `v1.0` at freeze. Poridhi deployment after freeze (per `docs/DEPLOY.md`).

### Kazi Badrul Hasan: pitch, evidence, deployment support
- [ ] **Top priority: 4-minute slides + `docs/DEMO_SCRIPT.md` by 13:30.** ~5 slides: problem → solution/architecture
      (add the **scale-out diagram**: gateway → engine + replicas → Postgres) → live demo → results (100% vs 83.4%,
      load test, resilience) → roadmap. Demo: Overview → inject demand spike → alert + recommendation → inspect →
      approve → "Simulator down" → degraded banner → recovery → Grafana (replicas panel).
- [ ] Evidence: screenshot Grafana **"API replicas up" + "Requests served per replica"** during Ishmam's scaled load test.
- [ ] Read `docs/DEPLOY.md` and be ready to help with the Poridhi deployment after freeze.
- [ ] Delete the unused `ops/prometheus.yml`.
- [ ] 13:40: run a timed rehearsal with everyone (4 min + 3 min Q&A).

### Earlier items (done)
Farhan: false inventory alarm (`2dcb5e9`, `60a2e8a`), Groq models, watch level at ≥ 90% risk, paired-truck card note.
Badrul: load test and resilience docs (with Ishmam).

## Messages
- **11:55 · Ishmam → All:** Board created. Please pull, tick your items as you finish (with commit hash), and push small
  commits often. Anything that blocks you → write it here and ping in the group chat.
- **12:00 · Farhan → Ishmam:** 4 of my 5 items fixed on `intel` (`2dcb5e9`, `60a2e8a`), 106 tests green; please merge.
  (1) Please add `GROQ_MODEL_PRIMARY` / `GROQ_MODEL_FALLBACK` to `.env.example`. (2) Please send me the Q&A PDF (Q5–Q19),
  it's not in the repo. (3) Correction for the round-1 doc: trucks **depart on the tick they're ordered**
  (tested on the simulator), so lead time is **2–4 ticks (30–60 min)**, not "1-tick departure" / 3–5 ticks.
- **12:40 · Ishmam → All:** Plan v2 is up. Scale-out is on `main`: pull, `docker compose up -d --build`, open
  http://localhost. Sakib: all frontend items. Farhan: RL timeboxed to 13:20. Badrul: slides + demo script first.
- **12:40 · Ishmam → Farhan:** thanks. Merged; departure correction accepted (fixing my fallback ETA + docs); Groq vars
  going into `.env.example`; Q&A PDF coming via chat (kept out of the repo).
