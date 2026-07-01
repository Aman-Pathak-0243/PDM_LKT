# Chapter 2 — Grafana dashboards (panels, fields, and relevance)

> This chapter is the human-readable twin of the `panel_catalog` table. It grows
> one section per module/session as dashboards are inspected. Each entry records
> the dashboard, its panels (id, type, fields, query target), and the **relevance
> verdict** for the module being built. Enumeration is always via the authenticated
> JSON API (`/api/dashboards/uid/<uid>`); panel ids are never guessed.

Grafana base: `http://192.168.24.230/grafana`. 108 dashboards across folders
(Business Intelligence, Maintenance, Quadron, GTP, Decanting, WES, CPU Utilization,
OPC/Kepware, …). Most panels back onto MySQL `lenskart_quadron` or MSSQL
`lenskart_opc_logs`.

---

## Session 1 — LIFT module

The LIFT module was resolved from the dashboards below (inspected + sampled
2026-06-30). **Key correction to the mapping:** two dashboards the mapping listed
as lift sources are in fact shuttle-specific and were reassigned to the Shuttle
module (see the mapping markdown).

### Lift Error History — `wQds52G4z` (folder: Quadron) — **PRIMARY**
Template vars: `startTime`, `endTime` (the panel returns full history regardless of
the dashboard time window; the model filters in-code).

| Panel | id | type | Fields | Query target | Verdict |
|-------|----|------|--------|--------------|---------|
| Lift Error History | 2 | table | `lift_id, error_code, error_desc, created_time, updated_timestamp` | MySQL `lenskart_quadron` | **PRIMARY signal.** Per-lift fault events with semantic error descriptions. 4,751 rows spanning 2022-09 → 2023-02, 16 distinct lifts. The backbone of the LIFT model. |

Observed data is **historical/frozen** (no rows in the last 2 years). The model
anchors its analysis window to `as_of = max(created_time)` so it works identically
on this frozen source and on live data (methodology.md §6).

### Bad Tracker Diagnosis — `VAW2nmqIz` (folder: Maintenance) — **SECONDARY (cross-relevant)**
Template vars: `lift`, `tracker`, `shuttle`.

| Panel | id | type | Fields | Verdict |
|-------|----|------|--------|---------|
| Bad Tracker | 2 | table | `tracker, container, location, created_time, shuttle_id, task_type, status, shuttle Status Description, lift_id, lift_status, lift Status Description, Last Possible Tracker…` | **SECONDARY.** Rows carry `lift_id` + `lift status` when a bad tracker is lift-associated → lift recurrence + **current ERROR status**. Current data (2026). |
| Total BT Totes | 4 | stat | `Value` | Context only (count of bad-tracker totes). |
| latest Lift Tasks WithIn Given TimeRange | 6 | table | needs `var-lift` | Not used (empty without a lift var). Future: per-lift task/command stream. |
| Tracker Journey / Latest Shuttle Commands | 8 / 10 | table | needs vars | Not lift signals (tracker/shuttle). Relevant to Tracker/Shuttle modules. |

### Lift Error Analysis — `EqDhnQ9Sz` (folder: Business Intelligence) — **SECONDARY (load context)**
Template var: `lift`. MSSQL, derived analytics.

| Panel | id | type | Fields | Verdict |
|-------|----|------|--------|---------|
| Lift Level Task Creation Count | 2 | table | `Aisle, Front Inbound Lift, Front Outbound Lift, Back Inbound Lift, Back Outbound Lift` | **SECONDARY (load proxy).** Per-aisle cumulative task counts per lift position (Front=lift_01, Back=lift_02). Used as relative load context. |
| MTBF / MTTR / Total Errors | 16 / 12 / 18 | stat | `MTFB`, `MTTR`, `error_count` | System-wide KPIs (single values). Useful context; the model computes its own per-lift MTBF from the primary signal. |
| Lift Level Errors / Liftwise Errors / Uptime-Downtime / Run Time | 4 / 22 / 24 / 20 | bar/pie | — | Visualisation panels; CSV not exposed in inspector. Conceptually duplicative of the primary error source. |

