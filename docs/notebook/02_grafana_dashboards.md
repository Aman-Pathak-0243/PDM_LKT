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

*(Subsequent sessions append their module's dashboard sections here.)*
