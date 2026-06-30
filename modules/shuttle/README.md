# SHUTTLE module — the Shuttle PdM chapter

Predictive maintenance for the ASRS **shuttles** — rotating, high-cycle assets with
telescopic forks (see `docs/notebook/01_intro_to_asrs.md` §1.3). Unlike the lift, the
shuttle exposes **cycle counts**, so faults are normalised by usage and a
**cycles-based remaining-useful-life (RUL)** becomes possible.

This chapter documents the resolved sources, every feature/formula, and — per the
project requirement — **exactly how each shuttle's verdict and the module's overall
status are reached**. Tunables live in [`module.yaml`](module.yaml); pipeline is
`fetch.py → features.py → health.py` (calls `rca.py`); it self-registers in `__init__.py`.

> **Roster note.** The cycle data lists **124 shuttle units** (`QD_Shuttle_<aisle>_<unit>`),
> richer than Chapter 1's simplified "one shuttle per aisle". The model treats every
> unit in QUADRON CYCLES as a component, so the roster comes from the data, not the prose.

---

## 1. Data sources (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary** | QUADRON ERROR HISTORY (`K2QzauWVz`) | `#2` | `shuttle_id, error_type, error_desc, created_time` | Per-shuttle fault events (FORK/TELESCOPIC dominate). |
| **Primary** | QUADRON CYCLES (`8dDcXomVz`) | `#2` | `shuttle_id, PUTAWAY, PICKING, RESHUFFLING` | Cumulative cycles = usage/wear; the RUL basis. |
| Secondary | Daily Shuttle Errors (`N8QvGxQIk`) | `#2` | `error_desc, Value` | Current aggregated errors (`shuttle (n)` parsed). |
| Secondary | Bad Tracker (`VAW2nmqIz`) | `#2` | `shuttle_id, shuttle Status Description` | Current recurrence + `SHUTTLE_PICK_ERROR`. |
| Secondary | Quadron Alerts (`VxY5Zls7z`) | `#2` | `message` | Current free-text alerts (shuttle mentions parsed). |

Observed errors are **frozen/historical** (2023-08-11; 4 shuttles, mostly FORK_ERROR);
cycles are cumulative for 124 shuttles. The error window anchors to
`as_of = max(created_time)` for live/frozen parity.

## 2. Features (`features.py`)

Per shuttle over the window `[as_of − window, as_of]`. `n` = error count, cycles from
QUADRON CYCLES.

| Feature | Formula | Meaning |
|---------|---------|---------|
| `total_cycles` | `PUTAWAY + PICKING + RESHUFFLING` | Cumulative usage. |
| `reshuffle_share` | `RESHUFFLING / total_cycles` | Reshuffle load (deep-2 access / inefficiency). |
| `error_count` | `n` | Faults in window. |
| **`errors_per_mcycle`** | `n / total_cycles × 1e6` | **Usage-normalised fault rate — primary signal.** |
| `severity_mean` | `mean(severity(error_type, error_desc))` | Fault seriousness (0–1). |
| `mechanical_share` | mechanical-wear errors / `n` | Fork/telescope physical-wear fraction. |
| `recurrence_max` | max repeats of one `error_desc` | Same fault recurring. |
| `distinct_types` | unique `error_type` | Fault-type breadth. |
| `median_gap_hours` | median inter-fault gap | MTBF proxy. |
| `reshuffle_excess` | `max(reshuffle_share − fleet_median, 0)` | Reshuffle load above peers. |
| `epc_peer_z` | robust z of `errors_per_mcycle` vs fleet | Peer deviation (MAD, std fallback). |
| `current_daily_errors` / `bad_tracker_events` / `current_pick_error` / `current_alert` | parsed counts/flags | Live status. |