### Candidates discovered but not used this session (documented for the future)
| Dashboard | uid | Why deferred |
|-----------|-----|--------------|
| OPC - Lift Datalogger | `SBaBnPb4z` | 16 panels (`NCL01–NCL16`), raw per-lift OPC telemetry (`device_id, value, timestamp`) from MSSQL `lenskart_opc_logs`. Returned no downloadable data in-window (no CSV button). Potentially the richest source — revisit with explicit time handling. |
| Process - Lift | `Z0Ls6L7Sk` | xy-charts of per-lift cycle-time / throughput / idle%; require `var-date`/`var-shift`. High value once parameterised. |
| Lift_Supply_Tote | `lPsUfQ4Ska` | Load/throughput; requires `var-date`/`var-shift`/`var-station_type`. |
| Lift Error-time Graph | `R25cf1RHz` | Monthly error-time per lift; requires `var-year`/`var-month`. |

### Reassigned to the SHUTTLE module (NOT lift — corrected mapping)
| Dashboard | uid | Actual content |
|-----------|-----|----------------|
| QUADRON CYCLES | `8dDcXomVz` | Shuttle cycle counts: `shuttle_id, PUTAWAY, PICKING, RESHUFFLING` (panel #2 "Shuttle Cycles", #4 "Shuttle date wise"). 124 shuttles. → Shuttle primary (cycles/wear). |
| QUADRON ERROR HISTORY | `K2QzauWVz` | Shuttle errors: `shuttle_id, error_type, error_desc, created_time, updated_timestamp`. → Shuttle primary (errors). |

---

## Session 2 — SHUTTLE module

Resolved + sampled 2026-06-30. Shuttle uniquely has **cycle** data, enabling
usage-normalised faults and cycles-based RUL.

### QUADRON ERROR HISTORY — `K2QzauWVz` (folder: Quadron) — **PRIMARY (errors)**
Template vars: `From`, `To`.

| Panel | id | type | Fields | Verdict |
|-------|----|------|--------|---------|
| Quadron Shuttle Errors | 2 | table | `shuttle_id, error_type, error_desc, created_time, updated_timestamp` | **PRIMARY.** 94 rows (frozen 2023-08-11), 4 shuttles; `FORK_ERROR` (fork up/down faulty) + `TELESCOPIC_ERROR` dominate. |

### QUADRON CYCLES — `8dDcXomVz` (folder: Maintenance) — **PRIMARY (cycles / RUL)**
Template vars: `startTime`, `endTime`.

| Panel | id | type | Fields | Verdict |
|-------|----|------|--------|---------|
| Shuttle Cycles | 2 | table | `shuttle_id, PUTAWAY, PICKING, RESHUFFLING` | **PRIMARY.** 124 shuttles; cumulative cycles (TOTAL 11k–79k). Basis for errors/Mcycle + RUL. |
| Shuttle date wise | 4 | table | date-wise breakdown | Not used (date pivot of the same data). |

### Daily Shuttle Errors — `N8QvGxQIk` (folder: Maintenance) — **SECONDARY (current)**
No vars. Panel #2 (MSSQL `string_agg`): `error_desc, Value` where `Value` = `shuttle_id (n),…`.
Parsed to current per-shuttle error counts. Current snapshot (vs frozen error history).

### Bad Tracker Diagnosis — `VAW2nmqIz` — **SECONDARY (current recurrence)**
Panel #2 carries `shuttle_id` + `shuttle Status Description` (`SHUTTLE_PICK_ERROR`): 76 current
rows → shuttle recurrence + current pick-error. (Also a lift source — Module 1.)

### Quadron Alerts — `VxY5Zls7z` (folder: Quadron) — **SECONDARY (current alerts)**
16 panels, mostly **operational** (buffers, lanes, outbound queue, containers) — *excluded*.
Panel #2 "Quadron Alerts" (`message`) carries free-text active alerts; shuttle mentions parsed
to a current-alert flag. The buffer/lane/outbound panels are candidates for a future
Buffer/Outbound module.

---

## Session 3 — CONVEYOR module

Resolved + sampled 2026-06-30. Data is **live/current** (unlike the frozen Lift/Shuttle
error logs). Component universe = **6 zones**.

### Conveyor Zone Count — `lavIciTDk` (folder: GTP) — **PRIMARY (per-zone congestion)**
No template vars. MSSQL `lenskart_gtp.dbo.conveyor_zone_count`.

| Panel | id | type | Fields | Verdict |
|-------|----|------|--------|---------|
| Zone 1–6 | 6, 8, 10, 12, 14, 16 | timeseries | `time, Conveyor Actual, Conveyor Limit, Buffer Actual, Buffer Limit` (per `WHERE zone='N'`) | **PRIMARY.** Per-zone queue vs limit over time. 6k–17k samples/zone/day. All zones run ≈1.0–1.5× limit. |
| Panel Title (snapshot) | 4 | table | `Last Updated, Zone ID, Conveyor (Actual/Limit), Buffer (Actual/Limit)` | Latest per-zone state (best-effort context). |

### GTP (HOLD, TRANSIT) — `C8jMvAcIk` (folder: GTP) — **SECONDARY (flow stress)**
No vars. Panel #2 `ON_HOLD Orders` (≈200 rows), #4 `Transit state` (≈180 rows): order/tray
flow keyed by `station_id` (not zone). Used as module-level **counts** (`system_on_hold`,
`system_in_transit`), not per-zone scoring.

### Discrepancy Report Events — `D6sQle2Vz` (folder: GTP) — **REASSIGNED (NOT conveyor)**
Panel #2 = `verification_events`: `station, operation_type, user, container, type, discrepancy_type,
create_time` (≈17.8k current rows; values `EMPTY_SUPPLY_CONTAINER_CONFIRM`, `SHORT`, …). This is
**GTP-station pick verification keyed by station**, not conveyor jams/zones. **Reassigned to the
GTP Station + Scanner module (Module 7).** Grafana exposes no discrete conveyor jam-event feed.

---

## Session 4 — TRACKER / Position-Sensor module

Resolved + sampled 2026-06-30. **Anomaly/recurrence** module — the component is the
grid **`location`** (the fixed position sensor / tracker reader), not the per-tote
tracker tag. **Two corrections to the kickoff/mapping** (below).

### Bad Tracker Diagnosis — `VAW2nmqIz` (folder: Maintenance) — **PRIMARY**
Template vars: `lift`, `tracker`, `shuttle`. MSSQL `lenskart_quadron`.

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Bad Tracker | 2 | table | `tracker, container, location, created_time, shuttle_id, task_type, status (8=PICK_ERROR), shuttle Status Description, lift_id, lift_status (2=ERROR), lift Status Description, Last Possible Tracker Location/Timestamp` | **PRIMARY signal.** Current set of mislocated totes. **Current-state** (same 86 rows at `now-2d` and `now-90d`; window not server-filtered). `tracker` is a per-tote tag (86 distinct in 86 rows, **no recurrence**); `location` (uniform `aisle_NN_bt_NN`) **clusters** — `aisle_03_bt_10` had 5, `aisle_04_bt_5` had 4. → component = location. |
| Total BT Totes | 4 | stat | `Value` (=85) | Context scalar (count of bad-tracker totes). |
| Tracker Journrey | 8 | table | needs `${tracker}`: `tracker, source, destination, create_timestamp` from `tracker_history` | **Drill-down**, not a population signal. Future RCA enrichment for a flagged location's worst tracker. |
| latest Lift Tasks WithIn Given TimeRange | 6 | table | needs `${lift}` | Per-lift drill-down (cross-module). Not a tracker signal. |
| Latest Shuttle Commands WithIn Given TimeRange | 10 | table | needs `${shuttle}` | Per-shuttle drill-down (cross-module). Not a tracker signal. |

**Correction 1 (kickoff):** the component is **not** the `tracker` ID. A tracker is a
mobile per-tote tag with no within-snapshot recurrence; the recurring/degrading unit is
the fixed grid `location` (position sensor). The model scores locations.

### Aggregate Error Report — `DaVyCb9Hz` (folder: Maintenance) — **DROPPED (NOT a tracker source)**
No template vars. Panel #2 SQL = `shuttle_error UNION lift_error` →
`error_code, error_desc, error_type, robot_id, created_time, updated_timestamp, robotType, Site_name`.

**Correction 2 (mapping):** the mapping listed this as the tracker secondary ("error
clustering by location/tracker"). Live inspection shows **no tracker/location column** —
it is a shuttle+lift error union keyed by `robot_id` (17,368 rows: 14,012 SHUTTLE +
3,356 LIFT), already covered by the Shuttle + Lift modules. **Dropped as a tracker source.**

---

## Session 5 — GATE / Door-actuator module

Resolved + sampled 2026-07-01. Data is **live/current**. Component universe = **52 gates**
(`aisle_<NN>_level_<NN>_<FG|RG>`, 26 front + 26 rear). **Current-state + latency + recurrence**
module (Tracker-family). One correction to the mapping (below).

### Quadron-gate-status — `5gFdGgwnz` (folder: Maintenance) — **PRIMARY**
No template vars. MSSQL `lenskart_quadron.gate` (+ `gate_zone_mapping`, `aisle_zone`).

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Gate status | 2 | table | `select distinct id, status(1=CLOSED/2=OPEN REQUEST INITIATED/3=OPEN), aisle` from `gate` join `gate_zone_mapping` join `aisle_zone` | **PRIMARY signal.** Current state of all **52 gates** = the roster + component universe. **Current-state** (52 rows identical at `now-2d` and `now-90d`; window not server-filtered). Live snapshot: 51 CLOSED, 1 OPEN. |
| OPEN/REQUESTED gate's | 4 | table | same projection, `where status >= 2 and status <= 3` | **Context.** Currently open / open-request-initiated subset — integrity cross-check of #2's non-closed set (1 row when 1 gate open). |

The gate table has an `updated_timestamp` (last status change) but #2/#4 do **not** project it,
so response-latency (minutes stuck non-closed) is read from Quadron Alerts (below).

### Quadron Alerts — `VxY5Zls7z` (folder: Quadron) — **SECONDARY (latency; shared with Shuttle)**
No vars. Panel #2 (`message`) is a `UNION` of many operational alerts. Subquery **H** emits, for
every `gate where status > 1`: `"<id[:18]> front_gate|rear_gate open initiated|opened for
DATEDIFF(MINUTE, updated_timestamp, GETDATE()) minutes"`. Parsed back to the gate id
(`prefix + FG/RG`) → per-gate **stuck_minutes** (response latency). Non-gate rows (shuttle / lift
/ buffer / scanner) are ignored. (This is the same panel the Shuttle module reads for shuttle
alerts — cross-module reuse, CLAUDE.md §7.)

### QUADRON ERROR HISTORY — `K2QzauWVz` (folder: Quadron) — **DROPPED (NOT a gate source)**
Panel #2 SQL = `select shuttle_id, error_type, error_desc, created_time, updated_timestamp from
shuttle_error …` (94 rows). **Correction to the mapping:** the mapping listed this as the Gate
secondary ("Gate-related error codes"). Live SQL shows it has **no gate/id column** — it is
`shuttle_error` and is the **Shuttle module's primary**. **Dropped as a gate source.**

## Session 6 — BIN / TOTE-MECHANICAL module

Resolved + sampled 2026-07-01. **Anomaly/recurrence** module — the component is the grid bin
**LOCATION** (slot `NNN-NN-N-NNN-N-NN`), universe = currently-blocked slots. One correction to
the mapping (below).

### Bin blocked (i.e. tote tilted) — `GOqISik4k` (folder: Maintenance) — **PRIMARY**
Template vars: `aisle`, `level`. MSSQL `lenskart_quadron.bin_blocked` (status=0).

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Bin Blocked report | 2 | table | `tracker, aisle, zone, level, location, container, quantity, blockedTime` (bin_blocked status=0 join location_tracker/container_tracker/zone; entity type 8) | **PRIMARY signal.** Current set of blocked bins per **location** = component universe. **Current-state** (live table; all blocks recent). 224 rows this snapshot → **40 distinct locations** after partition dedup. |
| update_bin_block | 4 | table | `UPDATE bin_blocked set status=1 …` | **ACTION (write) panel — non-signal, skipped.** |
| Bid Unacknowledged report | 5 | table | `select * from bid where status=0` | Unacknowledged bids — not a bin-block signal, skipped. |

### Bin Block History — `hIVZMtGVz` (folder: Maintenance) — **SECONDARY (historical recurrence)**
Template vars: `startTime`, `endTime` (own vars, not Grafana from/to → returns its default range).

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Bin block Block History | 2 | table | `shuttle_id, tracker, source, destination, bay, zone, TIMING` (`shuttle_command status=10` join `bin`/`entity`) | **SECONDARY.** Per-location **SOURCE** frequency = chronic-slot fingerprint. **Frozen** 2022-12 → 2024-09; **26,638 rows**, 2,628 distinct source slots, **max 263** blocks at one slot (348 slots >20×). Barely overlaps current blocks (chronic slots mostly not blocked now) → enriches cold-start / RCA, fetched best-effort. |

### Bin Blocked Statistics — `wNp3FGZNk11` (folder: Lenskart Client Requirement) — **EQUIVALENT (not separately fetched)**
No vars; `$__timeFrom/$__timeTo`. Reads the **same live `bin_blocked` table** as tilted #2:
`#2` "Bin Blocked Data" (event rows incl. `Shuttle`), `#6` "Total Bin Blocked", `#8` "Aisle wise
bin Blocked", **`#14` "Repeated Location for Bin Block"** (`location → COUNT`, all 1 currently —
no within-snapshot recurrence). Server-side view of our primary; documented, not fetched.

