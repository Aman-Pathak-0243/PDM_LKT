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

## 3. Gate PdM  ✅ BUILT (Session 5) — RESOLVED BY LIVE INSPECTION
**Sub-component:** Quadron gates (door actuators). Roster = **52 units**
(`aisle_<NN>_level_<NN>_<FG|RG>` — front/rear gate per aisle+level; 26 FG + 26 RG),
taken from Quadron-gate-status.

| Role | Dashboard | Folder | What it provides | Verified |
|------|-----------|--------|------------------|----------|
| Primary | Quadron-gate-status (`5gFdGgwnz`) | Maintenance | `#2` current state of all 52 gates: `id, status(1=CLOSED/2=OPEN REQUEST INITIATED/3=OPEN), aisle`. `#4` = open/requested subset. **Current-state** (window not server-filtered). | ✅ 52 gates |
| Secondary (latency) | Quadron Alerts (`VxY5Zls7z`) | Quadron | `#2` free-text `… front_gate|rear_gate open initiated|opened for N minutes` → per-gate stuck-minutes (response latency, from `gate.updated_timestamp`). Shared with the Shuttle module. | ✅ panel #2 |

**Signal type:** open/close state + **response-latency** (minutes stuck non-closed) + cross-run
**non-closed recurrence/persistence** (from the store) + peer deviation → door-actuator
degradation. Implemented in `modules/gate/`.

> **CORRECTION (Session 5):** the mapping listed **QUADRON ERROR HISTORY** (`K2QzauWVz`) as the
> Gate secondary ("Gate-related error codes"). Live SQL shows `#2` is **`shuttle_error` only**
> (`shuttle_id, error_type, error_desc`; 94 rows, **no gate/id column**) — it is the Shuttle
> module's primary. **Dropped as a gate source.** The real gate signal is Quadron-gate-status
> (current open/close state) + Quadron Alerts (stuck-minutes latency).

---

## 4. Tracker / Position-Sensor PdM  ✅ BUILT (Session 4) — RESOLVED BY LIVE INSPECTION
**Sub-component:** ASRS **grid position sensors / tracker readers** — the component is the
grid **`location`** (`aisle_<NN>_bt_<NN>`), NOT the per-tote tracker tag. Universe = the
locations currently exhibiting bad-tracker events (dynamic anomaly set, ~54 this snapshot).

| Role | Dashboard | Folder | What it provides | Verified |
|------|-----------|--------|------------------|----------|
| Primary | Bad Tracker Diagnosis (`VAW2nmqIz`) | Maintenance | `#2` "Bad Tracker": current mislocated totes `tracker, container, location, created_time, shuttle_id, task_type, status, lift_id, …` → per-location cluster | ✅ 86 rows, current-state |
| Context | Bad Tracker Diagnosis | Maintenance | `#4` "Total BT Totes" (scalar count) | ✅ 1 row |
| Drill-down (not used) | Bad Tracker Diagnosis | Maintenance | `#8/#6/#10` need `${tracker}/${lift}/${shuttle}` (per-entity drill-downs) | ✅ documented |

**Signal type:** bad-tracker events **clustering** on the same grid location + **cross-run
recurrence** (from the store) + recency + robot breadth + peer deviation → position-sensor
pre-failure (mislocated totes). Implemented in `modules/tracker/`.

> **CORRECTION 1 (Session 4 — kickoff):** the component is **not** the `tracker` ID. The
> `tracker` field is a per-tote position tag (**86 distinct tags in 86 rows — no recurrence**),
> whereas the grid `location` clusters (`aisle_03_bt_10`=5 stuck totes, `aisle_04_bt_5`=4) and
> is the fixed unit that physically degrades. Component reassigned to **location (position sensor)**.
>
> **CORRECTION 2 (Session 4 — mapping):** the secondary **Aggregate Error Report** (`DaVyCb9Hz`)
> was listed as "error clustering by location/tracker". Live SQL shows it is `shuttle_error UNION
> lift_error` keyed by `robot_id` with **no tracker/location column** (17,368 rows: 14,012 SHUTTLE +
> 3,356 LIFT) — already covered by the Shuttle + Lift modules. **Dropped as a tracker source.**

---

## 5. Bin / Tote Mechanical PdM  ✅ BUILT (Session 6) — RESOLVED BY LIVE INSPECTION
**Sub-component:** Storage bin slots / rails. Component = the grid bin **LOCATION**
(slot `NNN-NN-N-NNN-N-NN` = Aisle-Level-Rack-Location-Deep). Universe = the currently-blocked
slots (dynamic anomaly set, ~40 this snapshot).

| Role | Dashboard | Folder | What it provides | Verified |
|------|-----------|--------|------------------|----------|
| Primary | Bin blocked (i.e. tote tilted) (`GOqISik4k`) | Maintenance | `#2` current blocked bins per location: `tracker, aisle, zone, level, location, container, blockedTime` (bin_blocked status=0). Current-state; partition-inflated → dedup to blocked-tote events. | ✅ ~40 locations |
| Secondary (historical) | Bin Block History (`hIVZMtGVz`) | Maintenance | `#2` per-location historical block frequency (`shuttle_command status=10`, source/dest bins). **Frozen** 2022-24; 26,638 rows, max 263 blocks at one slot → chronic-slot enrichment. | ✅ 26,638 rows |

