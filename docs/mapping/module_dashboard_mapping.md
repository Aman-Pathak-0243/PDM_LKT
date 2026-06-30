# Predictive Maintenance — Module ↔ Dashboard Mapping (Master Repository Index)

Source: Grafana dashboards (Maintenance, Quadron, GTP, WES, CPU Utilization, Decanting folders).
Scope: Equipment-health modules only. Inventory/order/decant-putaway dashboards are operational state and are **excluded** unless they carry a wear or fault signal.

**Legend**
- **Primary** = core data source for the model (errors / cycles / faults).
- **Secondary** = supporting features or cross-correlation inputs.
- **Signal type** = nature of the leading indicator the module learns from.

---

## 1. Shuttle Health PdM  ✅ BUILT (Session 2) — RESOLVED BY LIVE INSPECTION
**Sub-component:** ASRS shuttles (rotating, high-cycle asset). Roster = **124 units**
(`QD_Shuttle_<aisle>_<unit>`), taken from QUADRON CYCLES.

| Role | Dashboard | Folder | What it provides | Verified |
|------|-----------|--------|------------------|----------|
| Primary | QUADRON ERROR HISTORY (`K2QzauWVz`) | Quadron | Per-shuttle errors `shuttle_id, error_type, error_desc, created_time` (FORK/TELESCOPIC) | ✅ 94 rows |
| Primary | QUADRON CYCLES (`8dDcXomVz`) | Maintenance | Per-shuttle cycles `PUTAWAY, PICKING, RESHUFFLING` (errors/Mcycle + RUL basis) | ✅ 124 shuttles |
| Secondary | Daily Shuttle Errors (`N8QvGxQIk`) | Maintenance | Current aggregated `error_desc -> shuttle (n)` | ✅ panel #2 |
| Secondary | Bad Tracker (`VAW2nmqIz`) | Maintenance | Current `shuttle_id` recurrence + `SHUTTLE_PICK_ERROR` | ✅ 76 rows |
| Secondary | Quadron Alerts (`VxY5Zls7z`) | Quadron | Current free-text active alerts (shuttle mentions) | ✅ panel #2 |