### Aggregate Error Report — `DaVyCb9Hz` (folder: Maintenance) — **DROPPED (NOT a bin source)**
Panel #2 = `shuttle_error UNION lift_error` → `error_code, error_desc, error_type, robot_id,
created_time, updated_timestamp, robotType, Site_name` (6,081 rows). **Correction to the mapping:**
listed as the bin secondary ("location-level error aggregation") but has **no location column** —
keyed by `robot_id`, covered by the Shuttle + Lift modules. **Dropped as a bin source.**

## Session 7 — GTP STATION + SCANNER module

Resolved + sampled 2026-07-01. Data is **live/windowed** (the misread + discrepancy panels are
time-filtered — a wider window sharpens the rates). This module scores **two component types**:
**scanners** (272, `gtp_scanner`) and **pick stations** (63, `gtp_station`). Two mapping panels
turned out to be pendency/inventory (dropped); the real scanner-misread panel + a `scanner_events`
dashboard the mapping never listed were found by re-verifying.

### GTP Scanner logs — `pK7-8NmVz` (folder: GTP) — **PRIMARY (scanner)**
No template vars. MSSQL `lenskart_gtp` (`scanner_events`).

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Scanner Read /No read Data | 8 | table | `scanner, ReadCount, NoReadCount, efficiency_percentage` (windowed) | **PRIMARY signal.** Per-scanner misread = `NoRead/(Read+NoRead)`. 272 devices, 2.6M scans/2d; misread median 0.3%, p90 10%, p95 17%, max 100%. The scanner universe. |
| Scanner Hits | 4 | table | `scanner, hits` | **Secondary (volume).** Per-scanner usage proxy (best-effort join). |
| GTP Time wise scanner logs | 2 | table | `se.scanner, se.container, se.decision, se.create_time, se.decision_reason` | Raw event feed — **no Download-CSV** (heavy); `#8` aggregates it. Future RCA (`decision_reason`). |
| Tote Hits / Container location / Latest Hit Inbounds | 6 / 10 / 12 | table | per-container / location / 29 inbounds | Not scanner-population signals. |