**Signal type:** bin-block (tote-tilt) events at a slot — **block-age** (how long unresolved) +
current cluster + **historical block frequency** (chronic slot) + **cross-run recurrence** (from
our store) + peer deviation → slot/rail degradation (not random). Implemented in `modules/bin_mech/`.

> **CORRECTION (Session 6):** the mapping listed **Aggregate Error Report** (`DaVyCb9Hz`) as the
> bin secondary ("location-level error aggregation"). Live SQL shows it is `shuttle_error UNION
> lift_error` keyed by `robot_id` with **no location column** (6,081 rows) — covered by the
> Shuttle + Lift modules. **Dropped as a bin source.** Also noted: **Bin Blocked Statistics**
> (`wNp3FGZNk11`, incl. `#14 "Repeated Location"`) reads the *same* live `bin_blocked` table as
> the primary (server-side aggregates) — documented as equivalent, not separately fetched.

---

## 6. Conveyor PdM  ✅ BUILT (Session 3) — RESOLVED BY LIVE INSPECTION
**Sub-component:** GTP conveyor zones (belts, motors, diverters). Universe = **6 zones**.

| Role | Dashboard | Folder | What it provides | Verified |
|------|-----------|--------|------------------|----------|
| Primary | Conveyor Zone Count (`lavIciTDk`) | GTP | Per-zone congestion: `conveyor_actual/limit` + `buffer_actual/limit` over time (6 zone panels) | ✅ live, ~65k rows |
| Secondary | GTP (HOLD, TRANSIT) (`C8jMvAcIk`) | GTP | Order/tray flow state (counts = module flow stress) | ✅ panels #2/#4 |

**Signal type:** per-zone **congestion** (queue vs limit, severe-saturation, peak, buffer fill, peer deviation) → belt/motor/diverter wear. Implemented in `modules/conveyor/`.

> **CORRECTION (Session 3):** the mapping listed **Discrepancy Report Events** as conveyor
> "jam/misroute per zone". Live SQL shows it is **GTP-station pick verification**
> (`verification_events`: station/operation_type/type/discrepancy_type) keyed by **station**,
> not zone — **reassigned to Module 7 (GTP Station + Scanner)**, which is now **built (Session 7)**
> and owns it (the `.env` key moved `CONVEYOR__ → GTP_STATION__`). Grafana exposes no discrete
> conveyor jam-event feed, so conveyor health uses congestion (the observable symptom).

---

## 7. GTP Station + Scanner PdM  ✅ BUILT (Session 7) — RESOLVED BY LIVE INSPECTION
**Sub-components:** GTP barcode **scanners** (272, `gtp_scanner`) **and** GTP pick **stations**
(63, `gtp_station` — `GS001..GS063`). First module scoring **two component types** in one plugin.

| Role | Dashboard | Folder | What it provides | Verified |
|------|-----------|--------|------------------|----------|
| Primary (scanner) | GTP Scanner logs (`pK7-8NmVz`) | GTP | `#8` "Scanner Read /No read Data" `scanner, ReadCount, NoReadCount, efficiency` → per-scanner **misread rate** (NoRead/(Read+NoRead)); the scanner universe | ✅ 272 scanners, windowed |
| Secondary (volume) | GTP Scanner logs | GTP | `#4` "Scanner Hits" `scanner, hits` (usage/volume) | ✅ 272 rows |
| Primary (station) | Discrepancy Report Events (`D6sQle2Vz`) | GTP | `#2` `verification_events` (time-filtered) `station, operation_type, type, discrepancy_type, create_time` → per-station **pick-verification discrepancy rate** | ✅ ~1,150 rows/2d, 47/63 stations |
| Primary (roster) | GTP Stations (`GlGBwgY4z`) | GTP | `#2` "Station Summary" `id, Type, operation_type, active_status(Active/Inactive), updated_on` → 63-station roster + status | ✅ 63 stations |

**Signal type:** scanner **misread rate** (volume-gated) + peer/recurrence/trend; station
pick-**discrepancy rate** (peer deviation dominant, isolating station-specific degradation from
plant-wide inventory shorts) + recurrence/trend + low-weight offline-persistence. active_status
is context. A `GS<NN>-SL<NN>` scanner is the pick-station scanner → RCA cross-links a station to
its slot scanner. Implemented in `modules/gtp_station/`.

> **CORRECTION 1 (Session 7):** the mapping listed **GTP Station Information** (`j-fIgfqnk`) as
> "station uptime/downtime, status" and **Live GTP Summary** (`j_cdWK_7z`) as "real-time station
> throughput". Live SQL shows both are **pendency/inventory** (remaining_quantity/lines/skus,
> wave/outbound) — **operational state, not health**. **Both dropped.** The real scanner-misread
> signal is **GTP Scanner logs `#8`** (a per-scanner Read/NoRead table the mapping did not single
> out); a `scanner_events` (`N6tdd2aSz`) dashboard the mapping never listed backs it (per-tote
> drill-down, not a population source).
>
> **CORRECTION 2 (Session 7):** **Discrepancy Report Events** (`D6sQle2Vz`) — reassigned here from
> Conveyor in Session 3 — is confirmed `verification_events` keyed by **station** (the station
> primary). Its `.env` key moved `CONVEYOR__ → GTP_STATION__`. **GTP Throughput v2** (`ZR7Z2FR4z`)
> per-scanner/station hit-rate timeseries is a documented **future secondary** (per-run trend
> already accrues in our store).

**Build priority:** 7 — anomaly detection, quick win. **Built.**

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