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
| 3 | Conveyor | _next session_ | ⏳ planned (Conveyor Zone Count, Discrepancy Report Events, GTP HOLD/TRANSIT) |
| 4 | Tracker / Position-Sensor | — | planned |
| 5 | Gate | — | planned |
| 6 | Bin / Tote Mechanical | — | planned |
| 7 | GTP Station + Scanner | — | planned |
| 8 | Decanting Station + Scanner | — | planned |
| 9 | Network / Comms | — | planned (cross-feature for Lift/Shuttle) |
| 10 | Controller / Compute | — | planned |
| 11 | System-Wide Anomaly (meta) | — | planned (last) |

## Operating the system
- [README.md](README.md) — operator + developer guide (install, run, LAN access, dashboards).
