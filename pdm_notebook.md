# PdM Notebook — master index

The Predictive Maintenance book. Read top-to-bottom for full context; this index
links every chapter and module. The final Word notebook (built later) compiles in
this order: Chapter 1, Chapter 2, one chapter per module, then the data-volume chapter.

> New sessions: read **`CLAUDE.md`**, this index, **`docs/mapping/module_dashboard_mapping.md`**,
> and every **`modules/*/README.md`** to recover full context, then follow the
> per-module SOP in `CLAUDE.md §5`.

## Foundations
- [CLAUDE.md](CLAUDE.md) — durable conventions (rules, architecture, SOP, methodology, schema, session-end).
- [Chapter 1 — Intro to the ASRS](docs/notebook/01_intro_to_asrs.md) — the physical system.
- [PdM Methodology](docs/notebook/methodology.md) — how health is inferred without a logbook.

## Reference
- [Chapter 2 — Grafana dashboards](docs/notebook/02_grafana_dashboards.md) — panels/fields/relevance (grows each session).
- [Chapter 3 — Data volume](docs/notebook/03_data_volume.md) — fetch volumes + store growth.
- [Module ↔ Dashboard mapping](docs/mapping/module_dashboard_mapping.md) — the master repository index (kept in sync).
- [DB schema](db/schema.sql) — MySQL schema (designed; CSV mirror is active until permission).
- [Audit & hardening report](docs/AUDIT_REPORT.md) — Session 12 full-codebase correctness/methodology/RCA audit + fixes (see also methodology.md §12).

## Modules
| # | Module | Chapter | Status |
|---|--------|---------|--------|
| 1 | Lift | [modules/lift/README.md](modules/lift/README.md) | ✅ built (Session 1) |
| 2 | Shuttle | [modules/shuttle/README.md](modules/shuttle/README.md) | ✅ built (Session 2) — cycles-based RUL |
| 3 | Conveyor | [modules/conveyor/README.md](modules/conveyor/README.md) | ✅ built (Session 3) — per-zone congestion (live data) |
| 4 | Tracker / Position-Sensor | [modules/tracker/README.md](modules/tracker/README.md) | ✅ built (Session 4) — per-location cluster + cross-run recurrence |
| 5 | Gate / Door-Actuator | [modules/gate/README.md](modules/gate/README.md) | ✅ built (Session 5) — per-gate open/close state + response latency + stuck persistence (live) |
| 6 | Bin / Tote-Mechanical | [modules/bin_mech/README.md](modules/bin_mech/README.md) | ✅ built (Session 6) — per-slot bin-block/tilt: block-age + historical + cross-run recurrence (live) |
| 7 | GTP Station + Scanner | [modules/gtp_station/README.md](modules/gtp_station/README.md) | ✅ built (Session 7) — dual-entity: 272 scanners (misread rate) + 63 stations (discrepancy rate), live data |
| 8 | Decanting Station + Scanner | [modules/decant_station/README.md](modules/decant_station/README.md) | ✅ built (Session 8) — dual-entity: 9 decant/compaction scanners (misread rate) + 10 stations (status/throughput, no live discrepancy feed); reconciled 9 devices from GTP (each device owned by one module), live data |
| 9 | Network / Comms | [modules/network/README.md](modules/network/README.md) | ✅ built (Session 9) — per-shuttle comms link (124) scored on network downtime% (Quadron Network status / SHUTTLE_NETWORK_STATUS); today-vs-window recency spike + aisle-cluster + cross-feature flags to Shuttle/meta, live data |
| 10 | Controller / Compute | [modules/controller/README.md](modules/controller/README.md) | ✅ built (Session 10) — single compute node (`db_controller`) scored on CPU utilization% (CPU Stats / getCPUDetails); current-state so store provides sustained-high + trend; system-wide `meta` cross-flag, live data |
| 11 | System-Wide Anomaly (meta) | [modules/meta/README.md](modules/meta/README.md) | ✅ built (Session 11, FINAL) — store-only correlation layer; 6 aisles + system compound-risk (breadth + realized causal chains + persistence) from component_health + cross_module_flags; no Grafana fetch, no core edits |

**Module set COMPLETE — 11/11 built.** The Word notebook compiles: Chapter 1, Chapter 2, one chapter per module (Lift → Meta), then the data-volume chapter (Chapter 3).

## Operating the system
- [README.md](README.md) — quick-start (install, run, LAN access, dashboards).

## Guides (Session 13 documentation suite)
- [System Overview](docs/SYSTEM_OVERVIEW.md) — what it is, how it's built, what it tracks, the value it adds.
- [Operator SOP](docs/OPERATOR_SOP.md) — how to run + monitor it (regular vs interval tasks, navigation).
- [Hosting Resources](docs/HOSTING_RESOURCES.md) — machine spec, DB-size projection, LAN/firewall, backup.
- [Developer Guide](docs/DEVELOPER_GUIDE.md) — architecture, adding a module, and the DB backup/export/migration workflow.
- [URL / Route Map](docs/URL_MAP.md) — every dashboard page + JSON endpoint.
- [Dashboard UI & Graphical Overview](docs/DASHBOARD_UI.md) — the Overview page's Module-Health + Graphical-Overview tabs, every fleet chart, its data source, and the dependency-free SVG chart rules.
- [Per-Module Health Methodology](docs/MODULE_METHODOLOGY.md) — panels → fields → algorithm, per module.
- [CSV Database — data dictionary](database/README.md) — the single CSV `database/` folder (store + analytics extracts + archive/exports), how it's laid out for trends/EDA/ML, and quick-start recipes.
- [Analytics dataset builder](scripts/build_analytics_dataset.py) — flatten the store into tidy trend/EDA/ML CSVs under `database/analytics/` (universal time-series + per-module feature matrices + data dictionary).
- [Migration/export script](scripts/db_migrate_export.py) — backup / copy / load / verify the store (CSV↔MySQL).
- **[ASRS_PdM_Notebook.docx](docs/ASRS_PdM_Notebook.docx)** — the compiled Word notebook (all of the above + module chapters), rebuilt via [`scripts/build_notebook.py`](scripts/build_notebook.py).
- **[ASRS_PdM_Executive_Summary.docx](docs/ASRS_PdM_Executive_Summary.docx)** — weekly stakeholder progress report (executive summary with live charts + architecture/workflow diagrams), rebuilt via [`scripts/build_exec_summary.py`](scripts/build_exec_summary.py).
