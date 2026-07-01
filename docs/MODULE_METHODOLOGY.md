# Per-Module Health Methodology — dashboards, fields & algorithms

> **Audience:** anyone who wants to know *exactly how each module decides health* — which
> Grafana dashboards/panels it reads, which fields matter and why, and how those fields
> become the score. This is the consolidated reference; each module's own `README.md` is
> the long form, and [`methodology.md`](notebook/methodology.md) is the shared philosophy
> (esp. **§12** audit invariants). Panel↔module mapping (and excluded dashboards):
> [`module_dashboard_mapping.md`](mapping/module_dashboard_mapping.md).

## Shared model (applies to every module)

- **Health = penalty model:** `health = clamp(100 − Σ (weightᵢ · penaltyᵢ, capped), 0, 100)`.
  Each signal's penalty is capped so no single one dominates.
- **Tiers:** `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`. **Module tile = worst
  component tier.**
- **Signals are normalised** (rates/ratios/robust z-scores), never raw counts.
- **Regime & RUL:** `coldstart` (little history → coarse tier-band TTM, low confidence) →
  `trend` (≥ ~5 snapshots → fit the health trajectory, project threshold-crossing → sharper
  TTM, higher confidence). **Confidence tracks data sufficiency, not signal magnitude.**
- **Robust peer z-score:** median + MAD (falls back to std, then 0 when there's no spread),
  so a single-component or all-identical population never produces a spurious z.
- Tunables (weights, caps, thresholds, catalogs) live in each module's **`module.yaml`**.

Weights below are `{weight, cap}` = points removed per unit of the signal, capped.

---

## 1. Lift — `modules/lift/`
**Component:** each ASRS lift (`aisle_NN_<inbound|outbound>_lift_NN`).

| Role | Dashboard (uid) | Panel | Fields used | Why |
|------|-----------------|-------|-------------|-----|
| Primary | Lift Error History (`wQds52G4z`) | #2 | `lift_id, error_code, error_desc, created_time` | Per-lift fault events → rate/severity/recurrence. |
| Secondary | Bad Tracker Diagnosis (`VAW2nmqIz`) | #2 | `lift_id, lift Status Description` | Current ERROR state + recurrence. |
| Context | Lift Error Analysis (`EqDhnQ9Sz`) | #2 | `Aisle, Front/Back Inbound/Outbound Lift` | Per-position task counts (load proxy; not scored). |

**Fields → features:** `error_rate_per_day` (count ÷ window days), `rate_peer_z` (robust z
of that rate vs all lifts), `severity_mean` and `mechanical_share` (from the `error_catalog`
severity/category per `error_code`), `recurrence_max` (top same-code repeats), `distinct_codes`,
`current_error_status` (from Bad Tracker), inter-fault gaps (context, shown in RCA).

**Penalties:** `rate_peer_z {9,40}`, `abs_rate {2,20}`, `severity {30,30}`,
`mechanical {22,22}`, `recurrence {1.5,18}`, `diversity {2,12}`, `current_error {12,12}`.
`severity` & `mechanical` are **volume-gated** by fault count (≥5 for full weight) so a
single stale error can't force WARN. **RUL:** time-based health-slope trend; coldstart
bands {critical 24 h, warn 96 h, watch 336 h}. **RCA:** ranks contributors, names the
dominant error code + description; cross-flags **network** when ≥20 % of errors are
communication-class.

---

## 2. Shuttle — `modules/shuttle/`
**Component:** each shuttle (`QD_Shuttle_<aisle>_<unit>`, 124). Cycle-bearing → **cycles-based RUL**.

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary | QUADRON ERROR HISTORY (`K2QzauWVz`) | #2 | `shuttle_id, error_type, error_desc, created_time` | FORK/TELESCOPIC faults. |
| Primary | QUADRON CYCLES (`8dDcXomVz`) | #2 | `shuttle_id, PUTAWAY, PICKING, RESHUFFLING` | Usage → errors/Mcycle + RUL basis. |
| Secondary | Daily Shuttle Errors (`N8QvGxQIk`) | #2 | `error_desc, Value` | Current per-shuttle counts (today). |
| Secondary | Bad Tracker (`VAW2nmqIz`) | #2 | `shuttle_id, shuttle Status Description` | Current pick-error state. |
| Secondary | Quadron Alerts (`VxY5Zls7z`) | #2 | `message` | Current active-alert flag. |

**Fields → features:** `errors_per_mcycle = errors ÷ total_cycles × 1e6` (**None** if the
shuttle has no cycle row — no fabricated rate, no fleet-median pollution), `epc_peer_z`,
`severity_mean`, `mechanical_share`, `recurrence_max`, `distinct_types`, `reshuffle_excess`
(reshuffle share above fleet median), `current_daily_excess` (today's errors **beyond** the
window count — avoids double-counting), `current_pick_error` (binary), `current_alert`.

**Penalties:** `epc_peer_z {6,36}`, `epc_abs {0.02,18}`, `severity {28,28}`,
`mechanical {20,20}`, `recurrence {1.5,16}`, `diversity {2,10}`, `reshuffle_excess {18,8}`,
`current_badtracker {12,12}` (binary pick-error state), `current_alert {8,8}`,
`current_daily {3,9}` (excess only). **RUL:** health-vs-**cumulative-cycles** slope →
cycles-to-threshold ÷ cycle-accrual rate → hours; **falls back to a time-based slope** when
cumulative cycles are static (frozen data). **RCA:** dominant error_type+desc; cross-flags
**network** (servo/drive faults) and **tracker** (pick errors).

---

## 3. Conveyor — `modules/conveyor/`
**Component:** each GTP conveyor zone (6). No fault log → **congestion + stall**.

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary | Conveyor Zone Count (`lavIciTDk`) | per-zone timeseries | `time, Conveyor Actual/Limit, Buffer Actual/Limit` | Queue-vs-limit congestion + buffer fill. |
| Secondary | GTP (HOLD, TRANSIT) (`C8jMvAcIk`) | #2/#4 | on-hold / in-transit counts | Module flow-stress context. |

**Fields → features:** `congestion = actual ÷ limit` → `congestion_mean`, `congestion_peak`,
`congestion_p90`, `severe_saturation_share` (share ≥ 1.5), `buffer_congestion_mean`,
`idle_share` (fraction of samples at zero throughput), `idle_peer_z` (robust z of idleness
vs peer zones), `congestion_peer_z`.

**Penalties:** `congestion_excess {40,35}` (mean above 1.0), `severe_saturation {30,25}`,
`peak_excess {15,15}`, `buffer_congestion {25,18}`, `congestion_peer_z {6,18}`,
`sustained_congestion {12,12}` (p90 above 1.0), `stall_idle {100,55}`. **Stall detection:**
`stall_idle` fires on **peer-anomalous idleness** (a zone idle while peers flow — a seized
belt has zero congestion and would otherwise score 100), and is gated so a plant-wide quiet
period yields **no** false flag. **RCA** names the dominant symptom (stall / buffer / peak /
saturation / sustained). Cross-flag **outbound/buffer** when buffers fill.

---

## 4. Tracker / Position-Sensor — `modules/tracker/`
**Component:** each grid **location** (`aisle_NN_bt_NN`) exhibiting bad-tracker events (dynamic set).

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary | Bad Tracker Diagnosis (`VAW2nmqIz`) | #2 | `tracker, container, location, created_time, shuttle_id, task_type, status, lift_id, *Status Description*` | Mislocated totes clustering on a location. |

**Fields → features:** component keyed on **`location`** (not the per-tote `tracker` tag,
which never recurs). `bad_count` (totes stuck here), `recent_bad_count` (newer than the
active window), `recurrence_runs` (prior runs this location was bad — from the store),
`distinct_shuttles`, `dominant_shuttle_share` (÷ **shuttle-attributed** rows), `lift_error_count`,
`pick_error_count`, `bad_count_peer_z`.

**Penalties:** `cluster {8,34}` on **stale** totes (`bad_count − recent_bad_count`, disjoint
from recent), `recent_cluster {9,30}`, `recurrence {7,30}`, `multi_shuttle {5,15}`,
`lift_involved {6,12}`, `peer_z {5,12}`. Splitting stale/recent + a modest peer-z cap avoids
triple-counting one cluster. **RCA** names the cluster/recurrence story; cross-flags
**shuttle** when one shuttle owns ≥60 % of a location's mislocations (possible NOT_AT_CENTRE)
and **lift** on a lift-ERROR row.

---

## 5. Gate / Door-Actuator — `modules/gate/`
**Component:** each gate (`aisle_NN_level_NN_<FG|RG>`, 52). Current-state + latency + persistence.

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary | Quadron-gate-status (`5gFdGgwnz`) | #2 | `id, status (1=CLOSED/2=OPEN REQ/3=OPEN), aisle` | Current open/close state. |
| Secondary | Quadron Alerts (`VxY5Zls7z`) | #2 | `message` (`… front_gate|rear_gate open/opened for N minutes`) | Response-latency (minutes stuck non-closed). |

**Fields → features:** `status_code`/`is_non_closed`, `stuck_excess_minutes` (minutes stuck
beyond a 2-min grace, from Alerts), `non_closed_rate` & `stuck_rate` (fractions of prior
runs — from the store, needs ≥3 runs), `consecutive_non_closed` (persistence),
`aisle_non_closed_count` (common-cause), `peer_z` (rate vs peer gates).

**Penalties:** `stuck_latency {3,62}` (per minute; ~7 min→watch, ~14→warn, ~23→critical),
`open_request {8,8}`, `persistence {12,36}`, `stuck_recurrence {40,20}` (a **rate**, decays on
recovery), `non_closed_rate {35,22}`, `peer_z {5,18}`. **Confidence** in coldstart tracks
prior-run depth (a loud single reading stays low-confidence). **RCA** leads with an
**aisle-wide common cause** when ≥3 gates on an aisle are non-closed → cross-flags **network**
(zone-controller/comms).

---

## 6. Bin / Tote-Mechanical — `modules/bin_mech/`
**Component:** each bin slot **location** currently blocked (dynamic set).

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary | Bin blocked / tote-tilted (`GOqISik4k`) | #2 | `tracker, aisle, zone, level, location, container, blockedTime` | Current blocked slots (deduped to one row per blocked tote). |
| Secondary | Bin Block History (`hIVZMtGVz`) | #2 | `source` (bin-format) | Frozen historical block frequency → chronic-slot prior. |

**Fields → features:** `current_block_count` (totes at the slot, after partition dedup),
`block_age_hours` (**anchored to the run time**, not `max(blockedTime)`, so a systemic
backlog is caught), `historical_block_count` (chronic prior), `recurrence_runs` (store),
`peer_z` of block-age (**gated** by a 6 h absolute floor so fresh blocks aren't flagged),
`aisle_is_outlier`.

**Penalties:** `blocked_base {10,10}`, `block_age {2,35}`, `cluster {12,24}`,
`historical {0.4,12}` (enrichment prior, not a tier driver), `recurrence {8,40}`,
`peer_z {4,14}`. **RCA** names block-age + chronic + persistence; cross-flags **shuttle**/
**tracker** when blocks concentrate on one aisle. *(Note: the history SQL only covers aisles
001–005; the aisle-06 gap is logged.)*

---

## 7. GTP Station + Scanner — `modules/gtp_station/`
**Dual-entity:** 263 barcode **scanners** + 63 pick **stations** (`GS001..GS063`).

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary (scanner) | GTP Scanner logs (`pK7-8NmVz`) | #8 | `scanner, ReadCount, NoReadCount, efficiency_percentage` | Per-scanner **misread rate**. |
| Secondary (volume) | GTP Scanner logs | #4 | `scanner, hits` | Volume gate. |
| Primary (station) | Discrepancy Report Events (`D6sQle2Vz`) | #2 | `station, operation_type, type, discrepancy_type, create_time` | Per-station **pick-discrepancy rate**. |
| Roster (station) | GTP Stations (`GlGBwgY4z`) | #2 | `id, Type, operation_type, active_status, updated_on` | 63-station roster + status. |

**Scanner:** `misread_rate = NoRead ÷ (Read + NoRead)`, **volume-gated** (noisy low-scan
devices suppressed), + peer-z (gated by a minimum misread %) + recurrence + trend. **Station:**
pick-discrepancy **rate** with **peer deviation dominant** (isolates a station-specific
problem from plant-wide inventory shorts) + recurrence/trend + a low-weight offline-persistence
capped at `watch`. The 9 decant/compaction scan devices are **excluded** here (owned by Module 8).
**RCA** cross-links a `GS<NN>-SL<NN>` slot scanner to its station.

---

## 8. Decanting Station + Scanner — `modules/decant_station/`
**Dual-entity:** 9 decant/compaction **scanners** + 10 decant **stations** (`DS001..DS010`).

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary (scanner) | GTP Scanner logs (`pK7-8NmVz`) | #8 (filtered to 9 devices) | `scanner, ReadCount, NoReadCount` | Misread rate. **Shared** panel with Module 7. |
| Roster (station) | Decanting station report (`B4i1-HpVz`) | #2 | `station_id, active_status, user_id` | 10-station roster + status. |
| Throughput | StationWise Decanted Cartons (`n1oZnY_Vz`) | #2 | `station_id, carton_count` | Idle-while-active + utilisation. |

**Scanner:** misread rate (volume-gated + peer-z + **volume-gated recurrence**) — the strong
live signal. **Station:** **no live discrepancy feed exists**, so a station is scored coarsely
on **status** (`is_active` is **tri-state** — `None` for Unknown, never treated as offline) +
offline/idle-while-active **persistence** across runs, at low confidence. The store is what
makes the station entity predictive (a single run scores every station `ok`).

---

## 9. Network / Comms — `modules/network/`
**Component:** each shuttle's **comms link** (`network_link` keyed by `shuttle_id`, 124).

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary (windowed) | Quadron Network status (`gL0OBnq7z`) | #4 | per-shuttle `uptime%` since window start | **downtime% = 100 − uptime%**. |
| Secondary (recency) | Quadron Network status | #2 | per-shuttle `uptime%` today | Today-vs-window spike. |

**Fields → features:** `downtime_pct` and `today_downtime_pct` — both **clamped to [0,100]**
(panel #2's seconds-since-midnight denominator can otherwise report >100 %), `today_delta_pct`
(recency spike), `downtime_peer_z` (gated by a minimum absolute downtime), downtime-specific
`recurrence`, trend.

**Health:** peer deviation + absolute downtime rate + recency spike + recurrence/trend. It's a
**different error subset** than the Shuttle module's mechanical faults, so scoring it does
**not** double-count. **Cross-feature:** a degrading link cross-flags the **Shuttle** it serves;
an aisle downtime cluster cross-flags **meta** (aisle AP/controller).

---

## 10. Controller / Compute — `modules/controller/`
**Component:** the controller compute node(s) (`db_controller`; scales to N via a host column).

| Role | Dashboard (uid) | Panel | Fields | Why |
|------|-----------------|-------|--------|-----|
| Primary | CPU Stats (`CwTEp_GSz`) | #17 (`EXEC getCPUDetails`) | `cpu_idle, cpu_sql` | **utilisation% = 100 − cpu_idle**; SQL share as context. |

**Fields → features:** `utilization_pct` (the `cpu_idle` column is **required** — if absent,
the module scores nothing rather than a false 100 %), `sql_share` (clamped ≤ 1),
`consecutive_high` (from the store). **Current-state snapshot** (identical across windows), so
the **store** provides sustained-high + trend RUL. **Penalties:** saturation above a floor +
sustained-high + trend. **Confidence** tracks store depth, not CPU magnitude. **Cross-feature:**
a saturated controller starves the WES → a system-wide throttle cross-flag to **meta**.

---

## 11. System-Wide Anomaly (Meta) — `modules/meta/`
**Component:** an `incident_scope` — the observed ASRS **aisles** (dynamic) + one **`system`** scope.
**No Grafana fetch** — it reads the **store**.

| Role | Source | Reads | Why |
|------|--------|-------|-----|
| Primary | `component_health` (the store) | latest verdict per `(module, component_id)` (excl. meta) + `rca.cross_module_flags` + `metrics.aisle` | Correlate the other modules into compound incidents. |

**Fields → features (per scope):** `breadth` (distinct flagged modules), `worst_flagged_tier`,
`chain_edges` (a flagged member whose cross-flag names another **flagged** module in the same
scope = a realized causal chain), `has_meta_flag` (an explicit `→ meta` escalation),
`flagged_members`; (system) `controller_tier`, `compound_aisle_count`.

**Penalties (compound-risk, not a re-tally):** `breadth {9,45}` (keeps breadth 2..6 distinct),
`severity` by worst tier (**only when breadth ≥ 2**), `chain {8,24}`, `persistence {6,24}`,
`meta_flag {18,18}` (surfaces a coordinated cross-unit pattern as ≥ watch even at breadth 1);
system-only: `controller_trigger` (by tier) + `aisle_breadth {10/aisle, cap 40}`. **Anti-double-
count:** a lone flagged module leaves its aisle `ok` (unless it raised a `→ meta` escalation);
meta only escalates on co-occurrence, hardest with a realized chain. **RCA** names the compound
pattern (e.g. *"Compound incident on aisle_01: 3 subsystems degraded … realized chain
network→shuttle"*) and lists each involved module for drill-down.

---

## Cross-module signal graph (how modules inform each other)

- **network → shuttle** (comms drops precede pick errors) · **network → meta** (aisle cluster)
- **controller → meta** (system-wide throttle)
- **tracker → shuttle / lift** (a dominant robot at a bad location)
- **gate → network** (aisle-wide non-closed = zone controller/comms)
- **bin → shuttle / tracker** (blocks concentrated on one aisle)
- **shuttle → network / tracker** · **lift → network** (communication-class errors)

The **Meta** module consumes these flags to turn correlated single-module verdicts into one
ranked compound incident with a likely common cause — the payoff of scoring every subsystem in
one consistent methodology.