**Signal type:** errors normalised by cycles (errors/Mcycle) + severity/recurrence/peer + cycles-based RUL.
**Build priority:** **1 (highest)** — richest cycle-vs-error data. Implemented in `modules/shuttle/`.
*(This project built Lift first per the kickoff; Shuttle is Module 2. Quadron Alerts' buffer/lane/outbound panels are candidates for a future Buffer/Outbound module.)*

---

## 2. Lift PdM  ✅ BUILT (Session 1) — RESOLVED BY LIVE INSPECTION
**Sub-component:** ASRS lifts (rotating, load-bearing)

| Role | Dashboard | Folder | What it provides | Verified |
|------|-----------|--------|------------------|----------|
| Primary | Lift Error History (`wQds52G4z`) | Quadron | Per-lift fault events: `lift_id, error_code, error_desc, created_time` | ✅ 4,751 rows, 16 lifts |
| Secondary | Bad Tracker Diagnosis (`VAW2nmqIz`) | Maintenance | `lift_id` + current `lift_status` (recurrence + ERROR) | ✅ panel #2 |
| Secondary | Lift Error Analysis (`EqDhnQ9Sz`) | Business Intelligence | Per-lift task counts (load proxy); MTBF/MTTR | ✅ panel #2 |
| Candidate | OPC - Lift Datalogger (`SBaBnPb4z`) | OPC/Kepware | Raw per-lift telemetry (`NCL01–16`) | ⏳ needs time handling |
| Candidate | Process - Lift (`Z0Ls6L7Sk`) | Business Intelligence | Per-lift cycle-time/throughput/idle | ⏳ needs var-date/shift |
| Candidate | Lift_Supply_Tote (`lPsUfQ4Ska`) | Quadron | Load / throughput | ⏳ needs var-date/shift |

**Signal type:** Error rate + severity + recurrence + peer deviation + current status + load → motor/mechanical failure prediction.
**Build priority:** **2** — high-value rotating asset. Implemented in `modules/lift/`.

> **CORRECTION (Session 1):** the original mapping listed **QUADRON CYCLES** and
> **QUADRON ERROR HISTORY** as lift sources. Live SQL inspection shows both are
> **shuttle-specific** (`shuttle_id`, PUTAWAY/PICKING/RESHUFFLING / `shuttle_error`)
> with no `lift_id` — **reassigned to the Shuttle module (§1)** and removed here.

---

## 3. Gate PdM
**Sub-component:** Quadron gates (actuators)

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | Quadron-gate-status | Maintenance | Gate open/close states, faults |
| Secondary | QUADRON ERROR HISTORY | Quadron | Gate-related error codes |

**Signal type:** Open/close fault pattern + response-latency drift → actuator degradation.
**Build priority:** 5 — event-frequency anomaly, quick win.

---

## 4. Tracker / Position-Sensor PdM
**Sub-component:** Grid position trackers

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | Bad Tracker Diagnosis | Maintenance | Tracker fault diagnostics per ID |
| Secondary | Aggregate Error Report | Maintenance | Error clustering by location/tracker |

**Signal type:** Error clustering on specific tracker IDs → pre-failure warning (mislocated totes).
**Build priority:** 4 — anomaly detection, quick win.

---

## 5. Bin / Tote Mechanical PdM
**Sub-component:** Storage bin slots / rails

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | Bin Block History | Maintenance | Block events per bin location |
| Primary | Bin blocked (i.e. tote tilted) | Maintenance | Tilt/block faults |
| Secondary | Aggregate Error Report | Maintenance | Location-level error aggregation |

**Signal type:** Recurring blocks/tilts at the **same** location → slot/rail degradation (not random).
**Build priority:** 6.

---

## 6. Conveyor PdM
**Sub-component:** GTP conveyor zones (belts, motors, diverters)

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | Conveyor Zone Count | GTP | Throughput per zone |
| Primary | Discrepancy Report Events | GTP | Jam / misroute events per zone |
| Secondary | GTP (HOLD, TRANSIT) | GTP | Flow state, stuck-in-transit signals |

**Signal type:** Jam/misroute frequency + throughput drop per zone → belt/motor/diverter wear.
**Build priority:** **3** — rotating asset with rich data.

---

## 7. GTP Station + Scanner PdM
**Sub-component:** GTP pick stations + barcode scanners

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | GTP Scanner logs | GTP | Scan attempts / misreads (key leading indicator) |
| Primary | GTP Station Information | GTP | Station uptime/downtime, status |
| Secondary | Live GTP Summary | GTP | Real-time station throughput |
| Secondary | Discrepancy Report Events | GTP | Scan-driven discrepancies |
| Secondary | GTP Stations | GTP | Station master / config reference |

**Signal type:** Scanner misread-rate trend + station downtime pattern → scanner/station hardware failure.
**Build priority:** 7 — anomaly detection, quick win.

---

## 8. Decanting Station + Scanner PdM
**Sub-component:** Decant stations + scanners

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | Decanting station report | Decanting | Per-station activity & faults |
| Primary | Discrepancy Marked Barcode | Decanting | Barcode scan-failure rate |
| Primary | Discrepancy Marked Carton | Decanting | Carton-level scan discrepancies |
| Secondary | StationWise Decanted Cartons Count | Decanting | Throughput baseline per station |
| Secondary | Station-Material Wise Decants | Decanting | Station load profile |

**Signal type:** Per-station scan-failure / discrepancy climb → scanner or station degradation.
**Build priority:** 8.

---

## 9. Network / Comms PdM
**Sub-component:** Controller communication layer

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | Quadron Network status | Maintenance | Latency, packet loss, link state |

**Signal type:** Latency creep / packet-loss trend → comms failure precursor (often precedes shuttle/lift errors — strong cross-feature).
**Build priority:** 9 — also feed as input to Modules 1, 2.

---

## 10. Controller / Compute PdM
**Sub-component:** Controller compute nodes

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | CPU Stats | CPU Utilization | CPU / memory utilization trend |

**Signal type:** CPU/memory saturation trend → controller crash/throttle.
**Build priority:** 10 — also feed as input to meta-module.

---

## 11. System-Wide Anomaly Layer (Meta-Module)
**Sub-component:** Cross-system / compound failures

| Role | Dashboard | Folder | What it provides |
|------|-----------|--------|------------------|
| Primary | Aggregate Error Report | Maintenance | All-component error aggregation |
| Primary | QUADRON ERROR HISTORY | Quadron | Long-horizon multi-asset error log |
| Secondary | Quadron Alerts | Quadron | Active alert state |
| Secondary | Quadron Network status | Maintenance | Comms degradation chain trigger |
| Secondary | CPU Stats | CPU Utilization | Compute degradation chain trigger |

**Signal type:** Cross-correlation of all modules → compound failure chains (e.g. network degradation → shuttle errors → bin blocks).
**Build priority:** 11 (build last, once individual modules exist).

---

## Build Sequence (recommended)

1. Shuttle Health
2. Lift
3. Conveyor
4. Tracker / Position-Sensor
5. Gate
6. Bin / Tote Mechanical
7. GTP Station + Scanner
8. Decanting Station + Scanner
9. Network / Comms
10. Controller / Compute
11. System-Wide Anomaly Layer (meta)

**Rationale:** Rotating / high-cycle assets (1–3) first — they carry cycle-vs-error data needed for RUL modeling. Event-frequency anomaly modules (4–8) are faster wins. Infra modules (9–10) double as cross-features. Meta layer (11) requires the others to exist.

---

## Excluded Dashboards (operational state, not equipment health)

General (Over Allocation, Release Tote From Compaction); all Decanting *inventory/putaway* dashboards (Already Decanted Barcodes, Already Used Carton, Carton Details, Decant Dashboard NEW, Decanted Materials Data, Decanted Totes According to Partitions, Decanting History Report, Decanting Putaway, GRN Bin Summary, Total/Pending/Decanted Cartons, User State Report); Quadron inventory (Empty Totes Inside ASRS, Pending outbound queue, Quadron Discrepancy, Quadron Inventory, Quadron Occupancy, Quadron location finder, Tote Finder); GTP inventory (GTP Stock Check, GTP TOTE PROPERTIES, Location Container); Returns Putaway; Supervisor Dashboard (Available Stock, DBA approved); all WES inventory/order dashboards; Lenskart Client Requirement (Tote occupancy statistics).

> Note: a few of these (e.g. Quadron Occupancy, Tote Level Inventory) could later become **load/stress features** for the rotating-asset modules if you want utilization context — keep them as optional secondary inputs, not core sources.