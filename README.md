# ASRS Predictive Maintenance (PdM)

Predictive-maintenance system for the six-aisle ASRS at the Lenskart fulfilment
plant. It learns equipment health **purely from Grafana operational + error data**
(no maintenance logbook), scores each physical component, predicts time-to-
maintenance with a confidence + regime, and explains *why* — all on a local/LAN web
dashboard with terminal-resident automation.

Built **one module per session**. **Module 1: Lift**, **Module 2: Shuttle**
(cycles-based RUL), **Module 3: Conveyor** (per-zone congestion, live data),
**Module 4: Tracker / Position-Sensor** (per-location bad-tracker cluster + cross-run
recurrence), **Module 5: Gate / Door-Actuator** (per-gate open/close state + response
latency + cross-run stuck persistence, live data), **Module 6: Bin / Tote-Mechanical**
(per-slot bin-block/tilt: block-age + historical + cross-run recurrence, live data), and
**Module 7: GTP Station + Scanner** (dual-entity — 272 scanners scored on misread rate +
63 pick stations on pick-discrepancy rate, with cross-run recurrence/trend, live data) are
complete. See [`pdm_notebook.md`](pdm_notebook.md) for the full book and
[`CLAUDE.md`](CLAUDE.md) for durable conventions.

---

## Operator guide

### Prerequisites
- Python 3.11+ (developed on 3.14), on a PC that can reach the Grafana server on the
  company LAN. Secrets + URLs live in `.env` (copy from `.env.example`).

### Install
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

### Run
```bash
.venv/bin/python run.py
```
This starts the web dashboard **and** the automation scheduler in one terminal
process. Open `http://<host-ip>:8800`.

- **Overview** — one tile per module (worst-component status, last run). Pick a
  **window** (top-right) and **Run PdM (all)**, or run a single module from its tile.
- **Per-module page** (`/module/lift`, `/module/shuttle`, `/module/conveyor`, `/module/tracker`, `/module/gate`, `/module/bin_mech`, `/module/gtp_station`) —
  per-component health, risk tier, predicted time-to-maintenance, confidence, regime; click
  a row for RCA + health trend; optional "Mark maintenance done". Each page has an in-page
  **Methodology** section explaining how a component's verdict and the module's overall
  status are computed.
- **PdM Triggers** — every manual + automated run, fully traceable (id, type, status,
  window, duration, counts).
- **Automation** — enable/disable per scope (`global` or a module), set interval +
  window. **Runs in the terminal process, independent of the dashboard** — close the
  browser and automation keeps running; only stopping the service (Ctrl-C) halts it.
- **Storage** — total/per-dataset sizes, record counts, 24 h growth; export
  (CSV/JSON/Excel) by date range; delete by range (confirmed + logged); archive +
  restore.
- **Logs** — searchable structured event log. **System** — status + performance.
  **Plugins** — registered modules + panel catalog. **Settings** — runtime config.

### LAN access
The app binds `APP_HOST:APP_PORT` (default `0.0.0.0:8800`). To reach it from another
device on the same subnet, allow the port through the host firewall:
- **macOS:** System Settings → Network → Firewall → Options → allow Python/the port.
- **Windows:** create an inbound rule for TCP `8800`.
Then browse to `http://<host-ip>:8800`. Healthcheck: `GET /api/health`.

### Storage backend (important)
The active store is **CSV** under `data/store/` — one file per table, mirroring the
MySQL schema. **MySQL is intentionally not used until permission is granted.** The
schema is designed in `db/schema.sql` and a dormant MySQL backend exists; switching
is `STORAGE_BACKEND=mysql` + `MYSQL_CONFIRM=ENABLE` (and the real DB name) — no
application-logic changes.

---

## Developer guide

### Architecture
```
core/      config, structured logging, Grafana auth/fetch/inspect, storage
           abstraction (CSV active / MySQL dormant), module registry, runner,
           scheduler, audit.
modules/   one self-registering plugin per equipment type (lift, shuttle, conveyor, tracker, gate, bin_mech, gtp_station).
webapp/    FastAPI app, JSON API, services, exporting, templates, static.
db/        MySQL schema (designed).
docs/      the PdM book (notebook chapters + mapping).
data/      CSV store + fetched-panel caches + exports/archives (gitignored).
```

A PdM run = **fetch → features → health → persist** (`core/runner.py`). Manual runs
go through a background thread (`webapp/background.py`); automated runs through
APScheduler (`core/scheduler.py`). Both call the same code and write the same datasets.

### Adding a module (the plugin contract)
1. Create `modules/<name>/` with `__init__.py` (subclass `PdMModule`, `register(...)`),
   `module.yaml`, `fetch.py`, `features.py`, `health.py`, `rca.py`, `README.md`.
2. Add one import line in `modules/__init__.py`.
3. Add its dashboard URLs to `.env` under `MODULE__DASHBOARD_NAME` keys.
**No `core/` edits.** The dashboard, runner, scheduler, and storage discover it
automatically. Follow the per-module SOP in `CLAUDE.md §5`.

### Helper scripts
- `scripts/discover_dashboards.py` — log in + list/match dashboards via `/api/search`.
- `scripts/inspect_<module>.py` — enumerate (`meta`) + sample (`sample`) panels
  (`inspect_lift.py`, `inspect_shuttle.py`, `inspect_tracker.py`, `inspect_gate.py`,
  `inspect_gtp.py`, …); `inspect_gtp.py`/`inspect_bin.py`/`inspect_gate.py` have a `discover`
  mode. `scripts/analyze_<module>_primary.py`
  deep-dives a module's primary against live data before features are written.

### Tooling
- Tests/scratch under `tests/`. Logs at `logs/app.log.jsonl` (JSON lines).
- Never run git here (the user manages the repo). Never use MySQL without permission.
- Docker-ready by design (env-driven config, healthcheck, persistent `data/` volume).
