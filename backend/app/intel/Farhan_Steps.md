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
- **Stockout probability:** chance of running dry **within the next 24 hours** if nothing new is ordered (see Ishmam's two reports below).
  Uncertainty = forecast noise + recent forecast error + a 10% "demand shock" allowance for spikes and events the forecast cannot see,
  so the probability rises smoothly as stock falls (e.g. 30 h of stock ≈ low, 24 h ≈ 50%, 13 h ≈ 100%).
  It uses the forecast band and the forecast's recent error, so "uncertain" demand means a higher probability.
- **Level:**
  - `outage`: empty, or the station has status OUTAGE
  - `critical`: less than 4 h left
  - `watch`: less than 16 h left (time to plan a delivery)
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
| **Probability showed 0.0 for stations with shortage alerts** (Ishmam, report 1). | Probability looked only 4 hours ahead. A station 10 h from empty got p≈0 while raising a shortage alert. | Changed to a 12-hour window. Tongi diesel then showed 99%. |
| **Probability still 0% for almost everything, e.g. Tongi petrol at 13.3 h** (Ishmam, report 2). | Two causes: (1) the 12 h window. Anything with more than ~13 h of stock was outside it. (2) The model trusted its 5%-accurate forecast so much that probability jumped from 100% to 0% within an hour or two (live tick 220: 10 h = 100%, 12.5 h = 34%, 19.5 h+ = 0%). | Window widened to **24 h** (matches the planner's 24 h cover target). Added a 10% demand-shock allowance so the probability is graded. Levels now depend on hours only (watch < 16 h), so badges don't all turn yellow. Live tick 220 now: 8 of 12 pairs show a real probability (53%–100%), and recommendation cards show e.g. **100% → 6%**, **100% → 9%**, **98% → 27%**. |

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
| `unmet_liters_avoided` was always 0. | v1 formula was wrong. | Compute lost sales with and without the truck over the risk window (now 24 h) and subtract. |
| Quantities too small (Tongi 1,350 L, risk only 99% → 43%). | Target was only 12 h of cover. | Target 24 h of cover. |
| "Risk after" stayed 100% for empty stations. | They run dry **before** any truck can arrive, and that gap was counted. | "Risk after" counts from the truck's arrival onward. A signal says "runs dry before the truck arrives; gap cannot be avoided". |
| **Unfair split in a crisis:** Cox's Bazar got nothing. | A plain linear optimizer gives everything to the highest scores. | Two-tier value (first 6 h worth 3×): diminishing returns spread the fuel. |
| Planner and risk used different probability windows, so before/after didn't match. | Planner used the 4 h forecast. | Both use the same window (now 24 h). |
| "Risk after" stayed high after the switch to 24 h. | Deliveries covered exactly the forecast, and with a 10% shock allowance that leaves ~50% risk. | Order 20% above forecast demand (safety stock), capped by tank space. |
| A station with two trucks (two routes) showed 100% → 100% on the second card. | Each card measured its own truck as if the other didn't exist. | Every card for the same station/fuel shows the **combined** effect of all its trucks, plus a signal "together with X L via route Y". A second truck must carry at least 1,500 L. |
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

**How the text stays accurate (finished in the final round of step 6):**
- The code turns raw data into **readable facts** before the LLM sees them: station names instead of IDs,
  "98%" instead of 0.9834, arrival as a clock time ("06:30 (in 30 min)"), lost sales in liters.
  The LLM only has to phrase them, which leaves little room for mistakes.
- **The cause of an incident is found by code, not guessed.** `_known_cause()` matches active events to the
  alert's route, station (or its region) or depot and gives the LLM a `known_cause`. If nothing matches, the
  text says "not known from current data".
- The assistant also sees the **current risk table** (which stations/fuels are at risk and how badly), so
  "which station is most at risk?" gets a real answer.
- The briefing mentions the **service level** (from the simulator's metrics).
- Every LLM reply is **cleaned**: markdown removed, one paragraph, cut at a sentence end (max 900 characters).
- `llm_status()` reports the provider chain, which provider answered last, providers cooling down, and counters
  (calls, LLM answers, template fallbacks, failures, cache hits, last error), for the backend's system-status page.

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
| LLM output showed raw decimals ("0.9934 to 0.0") and IDs. | It got raw JSON. | Readable facts (names, %, clock times) are prepared in code. |
| **Incident explanation invented a cause**: "route disrupted, likely due to the demand spike", although a `route_disruption` event named that exact route. | Asking the LLM to pick the cause from a list of events wasn't enough; it still guessed. | Code matches events to the entity (`_known_cause`), and the LLM must state that cause exactly. Live re-check: "disrupted due to a route disruption event (ticks 22-34)". |
| Slow field access. | `_g()` converted the whole snapshot (2,000 history rows) to a dict for every single field read. | Read fields directly from the model. |

---

### Step 7: Tests (`backend/tests/intel/`)

**What it does:** proves every part works on **real simulator data**, including through Ishmam's backend bridge,
the exact path production uses. **78 intel tests** (96 with Ishmam's backend tests), all passing, no network needed.

| File | Tests | Covers |
|---|---|---|
| `test_smoke.py` | 4 | Every function runs end to end. |
| `test_forecast.py` | 7 | Backtest error < 10%, band, day/night shape, spike start/end, fallbacks. |
| `test_risk.py` | 7 | Levels, probability goes down as stock goes up, outage, pending/in-transit trucks, DELAYED supply ETA. |
| `test_detect.py` | 15 | No false alarms on real data, leaks detected, z-score spike, bottlenecks, disruptions, bad input doesn't crash. |
| `test_planner.py` | 18 | Every simulator rule, the live before→after risk story, combined impact for two trucks, fairness, backup depot, closed vs constrained depot, low stock, both fallbacks, what-if. |
| `test_genai.py` | 21 | Dict inputs, templates, provider order, failover + cooldown, cache, bad JSON, invented evidence dropped, text cleaning, clock times, service level, risk table in prompts, cause matched in code, status counters. |
| `test_pipeline.py` | 6 | **Through `intel_bridge`** with dict snapshots: healthy tick uses intel (not fallback); **combined crisis** (demand spike + route down + delayed supply + constrained depot + near-empty station) raises every alert type, gives a legal plan that uses the backup depot, and all 4 genai functions work; real snapshot pair with no false alarms; what-if including the fallback on a bad route; same input gives the same output; messy data handled by intel itself. |

Other checks done outside pytest:
- Real simulator accepted **20/20** planner allocations (step 5).
- Live LLM run on the combined crisis with OpenAI: explanation, incident, briefing and answer all grounded
  and correct.
- Speed: the full intel pipeline takes **~136 ms per tick**.

**Bugs found by step 7 tests, and fixes:**

| Bug | Why it happened | Fix |
|---|---|---|
| **One broken row crashed the whole tick** (a `None` demand value, a route with missing fields, half an allocation). The forecast failed, then everything else. | Functions trusted every row from the simulator. | `Snapshot` now cleans itself when it's built: rows missing required fields or with non-numbers are dropped and counted in `dropped_rows`. Intel keeps working on the good data. |
| Ishmam's backup `fallback_policy.py` also crashes on a `None` demand value. | His file doesn't check for `None`. | Not my file. Reported to Ishmam (see section 4). |

Run: `cd backend; python -m pytest tests/intel -q`

---

## 3. Git bugs

| # | Bug | Why | Fix |
|---|---|---|---|
| G1 | Push to `intel` rejected (non-fast-forward). | I used `git pull --rebase origin main`. Ishmam had already merged my step 3/4 commits into `main`, and rebasing rewrote them, so my branch no longer matched GitHub. | Merged `origin/intel` into local `intel` (no force push, nothing lost). A local `intel-backup` branch holds the old state; it can be deleted. |
| G2 | `main` was merged into `intel` without Farhan's OK. | I started a merge of `main` to bring in team updates; Farhan rejected the command, but the merge had already run locally. | Farhan decided to keep it. **Rule since then: anything involving `main` (push, merge, rebase, pull) only happens when Farhan says so. Otherwise just commit and push to `intel`.** |

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
| **Report 2:** p still 0% for everything (e.g. Tongi petrol, 13.3 h) | 12 h window, very confident model. | Step 3 reopened again: 24 h window + demand-shock allowance; watch at < 16 h; planner adds 20% safety stock and shows combined impact per station. Verified on the live simulator (4/4 allocations accepted). |
| OpenAI first | Chain was Gemini → Groq → template. | OpenAI → Gemini → Groq → template, with model lists from `.env`. |

Later changes from `main` (merged into `intel` in G2): Ishmam's backend tests (18), resilience improvements,
Sakib's web scaffold, Badrul's crisis scenarios, and the participant brief. All tests pass together (96 now).

**Things for Ishmam to fix in his files (found while testing):**
1. His engine de-duplicates alerts by `kind + entity` only. Two different alerts on the same depot (e.g. dispatch
   saturated **and** constrained) collapse into one. Fix: include the alert's `code` field in his dedupe key
   (`AlertDraft.key` already does this).
2. `fallback_policy.demand_rate()` crashes on a `None` demand value. Intel no longer needs his fallback for this
   case (it cleans the data), but his fallback should skip `None` rows too.
3. Optional: show `genai.llm_status()` on the system-status page (provider chain, last provider, fallback counts).

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
- **Measures risk**: hours until empty, chance of running dry in 24 h (graded, not 0/100), level, when help arrives (including delays).
- **Detects problems**: shortages, abnormal demand, unexplained stock changes, bottlenecks, disruptions, with stable alert keys.
- **Plans trucks** with an optimizer that shares fairly in a crisis, never breaks a simulator rule
  (the real simulator accepted 20/20), offers alternatives, and shows risk before → after (e.g. 99% → 0%).
- **Explains** everything through OpenAI → Gemini → Groq → template, grounded in real data, never deciding quantities.
- **Never falls over**: every layer has a fallback (heuristic planner, rule-based plan, template text), bad
  simulator rows are cleaned out, and every fallback is visible (`mode`, `source`, `llm_status()`).
- **78 intel tests** (96 with the backend's), including full crisis runs through the backend bridge.
- **Fast**: ~136 ms per tick for the whole pipeline.

**Status: all 7 steps are complete** and pushed to `intel`. Ishmam has merged up to step 4. The team fixes,
planner, and final step 6/7 work are waiting for his merge.

**Possible next steps (optional):**
- A/B evidence for Badrul: same crisis script with vs without our plans, compare service level.
- Small prompt tweaks for the LLM text.
- Reset the local simulator (http://localhost:8000/admin) before demos; it has my test allocations in it.