Scanner ids carry the subtype: pick-station slot scanners `GS<NN>-SL<NN>` (belong to a station),
`aisle_<NN>_inbound_scanner_<NN>`, `GTP_scanner_<N>`, `Zone…Scanner`, `Compaction_scanner_<N>`,
`aisle_<NN>_*_diverter`, `aisle_<NN>_decant_diverter`. The worst live misreads are station slot
scanners (`GS030-SL02`=53%, `GS015-SL02`=51%) + a dead diverter (`aisle_03_gtp_diverter`=100%).

> **Session 8 update:** the `decant`/`compaction` subtype devices (7 `aisle_<NN>_decant_diverter`
> + 2 `Compaction_scanner_<N>`) were reassigned to the **Decanting Station + Scanner module
> (Module 8)** and are now **excluded** from the GTP scanner universe + peer baseline
> (`gtp_station/module.yaml → scanner.exclude_subtypes`). The GTP scanner universe is therefore
> **263** (was 272). GTP Scanner logs `#8` is a **shared** panel (Module 8 filters it to those 9
> devices). Each device is owned by exactly one module (CLAUDE.md §7).

### Discrepancy Report Events — `D6sQle2Vz` (folder: GTP) — **PRIMARY (station)** — *reassigned from Conveyor (Session 3)*
No vars. MSSQL `lenskart_gtp` (`verification_events`).

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Discrepancy Report Events | 2 | table | `SELECT * from verification_events` (`$__timeFilter` on `create_time`): `station, operation_type, user, container, type, discrepancy_type, create_time` | **PRIMARY signal.** Per-station pick-verification discrepancies. ~1,150 rows/2d across 47 of 63 stations; `type=EMPTY_SUPPLY_CONTAINER_CONFIRM`, `discrepancy_type ∈ {SHORT (1009), ALRIGHT (141)}`. Per-station median 21, p90 47, max 65 (GS037). |

