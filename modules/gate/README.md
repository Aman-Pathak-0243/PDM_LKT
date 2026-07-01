# GATE / Door-Actuator module — the Gate PdM chapter

Predictive maintenance for the ASRS **Quadron gates** — the door actuators that open and
close to let totes through at each aisle level (one **front gate** and one **rear gate**
per aisle+level). Unlike Lift (time) and Shuttle (cycles), a gate exposes only its
**current open/close state**, so this is a **current-state + latency + recurrence** module:
a healthy gate rests CLOSED and opens only briefly; a degrading **actuator** gets caught or
stuck **non-closed** — either in *OPEN REQUEST INITIATED* (it was told to open but can't
complete) or stuck *OPEN* (it won't return to closed) — with a growing **response latency**
(minutes stuck) that recurs and persists across runs.

This chapter documents the resolved sources, every feature/formula, and — per the project
requirement — **exactly how each gate's verdict and the module's overall status are
reached**. Tunables live in [`module.yaml`](module.yaml); the pipeline is
`fetch.py → features.py → health.py` (which calls `rca.py`); it self-registers in
`__init__.py`. The data is **live/current** (not frozen).

> **Mapping correction (Session 5).** The mapping (§3) listed **QUADRON ERROR HISTORY** as
> the Gate secondary ("Gate-related error codes"). Live SQL re-confirms it is
> **`shuttle_error` only** (`shuttle_id, error_type, error_desc`; 94 rows, **no gate/id
> column**) — it is the Shuttle module's primary and carries no gate signal, so it is
> **dropped as a gate source**. This is the same class of mapping error the kickoff warned
> about, caught by re-verifying every candidate by live inspection.

---

## 1. Data sources (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary** | Quadron-gate-status (`5gFdGgwnz`) | `#2` "Gate status" | `id, status, aisle` | Current state of **all 52 gates** (the roster + component universe). |
| Context | Quadron-gate-status | `#4` "OPEN/REQUESTED gate's" | `id, status` | Currently open / open-request-initiated subset (`status 2..3`) — integrity cross-check of #2's non-closed set. |
| Secondary (latency) | Quadron Alerts (`VxY5Zls7z`) | `#2` "Quadron Alerts" | `message` | Per-gate **stuck-minutes** parsed from `… front_gate|rear_gate open initiated|opened for N minutes` (from `gate.updated_timestamp`). |

**Component universe:** **52 gates**, id format `aisle_<NN>_level_<NN>_<FG|RG>` (26 front-gates
+ 26 rear-gates; aisles 1–4 have 4 levels, aisles 5–6 have 5 → 8+8+8+8+10+10 = 52). Every
gate is scored each run (a **fixed roster**, unlike the tracker's dynamic anomaly set).

**Status enum** (`gate.status`, from the panel `CASE`): `1 = CLOSED`, `2 = OPEN REQUEST
INITIATED`, `3 = OPEN`. **Current-state panel:** `#2` returns the same **52 rows at `now-2d`
and `now-90d`** — the dashboard window does **not** filter it. The 2-day-retention limit is
overcome by **our store**: each PdM run snapshots gate state, so **stuck-persistence** and
**non-closed recurrence** accrue across runs (CLAUDE.md §6). The `window` is nominal here
(it drives the fetch time range, not a server-side filter).

**Latency source.** `#2`/`#4` project no timestamp, so within-snapshot latency is read from
**Quadron Alerts #2**, whose subquery emits — for every `gate where status > 1` — a message
`"<id[:18]> front_gate|rear_gate open initiated|opened for DATEDIFF(MINUTE, updated_timestamp,
GETDATE()) minutes"`. We reconstruct the gate id (`prefix + FG/RG`) and read the minutes.
This panel is **shared with the Shuttle module** (which reads its shuttle alerts); Gate parses
only the `front_gate`/`rear_gate` messages (CLAUDE.md §7 cross-module reuse).

## 2. Features (`features.py`)

Per gate over the current snapshot. `grace = stuck_grace_minutes` (default 2).

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `status_code` | 1/2/3 from status text (None if unmapped) | Current open/close state. |
| `is_open_request` | `status_code == 2` | **Caught mid-actuation** (open issued, not reached OPEN). |
| `is_open` | `status_code == 3` | Gate currently open (normal if brief). |
| `is_non_closed` | `status_code ∈ {2,3}` | Not at rest — the anomaly candidate. |
| `stuck_minutes` | parsed from Quadron Alerts (0 if closed / no alert) | **Response latency** — minutes stuck non-closed. |
| `stuck_excess_minutes` | `max(stuck_minutes − grace, 0)` | Latency beyond normal operation — the penalised part. |
| `aisle` / `level` / `face` | parsed from the gate id | Location + front/rear. |
| `aisle_non_closed_count` | non-closed gates on this gate's aisle | Common-cause context (drives the cross-module flag). |
| `system_non_closed_count` | non-closed gates system-wide | Snapshot context. |
| `non_closed_rate` | *(health.py)* prior runs non-closed / runs observed | **Longitudinal open-often rate.** |
| `consecutive_non_closed` | *(health.py)* consecutive most-recent runs (incl. now) non-closed | **Stuck persistence — not returning to CLOSED.** |
| `prior_stuck` | *(health.py)* prior runs with `stuck_excess > 0` | Repeated actuator hesitation. |
| `non_closed_rate_peer_z` | *(health.py)* robust z of `non_closed_rate` vs peer gates | Peer deviation (MAD, std fallback). |

## 3. How a single gate's status is reached (`health.py`)

Two-pass penalty model: pass 1 reads each gate's history to compute the longitudinal stats
(and the peer baseline of `non_closed_rate`); pass 2 scores. `health = clamp(100 − Σ penaltyᵢ,
0, 100)`, `penaltyᵢ = min(valueᵢ·weightᵢ, capᵢ)`.

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `stuck_latency` | `stuck_excess_minutes` (minutes stuck beyond grace) | 3.0 · 62 |
| `open_request` | caught in OPEN REQUEST INITIATED (flat) | 8.0 · 8 |
| `persistence` | `max(consecutive_non_closed − 1, 0)` | 12.0 · 36 |
| `stuck_recurrence` | `prior_stuck` (prior runs stuck) | 6.0 · 24 |
| `non_closed_rate` | `non_closed_rate` (0–1) — *only after ≥ `min_runs_for_rate` (3) runs* | 35.0 · 22 |
| `peer_z` | `non_closed_rate_peer_z` — *only after ≥ 3 runs* | 5.0 · 18 |

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`. The
latency calibration means a **single** stuck reading reaches watch at ~7 min, warn at ~15 min,
and critical at ~22 min stuck; shorter sticking that **persists or recurs** across runs
escalates via `persistence`/`stuck_recurrence`. A gate that is merely OPEN briefly (0-min
latency) scores 100 — being in use is not a fault. The longitudinal `non_closed_rate`/`peer_z`
penalties stay dormant until ≥3 runs of history exist (honest cold-start).

**Time-to-maintenance + regime:** no cycle counter and a current-state panel, so RUL is
time/recurrence-based — **cold-start** uses a coarse band by tier (critical 48 h, warn 240 h,
watch 720 h); **trend** (≥ 5 runs) fits the gate's `health_score` trajectory over time and
projects when it crosses the critical line (capped at 1 year). Cold-start confidence rises
with stuck-minutes evidence and any history; trend confidence rises with history depth.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by points removed; `primary_cause` names the dominant symptom
("Stuck OPEN REQUEST INITIATED for N min — actuator not completing", "Non-closed across K
consecutive runs — not returning to CLOSED", "Repeatedly stuck across N prior runs",
"Non-closed in X% of runs — elevated vs peer gates", or the healthy states "Gate resting
CLOSED" / "Gate OPEN (in use) — no stuck signal"). **Cross-module flag:** when **≥ 3 gates on
one aisle** are non-closed at once, the RCA flags a possible **zone-controller / comms common
cause** (a candidate for the future Network / Controller module) rather than blaming each
actuator alone.

## 5. How the overall module status is reached

The **Gate / Door-Actuator PdM** tile shows the **worst risk tier among all 52 gates**
(critical > warn > watch > ok), the per-tier counts, and the last-run time; the per-gate table
(sorted worst-first) shows the full picture. Identical rollup for every module
(`core/registry.py`).

## 6. Validation (this session)

Two `now-2d` runs on **live data** scored all **52 gates**. The plant was healthy both runs
(gates rest CLOSED and open only briefly), so every gate read **ok** — the honest result when
nothing is degrading. The model's discrimination was proven two ways:

- **Cross-run persistence, live:** `aisle_06_level_04_RG` was OPEN in run 1 and **still
  non-closed in run 2** → `consecutive_non_closed = 2` → health **100 → 88**, primary cause
  *"Non-closed across 2 consecutive runs — not returning to CLOSED."* This is the store-driven
  persistence signal activating on real data. (Panel #4 returned exactly the non-closed gates
  each run — an integrity cross-check.)
- **Synthetic degradation:** a gate stuck in *OPEN REQUEST INITIATED* for 22 min with a
  6-run stuck history scored **health 0 / critical / trend regime**, with the aisle-wide
  cross-module flag; an 8-min stuck-open gate → **watch**; a non-gate alert row was correctly
  ignored. (`scripts/analyze_gate_primary.py` + the offline logic check.)

See `/module/gate` (with its in-page Methodology section) and `data/inspection/s5_gate.png`.

## 7. Running it

- Dashboard: `/module/gate` → pick a window → **Run gate now**.
- API: `POST /api/run {"module":"gate","window":"now-2d"}`.
- Automation: enable the `gate` (or `global`) scope on the Automation page — because the
  panel is current-state, **regular automation is what makes this module predictive**:
  persistence/recurrence only accrue if gate state is sampled repeatedly.

## 8. Future enrichment

- If a **gate command/latency history** feed (per-open duration, cycle count) is exposed, it
  would turn the response-latency signal into a server-side timeseries (sharper than parsing
  Alerts) and enable a cycles-based RUL like the Shuttle module.
- The aisle-wide cross-module flag becomes a live edge to the **Network / Controller** module
  once that exists (compound-failure detection, mapping §9–§11).
- As automation accumulates runs, the **trend** RUL and `non_closed_rate`/`peer_z` penalties
  activate automatically — no code change — sharpening each gate's time-to-maintenance.


---

> **Audit hardening (Session 12 — 2026-07-01).** Cold-start `confidence` now tracks **data sufficiency** (prior runs), not the current reading's magnitude. `stuck_recurrence` converted from a raw count to a decaying **rate**. RCA distinguishes peer-deviation from own-history rate and **leads with an aisle-wide common cause** when ≥3 gates on an aisle are non-closed. Latency calibration comment corrected; unparsed-id aisle fallback zero-pads; `polyfit` guarded. See `docs/AUDIT_REPORT.md` and `docs/notebook/methodology.md §12` for the cross-cutting invariants.
