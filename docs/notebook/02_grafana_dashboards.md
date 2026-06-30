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

*(Subsequent sessions append their module's dashboard sections here.)*