### GTP Stations — `GlGBwgY4z` (folder: GTP) — **PRIMARY (station roster)**
No vars. MSSQL `lenskart_gtp` (`station`).

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Station Summary | 2 | table | `user_id, Type, id, operation_type, active_status(Active/Inactive), created_on, updated_on` | **PRIMARY roster.** The **63-station universe** (GS001..GS063) + Active/Inactive (49/14 this snapshot) + recency. Current snapshot (not window-filtered). |
| Time Elapsed For Tote Inside Station | 6 | gauge | `SUBSTRING(location,1,5) station, DATEDIFF(MINUTE, updated_on, getdate())` | **Future true-downtime signal** — a gauge, no Download-CSV today. |
| Marry_time | 8 | table/gauge | per-station marry latency | Gauge, no CSV. |

### Dropped as GTP-health sources (verified Session 7 by live SQL/sampling)
| Dashboard | uid | Actual content |
|-----------|-----|----------------|
| GTP Station Information | `j-fIgfqnk` | `#2` per-station `remaining_quantity/lines/skus/occupancy` — **PENDENCY/inventory**, not health. The mapping mislabeled it "uptime/downtime". |
| Live GTP Summary | `j_cdWK_7z` | Station pendency / wave / outbound / current-inventory panels — **operational state**, not health. The mapping mislabeled it "real-time station throughput". |
| GTP Throughput v2 | `ZR7Z2FR4z` | *(deferred, not dropped)* per-scanner hit-rate `#8` + per-station line-rate `#2` timeseries — a live trend source; our store already accrues per-run trend, so it is a future secondary. |