Severity vocabulary (`module.yaml`): `FORK_ERROR` → mechanical_wear 0.90; `TELESCOPIC_ERROR`
→ mechanical 0.80; `error_desc` keyword overrides (`SERVO_DRIVE`→drive 0.90, `SENSOR`/`DETECTION`→sensor 0.60,
`NOT_AT_CENTRE`→positioning 0.65, `FORK`→mechanical_wear 0.90).

## 3. How a single shuttle's status is reached (`health.py`)

A penalty model: **start at 100, subtract capped penalties**, then map to a tier.

```
health = clamp(100 − Σ penaltyᵢ , 0, 100)        penaltyᵢ = min(valueᵢ · weightᵢ, capᵢ)
```

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `epc_peer_z` | errors/Mcycle vs fleet (robust z) | 6.0 · 36 |
| `epc_abs` | absolute errors/Mcycle | 0.02 · 18 |
| `severity` | mean severity | 28 · 28 |
| `mechanical` | mechanical-wear share | 20 · 20 |
| `recurrence` | `max(recurrence_max−2,0)` | 1.5 · 16 |
| `diversity` | `max(distinct_types−2,0)` | 2.0 · 10 |
| `reshuffle_excess` | reshuffle load above fleet | 18 · 8 |
| `current_badtracker` | bad-tracker events | 4.0 · 16 |
| `current_alert` | named in an active alert | 8 · 8 |
| `current_daily` | errors reported today | 3 · 9 |

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`.

**Time-to-maintenance + regime:**
- **`coldstart`** (history < 5 snapshots): coarse band by tier — critical 48 h, warn 240 h,
  watch 720 h, ok none. Confidence `coldstart_base(0.4) + 0.25·data_factor + 0.15·cycles_known (+0.1 if history)`.
- **`trend`** (≥ 5 snapshots): **cycles-based RUL** — fit `health` vs cumulative cycles to get
  `cycles_to_critical = (health − 40) / |slope|`, then convert to hours with the recent
  cycle-accrual rate (`Δcycles/Δhours` fitted across snapshots):
  `ttm_hours = cycles_to_critical / cycle_accrual_rate`. Both `predicted_ttm_cycles` and
  `predicted_ttm_hours` are stored. Confidence rises with history depth + data sufficiency.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by the points each penalty removed; `primary_cause` names the
dominant fault (`error_desc (error_type)`), or the live state (active alert / pick errors).
The payload carries the dominant error, error mix, `errors_per_mcycle`, `total_cycles`,
`reshuffle_share`, and **cross-module flags** (servo-drive → Network; persistent pick
errors / bad-tracker → Tracker).

## 5. How the overall module status is reached

The **Shuttle PdM** tile (overview page) shows the **worst risk tier among all 124
shuttles** (critical > warn > watch > ok), the count of shuttles in each tier, and the
last-run time. One critical shuttle makes the module read *critical* — surfacing the most
urgent unit first — while the per-shuttle table shows the full fleet, sorted worst-first.
This rollup is identical for every module (documented once in `core/registry.py`).

## 6. Validation (this session)

A `now-365d` run scored **124 shuttles**: `QD_Shuttle_03_06` and `_03_13` → health 0 /
critical (FORK_ERROR, ~1,580 and ~1,435 errors/Mcycle, peer-z ≈ 8, recurrence 22, mechanical
share 1.0); 14 watch (current alerts / pick-errors); 107 ok. Cold-start regime labelled with
confidence scaled by data sufficiency + cycle knowledge. See `/module/shuttle` (with its
in-page Methodology section).

## 7. Running it

- Dashboard: `/module/shuttle` → pick a window → **Run shuttle now**.
- API: `POST /api/run {"module":"shuttle","window":"now-30d"}`.
- Automation: enable the `shuttle` (or `global`) scope on the Automation page.

## 8. Future enrichment

Quadron Alerts also exposes buffer/lane/outbound panels (a future Buffer/Outbound module).
As automation accumulates run history, the cycles-based **trend** RUL activates automatically —
no code change — sharpening the per-shuttle time-to-maintenance.
