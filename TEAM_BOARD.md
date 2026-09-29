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
| **12:00** | **Checkpoint:** everything below marked done or explicitly dropped |
| **13:30** | **Feature freeze.** Only demo-breaking fixes after this |
| **14:00** | **Round 2:** 4 min presentation + 3 min Q&A (selected teams) |
| 15:30 | Submission deadline (repo public after deadline) |

## Current status (verified live by Ishmam, 11:55)
- Stack: `docker compose up --build` → simulator :8000, backend :8090, console :3000, Prometheus :9090, Grafana :3001. All healthy.
- AI/ML verified: forecast (MAPE 5%), risk model, detection, LP optimizer (recs 100% → 21% risk), LLM explanations,
  briefing and assistant (OpenAI, 0 failures), fallbacks unused.
- Evidence done: `docs/LOAD_TEST.md` (10/25/50/100 VUs, 0% errors), `docs/RESILIENCE.md` (all faults, screenshots),
  benchmark: **100% vs 83.4%** service level with vs without the platform (combined crisis, same seed).
- 101 backend tests passing, CI green.
- Simulator is **reset and paused at tick 0** on Ishmam's laptop, ready for the demo. **Don't reset it during judging.**

## Open items

### Farhan Tahsin Khan (intelligence)
- [x] **False positive alert:** "Unexplained petrol inventory drop −8000 L at Patiya Depot (ticks 80–82)". The simulator
      audit shows `supply-105` **ARRIVED +8000 L** at tick 80 (`GET /admin/audit`). The inventory-accounting detector
      seems to invert or double-count supply arrivals when snapshots are several ticks apart (e.g. after `step n=4`).
      → `2dcb5e9`, `60a2e8a`: cause = snapshot race (tick read first, lists fetched in parallel, so contents can be
      ahead of the label and the supply was counted twice). Now tolerates up to 3 ticks of lag; real leaks still caught.
- [x] **Groq fallback model** `llama-3.1-8b-instant`: Llama left Groq's free tier in August; use `openai/gpt-oss-20b`
      (or another current free model) so the fallback really works.
      → `2dcb5e9`: confirmed 404; defaults now `qwen/qwen3.8-27b` → `openai/gpt-oss-120b` → `openai/gpt-oss-20b` (all tested live).
- [x] (Label) A station can show level "ok" next to p=98%: consider labelling the probability
      "24 h stockout risk if no action" or folding probability into the level.
      → `60a2e8a`: folded in, level is `watch` when 24 h risk ≥ 90% (or < 16 h left). Sakib: label p as "24 h stockout risk if no action".
- [x] Confirm for Q&A: why a single card's impact (e.g. 99% → 9%) can differ from its what-if (99% → 71%): the card
      counts the paired shipment on the other route; say so on the card.
      → `60a2e8a`: confirmed. Card signal now reads "risk after counts this truck together with 5000 L via route-…;
      this truck alone: 97% (what-if shows the single truck)".
- [ ] Read `docs/`/Q&A answers Q5–Q19 (Ishmam has the PDF) and correct anything wrong about your code.

### Mahmudul Hasan Sakib (console)
- [ ] **System Status wording:** resilience cards read "LLM unavailable – HEALTHY" / "ML unavailable – HEALTHY", which judges
      will misread. Rename titles to "If LLM fails → template fallback" / "If ML fails → rule-based fallback" and show
      the badge as the current state (e.g. "LLM OK (openai)" from `llm_detail.last_provider`).
- [ ] **Empty tank labelled "OUTAGE":** "OUTAGE" is the simulator's word for a station outage. For a fuel with 0 L show
      "STOCKOUT"/"EMPTY" (station header currently shows "OPEN" and "OUTAGE" together).
- [ ] System Status text says fallback "reorders at 35% capacity"; the backend fallback uses **50%**.
- [ ] Duplicate toast: "New recommendation #N" appears twice.
- [ ] Phone-width check of Overview (network map) and tables on Stations/History (could not verify automatically).

### Kazi Badrul Hasan (evidence & pitch)
- [ ] **Slides for Round 2 (4 minutes!)**: cut `prep/GTA7_Pitch_Template.pptx` to ~5 slides + ~2.5 min live demo.
      Suggested demo: Overview → inject demand spike (Control & Chaos) → alert + recommendation → inspect card →
      approve → inject "Simulator down" → degraded banner → recovery → Grafana.
- [ ] `docs/DEMO_SCRIPT.md`: exact clicks for the demo above + fallback if a step fails.
- [x] Load test: results in `docs/LOAD_TEST.md` (run by Ishmam with your k6 script).
- [x] Resilience: `docs/RESILIENCE.md` filled with results + screenshots in `docs/evidence/`.
- [ ] Delete the unused `ops/prometheus.yml` (targets the wrong port; the live config is `ops/prometheus/prometheus.yml`).

### Ishmam Tahmid (backend, DevOps, merges)
- [ ] README: setup, architecture diagram, features vs brief, results, **Credits** (every library/API/model): required.
- [ ] Merge everyone's branches at 12:00 and 13:30; tag `v1.0` at freeze.
- [ ] After the deadline: make the repo public.

## Messages
- **11:55 · Ishmam → All:** Board created. Please pull, tick your items as you finish (with commit hash), and push small
  commits often. Anything that blocks you → write it here and ping in the group chat.
- **12:00 · Farhan → Ishmam:** 4 of my 5 items fixed on `intel` (`2dcb5e9`, `60a2e8a`), 106 tests green; please merge.
  (1) Please add `GROQ_MODEL_PRIMARY` / `GROQ_MODEL_FALLBACK` to `.env.example`. (2) Please send me the Q&A PDF (Q5–Q19),
  it's not in the repo. (3) Correction for the round-1 doc: trucks **depart on the tick they're ordered**
  (tested on the simulator), so lead time is **2–4 ticks (30–60 min)**, not "1-tick departure" / 3–5 ticks.