## Session 8 — DECANTING STATION + SCANNER module

Resolved + sampled 2026-07-01. This module scores **two component types** — decant/compaction
**scanners** (9, `decant_scanner`) and decant operator **stations** (10, `decant_station`,
`DS001`–`DS010`). The two signals are **very unevenly supported**: the scanner misread rate is a
strong live signal; the station has **no live fault/discrepancy feed** at all. Three mapping
candidates turned out to be frozen drill-downs / var-gated (dropped); the real live sources were
confirmed by re-verifying every candidate.

### GTP Scanner logs — `pK7-8NmVz` (folder: GTP) — **PRIMARY (scanner)** — *shared with Module 7*
No template vars. MSSQL `lenskart_gtp` (`scanner_events`). The **same** `#8` panel the GTP module
uses; this module **filters it to the 9 decant/compaction devices** it owns (name contains `decant`
/ `compaction`). See Session 7 for the full panel table.

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Scanner Read /No read Data | 8 | table | `scanner, ReadCount, NoReadCount, efficiency_percentage` (windowed) | **PRIMARY signal.** Per-device misread = `NoRead/(Read+NoRead)`, filtered to `decant`/`compaction`. 7 decant diverters 0.008–0.167% (ok); 2 compaction scanners ~4% (watch). |

### Decanting station report — `B4i1-HpVz` (folder: Decanting) — **PRIMARY (station roster)**
No template vars. MSSQL `lenskart_decanting` (`station`).

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Decanting Station Report | 2 | table | `select station_id, active_status(1=Active/0=Inactive), user_id from station` | **PRIMARY roster.** The **10-station universe** (`DS001`–`DS010`) + Active/Inactive (9/1 this snapshot) + assigned user. Current snapshot (not window-filtered). |
| Material Type Available | 4 | barchart | `hsn_classification, sum(qty)` from `partition_details` | Partition **inventory** by material class — not a health signal. |

