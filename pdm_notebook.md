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
| 10 | Controller / Compute | _next session_ | ⏳ planned (CPU Stats — CPU/memory saturation trend; also feeds the meta-module) |
| 11 | System-Wide Anomaly (meta) | — | planned (last) |

## Operating the system
- [README.md](README.md) — operator + developer guide (install, run, LAN access, dashboards).
