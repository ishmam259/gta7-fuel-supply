# Farhan's Work Log: Intelligence Layer (`backend/app/intel/`)

GTA 7 Fuel Supply Intelligence & Resilience Platform, BUP CSE FEST 26 finals.
Owner: **Farhan Tahsin Khan**. Branch: **`intel`** (Ishmam merges it into `main`).

---

## 0. The big picture (read this first)

The organizers give us a **simulator**: a fake fuel network in Bangladesh with
**2 depots** (Gazipur, Patiya), **4 stations** (Mirpur, Tongi, Karnaphuli, Cox's Bazar),
**6 routes** and **3 fuels** (diesel, petrol, octane). Time moves in **ticks**; 1 tick = 15 simulated minutes.
Customers buy fuel at stations every tick. If a station runs dry, that demand is **lost** (unmet demand),
and the score (service level) drops.

The only thing we can do is send trucks: **POST an allocation** ("send X liters of fuel F from depot D to
station S over route R"). The simulator checks the request against strict rules and rejects anything illegal.

The team:

| Person | Part |
|---|---|
| Ishmam | Backend: talks to the simulator, stores data, API for the dashboard. Team lead; only he edits the API contract and merges into `main`. |
| **Farhan (me)** | **The brain.** Given a snapshot of the network, predict demand, measure risk, raise alerts, plan allocations, explain everything in plain language. |
| Sakib | Web dashboard for the operator. |
| Badrul | Crisis scripts, resilience tests, load test, slides. |

How my part is used: every tick, Ishmam's backend takes a **snapshot** of the whole network and calls my
functions in this order:

```
snapshot -> forecast() -> assess_risk() -> detect() -> plan() -> genai (explanations)
                                                          |
                                             fallback_plan() if plan() crashes
```

The operator sees my alerts and recommendations on Sakib's dashboard and clicks **Approve**. Only then does
the backend send the allocation to the simulator. The AI never decides quantities; my deterministic code does.
The LLM only explains.

---

## 1. Initial steps (setup)

1. Read the project docs: `CLAUDE.md`, `docs/TASKS.md` (section B is mine), `docs/INTEL_INTERFACE.md`,
   `docs/API_CONTRACT.md` and the simulator guide PDF.
2. Created my branch: `git checkout -b intel`.
3. Started the simulator: `docker compose up -d simulator-api`, then checked http://localhost:8000/docs (200 OK).
4. Created `.env` from `.env.example` (API keys go here and are never committed).
5. Saved **real snapshots** from the running simulator as test data (fixtures), so tests use real numbers:
   - `snapshot_tick24.json`: healthy network (6 simulated hours in)
   - `snapshot_tick200.json`: 2 days in, every station empty (a crisis where fuel is scarce)
   - `pair_live.json`: two snapshots 4 ticks apart with real allocations in between

**Rule I follow:** work and push only on `intel`, never push to `main`. To get team updates, merge `main`
into `intel` (not rebase; see bug G1 below).

---

## 2. Step-by-step progress

### Step 1: Models and interface (the "plug shape")

**What it does, in plain English:** before building anything smart, I agreed the exact shape of the data with
Ishmam, so his code can call mine from day one. `models.py` defines the objects (Snapshot, Forecast, Risk,
Alert, Recommendation, What-if) with the **same field names as the API contract**, so the backend can pass them
straight to the dashboard. I wrote all 10 functions with simple bodies that worked and pushed them within the
first 30 minutes.

**Files:** `models.py`, `__init__.py` (exports + signatures), first versions of every module, `test_smoke.py`.

**Bugs:** none at this stage. Design note: I added an optional `regions` field to `Snapshot`
(region demand factors). It defaults to empty, so it doesn't break Ishmam's calls.

---

### Step 2: Forecast (`forecast.py`), "how much will each station sell?"

**What it does:** for every station × fuel (12 pairs), predict how many liters will be sold in each of the next
16 ticks (4 hours).

**How:** the simulator guide documents how demand is generated:
`daily liters ÷ 96 × hour-of-day factor × demand_multiplier × region factor × random noise`.
For example, an industrial station is busy from 06:00 to 18:00 (×1.55) and quiet at night (×0.45).
My forecast uses that formula, then **adjusts itself to real history**. It compares the last 32 ticks of actual
sales with the formula and learns a correction factor. If a demand spike event changes the multiplier, the
forecast reacts **immediately** instead of waiting for history to catch up.

It also outputs:
- an **80% band** (`lower`, `upper`): the range the real value will usually fall in,
- `residual_std`: how noisy the series is,
- `mape_recent`: the recent average % error (the "prediction error" metric judges ask for).

**Result:** backtested on 2,688 real predictions, average error was **5.1%**. The naive "recent average"
method scored 64.7%.

**Bugs and fixes:**

| Bug | Why it happened | Fix |
|---|---|---|
| After a demand spike **ends**, the forecast would keep predicting spike-level demand. | The "adjust to history" step learned from spike-time history, and my override only triggered while the multiplier was ≠ 1. | The override now triggers whenever the learned factor and the current multiplier disagree by more than 25%, whether a spike starts or ends. Added a test for "spike just ended". |
| (Limitation, not a bug) The v1 forecast was a flat average. | First draft. | Replaced by the documented model above. |

Honest note for judges: the hour-of-day factors come from the guide, not learned from history.
Two days of history isn't enough to learn them reliably, and the guide values are exact.
The answer to give: *"documented demand model, calibrated online from demand history."*

---

### Step 3: Risk (`risk.py`), "who is going to run dry, and how likely is it?"

**What it does:** for every station × fuel:
- **Stockout hours:** hours until the tank hits zero. Computed with a 48-hour forecast so it follows day/night demand.
- **Stockout probability:** chance of running dry **within the next 12 hours** (see Ishmam's fix below).
  It uses the forecast band and the forecast's recent error, so "uncertain" demand means a higher probability.
- **Level:**
  - `outage`: empty, or the station has status OUTAGE
  - `critical`: less than 4 h left
  - `watch`: less than 12 h left or probability above 30%
  - `ok`: otherwise
- **Supply ETA:**
  - When the next truck reaches the station, counting trucks already driving (IN_TRANSIT) and ones just ordered (PENDING).
  - When the next supply reaches the depots that serve the station, including **DELAYED** supply. A DELAYED supply's `planned_tick` already includes the delay; if it's overdue, we expect it now.

**Bugs and fixes:**

| Bug | Why it happened | Fix |
|---|---|---|
| Stockout hours were too pessimistic. | Beyond 4 hours it assumed the current (busy-hour) rate would continue all night. | Use a 48-hour forecast that follows the daily demand curve. |
| PENDING trucks were ignored. | v1 only counted IN_TRANSIT. | Count PENDING too, using `destination_station_id` directly from the allocation. |
| **Off-by-one tick** in arrival times (found in step 4 by probing the real simulator). | I assumed a truck ordered at tick T leaves at T+1. In reality it leaves **at T** and arrives at **T + transit**, and fuel arriving at tick t is usable for tick t's demand. | Fixed arrival tick = created tick + transit, and the forecast's first value = the current tick. |
| **Probability showed 0.0 for stations with shortage alerts** (reported by Ishmam). | Probability looked only 4 hours ahead. A station 10 h from empty got p≈0 while raising a shortage alert. | Changed to "chance of stockout within **12 hours**", the window an allocation can still fix. Tongi diesel now shows **99%**. |

---

### Step 4: Detect (`detect.py`), "what should the operator be warned about?"

**What it does:** turns the situation into **alerts** with severity (info / warning / critical):

| Alert kind | Meaning in plain English |
|---|---|
| `shortage_risk` | A station is at watch/critical/outage. Says how many hours are left, how much fuel is arriving, and whether upstream supply is delayed. |
| `anomalous_demand` | Sales are far above what we predicted for this hour (z-score ≥ 3 = warning, ≥ 5 = critical), or a demand spike raised the multiplier. |
| `inventory_anomaly` | Stock changed without explanation. Station: old + deliveries − sales should equal new. Depot: old + supply − trucks sent should equal new. A difference beyond tolerance could mean a leak, theft or bad data. |
| `bottleneck` | A depot used ≥ 90% of its dispatch capacity this tick, a depot is CONSTRAINED, or a depot's stock won't last until its next supply arrives. |
| `disruption` | Active events, a route disrupted (critical if the station has no other route), a station in OUTAGE, a depot closed, supply delayed. |
| `low_confidence` | The forecast's recent error is above 20%. |

Each alert has a stable **`key`** (kind + entity + fuel + sub-code), so the backend can tell "the same problem
is still going on" from "a new problem" and resolve alerts when they go away.
If one detector crashes, the others still run.

**How I verified it:** I sent real allocations to the simulator and watched what happened tick by tick
(the "probe").

**Bugs and fixes:**

| Bug | Why it happened | Fix |
|---|---|---|
| Arrival timing was off by one tick. | See step 3. | Fixed in `risk.py`. |
| Dispatch used this tick was always 0. | The simulator doesn't report it. I was reading a field that doesn't exist. | Compute it by adding up allocations created this tick from that depot. A real **409 DISPATCH_CAPACITY_EXCEEDED** (6,000 + 5,500 > 11,000) confirmed the rule. |
| **False "unexplained inventory drop" at Patiya depot (−5,000 L).** | The depot was already **full** (85,000 L = capacity), so the simulator threw away the overflow when a supply truck arrived. My formula expected more fuel than possible. | Cap expected inventory at capacity. Real data now gives zero false alarms. |
| Two different depot bottlenecks (dispatch saturated and constrained) had the same key, so one was hidden. | Key didn't include the sub-type. | Added a `code` field to the key (`dispatch`, `constrained`, `low_stock`, `multiplier`). |
| Allocation POSTed at the same tick as the previous snapshot: is it already counted? | Depot stock drops the moment you POST, so it's ambiguous. | Accept either interpretation (whichever explains the change). Tested both. |

---

### Step 5: Planner (`planner.py`), "what trucks should we send?"

**What it does:** decides **which depot sends how much of which fuel over which route to which station**, and
explains why.

1. **Candidates:** every OPEN station × fuel at watch / critical / outage.
2. **Need:** liters to cover demand until the truck arrives **plus 24 hours**, minus what's in the tank and
   already on the way, capped by free tank space.
3. **Optimizer** (scipy `linprog`, HiGHS): decides the split when there isn't enough for everyone.
   - Stations more at risk count more.
   - A route that arrives **after** the station runs dry is worth less.
   - **Fairness:** the first 6 hours of cover for each station is worth 3× more, so every station gets a share
     before anyone is topped up. (Like giving everyone a slice of bread before anyone gets seconds.)
4. **Obeys every simulator rule** (guide §5.2): route max, depot open or constrained, station open, route
   available, depot stock, depot dispatch capacity this tick, station capacity. A `violations()` function
   replays these rules on every plan and drops anything the simulator would reject.
5. For each recommendation:
   - **Alternatives:** other legal routes/depots with their risk-after.
   - **Expected impact:** risk before → after, and liters of lost sales avoided.
   - **Confidence:** from forecast error. It goes down if the truck arrives late, only part of the need can be
     sent, or the network is disrupted.
   - **Needs human review** if confidence < 0.6, the truck arrives late, or the plan came from the fallback.
   - **Signals:** the reasons in words (spike, delay, blocked route, constrained depot, event...).
6. **Fallbacks:**
   - Optimizer crashes → greedy "most at-risk first" (`mode: heuristic`).
   - Forecaster crashes → `fallback_plan()`: recent-average demand + greedy, without the forecaster or the
     optimizer (`mode: fallback`).
7. **What-if (`simulate`)**: operator tries "what if I send X liters on route R?" and sees the inventory curve
   with/without it plus the risk before/after, with nothing sent to the simulator.

**Results:**
- Healthy network: 1 targeted recommendation, Tongi diesel 4,800 L, risk **99% → 0%**.
- Crisis (all stations empty): **all 12 station-fuel pairs** get fuel, and both depots use ~99% of their dispatch capacity.
- **Real simulator test:** 3 planning rounds, **20 allocations POSTed, 20 accepted, 0 rejected.**

**Bugs and fixes:**

| Bug | Why it happened | Fix |
|---|---|---|
| Stations at 0 L got **no** fuel. | Empty OPEN stations are level `outage`, and v1 only planned for watch/critical. | Include `outage` when the station is OPEN (it can still receive trucks). |
| Planner refused CONSTRAINED depots. | v1 required status OPEN; the guide says CONSTRAINED can still ship. | Allowed OPEN + CONSTRAINED everywhere. |
| `unmet_liters_avoided` was always 0. | v1 formula was wrong. | Compute lost sales with and without the truck over 12 h and subtract. |
| Quantities too small (Tongi 1,350 L, risk only 99% → 43%). | Target was only 12 h of cover. | Target 24 h of cover. |
| "Risk after" stayed 100% for empty stations. | They run dry **before** any truck can arrive, and that gap was counted. | "Risk after" counts from the truck's arrival onward. A signal says "runs dry before the truck arrives; gap cannot be avoided". |
| **Unfair split in a crisis:** Cox's Bazar got nothing. | A plain linear optimizer gives everything to the highest scores. | Two-tier value (first 6 h worth 3×): diminishing returns spread the fuel. |
| Planner and risk used different probability windows, so before/after didn't match. | Planner used the 4 h forecast. | Both use the same 12 h window. |
| What-if accepted a route that doesn't match the station/depot. | No check. | Raises `ROUTE_MISMATCH`. |

---

### Step 6: GenAI (`genai.py`), "explain it like a colleague"

**What it does:** writes operator-friendly text. It **never** decides anything.

| Function | Output |
|---|---|
| `explain_recommendation` | 2–3 sentences: why this truck, why this route, what it does to the risk. |
| `explain_incident` | What is happening, likely cause, what it affects. |
| `briefing` | Situation report: summary, top risks, recommended actions. |
| `answer` | Investigation assistant: answers questions **only about the current network**, cites evidence (`alert:9`, `recommendation:21`), refuses off-topic questions ("capital of France?" gets "I can only answer questions about the current operations."). |

**Provider chain:** **OpenAI → Gemini (model list) → Groq (primary, fallback) → template.**
If a provider fails, it's skipped for 60 s. Answers are cached so the same question isn't paid for twice.
The LLM only sees facts from our code and is told never to invent numbers. It can only cite evidence IDs that
actually exist. Every result says `source: "llm"` or `"template"`.

**Bugs and fixes:**

| Bug | Why it happened | Fix |
|---|---|---|
| **`explain_*` crashed** (reported by Ishmam). | The backend passes dicts, and my functions expected Pydantic models. | All functions accept dicts **or** models. |
| Gemini rejected every call. | My 8 s timeout was below Gemini's minimum of 10 s. | Gemini timeout set to 12 s. |
| Groq said "model does not exist". | I hard-coded a model the key can't use. | Read model lists from `.env` (`GROQ_MODEL_PRIMARY`, `GROQ_MODEL_FALLBACK`, `GEMINI_MODEL_CHAIN`). |
| Some models wrap JSON in ```` ```json ```` fences or `<think>` blocks. | Reasoning models. | Strip them before parsing. |
| OpenAI key "missing". | The key had been pasted into `OPERATOR_KEY` in `.env`. | Moved it to `OPENAI_API_KEY`, and set `OPERATOR_KEY` back to `change-me`. |
| OpenAI call crashed with `Decompressor.decompress() got an unexpected keyword argument 'output_buffer_limit'`. | Old `brotlicffi` 1.1 package in my Python. | `python -m pip install -U "brotlicffi>=1.2"`. |
| `pip install` "worked" but the import still failed. | `pip` pointed at a different Python (3.12) than `python` (Anaconda 3.13). | Always use `python -m pip`. |
| Tests started making real LLM calls once keys were added. | Tests read `.env`. | Tests disable keys; no network in tests. |

---

### Step 7: Tests (`backend/tests/intel/`)

**62 tests**, all on real simulator data:

| File | Covers |
|---|---|
| `test_smoke.py` | Every function runs end to end. |
| `test_forecast.py` | Backtest error < 10%, band, day/night shape, spike start/end, fallbacks. |
| `test_risk.py` | Levels, probability goes down as stock goes up, outage, pending/in-transit trucks, DELAYED supply ETA. |
| `test_detect.py` | No false alarms on real data, leaks detected, z-score spike, bottlenecks, disruptions, bad input doesn't crash. |
| `test_planner.py` | Every simulator rule, fairness, backup depot, closed vs constrained depot, low stock, both fallbacks, what-if. |
| `test_genai.py` | Dict inputs, templates, provider order, failover + cooldown, cache, bad JSON, invented evidence dropped. |

Run: `cd backend; python -m pytest tests/intel -q`

---

## 3. Git bugs

| # | Bug | Why | Fix |
|---|---|---|---|
| G1 | Push to `intel` rejected (non-fast-forward). | I used `git pull --rebase origin main`. Ishmam had already merged my step 3/4 commits into `main`, and rebasing rewrote them, so my branch no longer matched GitHub. | Merged `origin/intel` into local `intel` (no force push, nothing lost). From now on: **merge** main into intel, never rebase. A local `intel-backup` branch holds the old state; it can be deleted. |

---

## 4. What Ishmam changed, and how the plan changed

**Ishmam's changes (pulled from `main`):**
1. Built the whole backend core: resilient simulator client (timeouts, retries, circuit breaker), sync engine,
   database, API, metrics, and `intel_bridge.py`, which calls my functions and falls back to his own rule-based
   policy if my code crashes.
2. **Moved the backend to port 8090** (API contract v2). Dashboard URL: `NEXT_PUBLIC_API_URL=http://localhost:8090`.
3. Added **OpenAI settings** (`OPENAI_API_KEY`, `OPENAI_MODEL`) to `.env.example` and `config.py`.
4. The organizers updated the simulator guide: our app may now call `/admin/*` for self-test scenarios.
5. Merged my `intel` branch (up to step 4) into `main`.

**His three requests to me, and what changed in my plan:**

| Request | Plan before | Plan after |
|---|---|---|
| genai must accept dicts | GenAI was step 6, "later". | Done immediately, together with the full provider chain. Step 6 finished early. |
| `stockout_prob_before` = 0 | Probability over 4 h (step 3 was "done"). | Step 3 reopened: 12 h window; planner and what-if changed to match. |
| OpenAI first | Chain was Gemini → Groq → template. | OpenAI → Gemini → Groq → template, with model lists from `.env`. |

Other plan changes during the work:
- Found by probing the real simulator: arrival timing, dispatch counting, full-depot overflow. Steps 3–5 were
  corrected to match the **real** simulator, not my assumptions.
- Branch rule added: push only to `intel`, merge (not rebase) updates from `main`.

---

## 5. Summary

**The scenario:** a simulated fuel network where stations sell fuel every 15 minutes, supply arrives at depots
on a schedule, and crises happen (demand spikes, route disruptions, station outages, delayed or reduced supply).
Our platform must keep stations stocked and show the operator what's happening and why, with a human approving
consequential actions.

**My part, the intelligence layer:**
- **Predicts** demand per station/fuel (5.1% average error vs 64.7% naive).
- **Measures risk**: hours until empty, chance of running dry in 12 h, level, when help arrives (including delays).
- **Detects problems**: shortages, abnormal demand, unexplained stock changes, bottlenecks, disruptions, with stable alert keys.
- **Plans trucks** with an optimizer that shares fairly in a crisis, never breaks a simulator rule
  (the real simulator accepted 20/20), offers alternatives, and shows risk before → after (e.g. 99% → 0%).
- **Explains** everything through OpenAI → Gemini → Groq → template, grounded in real data, never deciding quantities.
- **Never falls over**: every layer has a fallback (heuristic planner, rule-based plan, template text), and
  every fallback is visible (`mode`, `source`).
- **62 tests** on real simulator snapshots.

**Status:** steps 1–7 done and pushed to `intel`. Ishmam has merged up to step 4. Team fixes and the planner are
waiting for his merge.

**Possible next steps (optional):**
- A/B evidence for Badrul: same crisis script with vs without our plans, compare service level.
- Small prompt tweaks for the LLM text.
- Reset the local simulator (http://localhost:8000/admin) before demos; it has my test allocations in it.