### StationWise Decanted Cartons Count — `n1oZnY_Vz` (folder: Decanting) — **SECONDARY (station throughput)**
No template vars. MSSQL `lenskart_decanting`.

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Station-Wise-Decanted-Cartons | 2 | barchart | `station_id, COUNT(carton_id)` from `grn_pick_list × hu_carton_mapping` (`status=2`, `updated_date` in window) | **SECONDARY.** Per-station decanted-carton **throughput** over the window (**time-filtered**). Used for the idle-while-active anomaly + utilization; low throughput alone is not penalized. This snapshot: 7 stations busy (`DS003`=749 … `DS010`=116). |

### Dropped as decant-health sources (verified Session 8 by live SQL/sampling)
| Dashboard | uid | Actual content |
|-----------|-----|----------------|
| Discrepancy Marked Barcode | `E_nYUnU4z` | `#2` = drill-down `SELECT … FROM discrepancy_details WHERE serial_id = '${Serial_No}'` (one barcode). **No station column**; **frozen 2022** (`create_timestamp 2022-12-21`). The mapping mislabeled it "barcode scan-failure rate". No live per-station discrepancy signal. |
| Discrepancy Marked Carton | `LQMn4RU4k` | `#2` = the same `discrepancy_details` drill-down `WHERE carton_id = '${Carton_Id}'`. Same finding. Dropped. |
| Station-Material Wise Decants | `3TbhR4TSz` | `#2` per-station `carton_count` **filtered by `${hsn_classification}`** — a per-material load profile; no population without the var. Not fetched. |

**Reconciliation (Session 8):** the 9 decant/compaction scan devices were scored by the GTP module
(Module 7) until this session; GTP now excludes subtypes `decant`/`compaction`, so each device is
owned by exactly one module (CLAUDE.md §7). GTP Scanner logs `#8` is a shared panel.

## Session 9 — NETWORK / COMMS module

Resolved + sampled 2026-07-01. Data is **live/windowed**. Component universe = **124 per-shuttle
comms links** (`network_link`, keyed by `shuttle_id`). The single mapped candidate is genuine health
data (not operational/inventory), but live SQL corrected the metric + component key.

### Quadron Network status — `gL0OBnq7z` (folder: Maintenance) — **PRIMARY**
Template var: `Date`. MSSQL `lenskart_quadron` (`shuttle_error`).

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| Shuttle network status specific date | 4 | table | `SELECT shuttle_id, (1 - SUM(DATEDIFF(second, created_time, updated_timestamp))/elapsed_since_${Date})*100 FROM shuttle_error WHERE created_time > '${Date}' AND error_type='SHUTTLE_NETWORK_STATUS' AND status=1 GROUP BY shuttle_id` | **PRIMARY signal.** Per-shuttle network **uptime%** since `${Date}` → we set `${Date}` = window start for a **windowed** downtime% (= 100−uptime). 124-shuttle roster. **Live 2026 data** (unlike the frozen FORK/TELESCOPIC shuttle errors). |
| shuttle/day %uptime | 2 | table | same, but `WHERE created_time > midnight today` (`GETDATE()`) | **Secondary (recency).** Per-shuttle uptime% **today** → flags links worse now than their window average (e.g. `QD_Shuttle_01_19` 29.7% window vs 67% today). Best-effort join by shuttle_id. |

**Live distribution:** downtime% median 3.25%, p90 6.5%, p99 16.9%, worst `QD_Shuttle_01_19` = 29.7%
(70.3% uptime). Aisle clustering: aisle_01 mean 6.74% (worst) vs aisle_05 1.12%.

**Correction to the mapping (Session 9):** the mapping called this "latency, packet loss, link state".
Live SQL shows it is per-shuttle **uptime% / disconnect-duration** derived from `shuttle_error`
(`error_type='SHUTTLE_NETWORK_STATUS'`) — **no latency-ms or packet-loss-% metric**, and the component
key is the **shuttle** (its comms link), not a per-controller/per-link device. This is a **different
error subset** than the Shuttle module's mechanical FORK/TELESCOPIC errors (frozen 2023, which do not
include network status), so scoring comms here does **not** double-count the Shuttle module. The two
OPC dataloggers (`3HJAGPbVk`, `SBaBnPb4z`) are candidate future latency/packet sources (raw telemetry,
no CSV today).

## Session 10 — CONTROLLER / COMPUTE module

Resolved + sampled 2026-07-01. Data is **live/current-state**. Component universe = a **single compute
node** this snapshot (`db_controller`, `compute_node`). The single mapped candidate is genuine health
data, but live SQL corrected its shape (CPU-only, one node, current-state — not a "CPU/memory trend").

### CPU Stats — `CwTEp_GSz` (folder: CPU Utilization) — **PRIMARY**
No template vars. MSSQL stored proc `[DBA].[dbo].[getCPUDetails]`.

| Panel | id | type | Fields / query | Verdict |
|-------|----|------|----------------|---------|
| CPU Utilisation | 17 | piechart | `EXEC [DBA].[dbo].[getCPUDetails]` → **one row** `cpu_idle, cpu_sql` | **PRIMARY signal.** utilization% = `100 − cpu_idle`; `cpu_sql` = SQL Server CPU share. **Current-state** (identical single row at `now-6h`/`now-2d`/`now-30d` — the window does not filter the proc). Live sample: idle 56–70, sql 28–41 → 30–44% utilization (healthy). |

**Correction to the mapping (Session 10):** the mapping billed this as "CPU / memory utilization trend"
across "controller compute nodes" (plural). Live SQL shows **CPU-only**, a **single node**, and a
**current-state snapshot** — no in-feed trend, no memory metric, no per-host breakdown. Scoped honestly
to CPU utilization%; the store provides the sustained-high + trend across runs (like Gate/Bin). The
feature extractor keys by a host/node column if the proc ever returns per-host rows (scalable to N nodes).

### Ruled out (verified Session 10)
| Dashboard | uid | Actual content |
|-----------|-----|----------------|
| JIT Frame Unallocated | `fP9A7Y0Hk` | `#2` = `select … from sales_order_line where jit_flag='true' and category='FRAME'` — **JIT order frames (inventory)**, not compute. Spurious keyword match. |
| OPC - GTP/Lift Datalogger | `3HJAGPbVk` / `SBaBnPb4z` | Raw per-device OPC telemetry (`device_id, value, timestamp`) — no CPU/memory, no CSV. Candidate **future** per-host source. |

## Session 11 — SYSTEM-WIDE ANOMALY (META) module — **NO Grafana source**

Resolved 2026-07-01. The final module has **no dashboard** — it is a **correlation layer over the PdM
store** (`component_health` + `rca_json.cross_module_flags` from Modules 1–10). All mapped §11 candidates
are already owned by other modules or dropped, so re-fetching any would double-count.

| "Source" | What it provides | Verdict |
|----------|------------------|---------|
| PdM store `component_health` | latest row per `(module, component_id)` (excluding `module='meta'`): each module's tier, health, primary_cause, cross-module flags, and `metrics.aisle` | **PRIMARY (store).** Correlated by aisle (+ system) into compound-risk incidents. No Grafana call. |

**Mapped §11 candidates — all resolved, none fetched:**
| Candidate | Status |
|-----------|--------|
| Quadron Network status (`gL0OBnq7z`) | **Owned by Network (Module 9)** — per-shuttle comms uptime. |
| CPU Stats (`CwTEp_GSz`) | **Owned by Controller (Module 10)** — CPU utilization. |
| QUADRON ERROR HISTORY (`K2QzauWVz`) | **Owned by Shuttle (Module 2)** — shuttle_error. |
| Quadron Alerts (`VxY5Zls7z`) | **Owned by Gate/Shuttle** — free-text alerts. |
| Aggregate Error Report (`DaVyCb9Hz`) | **Dropped (redundant)** — `shuttle_error ∪ lift_error` keyed by robot_id, covered by Shuttle + Lift (dropped in Sessions 4/6). |

So meta reads the store only; `is_configured()` is overridden to `True` (no dashboards) and it is
registered LAST so a "Run all" correlates the same trigger's fresh per-module verdicts. This completes the
dashboard inventory — **11/11 modules resolved**.

*(The module set is complete. This chapter is the human-readable twin of `panel_catalog`.)*
