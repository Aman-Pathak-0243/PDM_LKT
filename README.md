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
(per-slot bin-block/tilt: block-age + historical + cross-run recurrence, live data),
**Module 7: GTP Station + Scanner** (dual-entity — 263 scanners scored on misread rate +
63 pick stations on pick-discrepancy rate, with cross-run recurrence/trend, live data), and
**Module 8: Decanting Station + Scanner** (dual-entity — 9 decant/compaction scanners on misread
rate + 10 decant stations on status/throughput with no live discrepancy feed; reconciled the 9
scan devices out of Module 7 so each device is owned by exactly one module, live data), and
**Module 9: Network / Comms** (per-shuttle comms link — 124 links scored on network downtime% from
Quadron Network status, with a today-vs-window recency spike, aisle-clustering, and cross-feature
flags into Shuttle + the meta layer, live data), **Module 10: Controller / Compute** (the
controller compute node — CPU utilization% from CPU Stats, current-state so the store provides
sustained-high + trend, with a system-wide `meta` cross-flag, live data), and **Module 11:
System-Wide Anomaly (Meta)** (the final module — a store-only correlation layer, no Grafana fetch,
scoring per-aisle + system **compound-risk** from module co-occurrence + realized causal chains +
persistence over the other modules' verdicts and cross-flags) are complete — **the module set is
now COMPLETE (11/11)**. See [`pdm_notebook.md`](pdm_notebook.md) for the full book and
[`CLAUDE.md`](CLAUDE.md) for durable conventions.

---

## Documentation

Full guides live under [`docs/`](docs/) (and are compiled into a single Word notebook):

| Doc | For |
|-----|-----|
| [System Overview](docs/SYSTEM_OVERVIEW.md) | What it is, how it's built, what it tracks, the value it adds |
| [Operator SOP](docs/OPERATOR_SOP.md) | Running + monitoring day to day (regular/interval tasks, navigation) |
| [Hosting Resources](docs/HOSTING_RESOURCES.md) | Machine spec, DB-size projection, LAN/firewall, backup |
| [Developer Guide](docs/DEVELOPER_GUIDE.md) | Architecture, adding a module, DB backup/export/migration workflow |
| [URL / Route Map](docs/URL_MAP.md) | Every dashboard page + JSON endpoint |
| [Dashboard UI & Graphical Overview](docs/DASHBOARD_UI.md) | The Overview tabs, every fleet chart + its data, and the offline SVG chart rules |
| [Per-Module Health Methodology](docs/MODULE_METHODOLOGY.md) | Panels → fields → algorithm, per module |
| [PdM Methodology](docs/notebook/methodology.md) | The shared scoring philosophy (+ §12 audit invariants) |
| [Audit & Hardening Report](docs/AUDIT_REPORT.md) | The Session-12 correctness/methodology/RCA audit + fixes |
| **[ASRS_PdM_Notebook.docx](docs/ASRS_PdM_Notebook.docx)** | The compiled Word notebook (rebuild: `python scripts/build_notebook.py`) |
| **[ASRS_PdM_Executive_Summary.docx](docs/ASRS_PdM_Executive_Summary.docx)** | Weekly stakeholder progress report — charts/diagrams from live data (rebuild: `python scripts/build_exec_summary.py`) |

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

- **Overview** — two tabs: **Module Health** (one tile per module: worst-component status,
  last run) and **Graphical Overview** (fleet analytics — health trend, status donut,
  per-module risk breakdown, health-score distribution, an aisle × module risk heatmap, top
  at-risk components, and time-to-maintenance; all dependency-free SVG, offline on the LAN).
  Pick a **window** (top-right) and **Run PdM (all)**, or run a single module from its tile.
- **Per-module page** (`/module/lift`, `/module/shuttle`, `/module/conveyor`, `/module/tracker`, `/module/gate`, `/module/bin_mech`, `/module/gtp_station`, `/module/decant_station`, `/module/network`, `/module/controller`, `/module/meta`) —
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
The active store is **CSV** under **`database/store/`** — one file per table, mirroring the
MySQL schema. All plant data lives in the single **`database/`** folder (`DATA_DIR=database`),
which also holds `analytics/` (tidy, analysis-ready extracts for trends/EDA/ML — see
[`database/README.md`](database/README.md)), `raw/` (per-run gzipped snapshots of the raw
fetched Grafana data — toggle with `RAW_CAPTURE`), `archive/`, and `exports/`. **MySQL is
intentionally not used until permission is granted.** The schema is designed in
`db/schema.sql` and a dormant MySQL backend exists; switching is `STORAGE_BACKEND=mysql`
+ `MYSQL_CONFIRM=ENABLE` (and the real DB name) — no application-logic changes.

Build the analysis-ready extracts (read-only on the store; re-run after PdM runs):
```bash
python scripts/build_analytics_dataset.py   # -> database/analytics/
```

---

## Deploy with Docker (another PC)

The whole system ships as **one container** (dashboard + automation). This is the
recommended way to run it on a delivery/plant PC. The example host below is
**`192.168.27.132`** — substitute your machine's LAN IP.

### 0. Prerequisites (on the target PC)
- **Docker** with the Compose plugin.
  - **Windows:** install **Docker Desktop** (uses the WSL 2 backend). Ensure it's running.
  - **Linux:** `docker` engine + `docker compose` plugin.
- Network line-of-sight from this PC to the **Grafana server** on the LAN (the container
  fetches panels outbound). No inbound internet needed.

### 1. Copy the project to the PC
Clone the repo or copy the project folder to `192.168.27.132` (e.g. `C:\PdM\PDM_LKT`).
Everything needed is in the folder; the CSV data and `.env` are **not** in git — you create
`.env` in the next step.

### 2. Create `.env` (secrets + Grafana URL)
`.env` is read at runtime (via `env_file`), never baked into the image. From the project root:
```bash
cp .env.example .env
```
Then edit `.env` and set at least:
- `GRAFANA_BASE_URL`, `GRAFANA_USERNAME`, `GRAFANA_PASSWORD`
- the `*__DASHBOARD_NAME` module dashboard URLs (per module)
- keep `STORAGE_BACKEND=csv` and `RAW_CAPTURE=true` (defaults)

`DATA_DIR`/`LOG_DIR`/`APP_HOST`/`APP_PORT` are set for you by `docker-compose.yml` — no need to change them.

### 3. Build & start
From the project root (where `docker-compose.yml` is):
```bash
docker compose up -d --build
```
First build downloads the Playwright/Chromium base image (~1–2 GB) and installs deps — a few
minutes. Subsequent starts are instant.

### 4. Verify
```bash
docker compose ps                 # STATUS should become healthy
docker compose logs -f pdm        # watch startup ("application started", modules registered)
curl http://localhost:8800/api/health
```

### 5. Open it on the LAN
From any device on the same subnet: **`http://192.168.27.132:8800`**.
On the host PC itself: `http://localhost:8800`.

Open the port in the host firewall so other machines can reach it:
- **Windows** (PowerShell, as Administrator):
  ```powershell
  New-NetFirewallRule -DisplayName "ASRS PdM 8800" -Direction Inbound -Protocol TCP -LocalPort 8800 -Action Allow
  ```
  Find the PC's IP with `ipconfig` (the `192.168.x.x` IPv4 address).
- **Linux:** `sudo ufw allow 8800/tcp` (if `ufw` is active).

### Where the data lives
`docker-compose.yml` **bind-mounts** the data to host folders next to the project, so it
survives restarts/rebuilds and is easy to back up or analyse:
- `./database/` — the CSV store (`store/`), raw per-run snapshots (`raw/`), analytics
  extracts (`analytics/`), `archive/`, `exports/`.
- `./logs/` — structured JSON logs.

Automation runs **inside the container**, independent of any browser — closing the dashboard
never stops scheduled runs; only stopping the container does.

### Day-to-day operations
```bash
docker compose stop               # pause (keeps data)         | docker compose start
docker compose restart pdm        # restart the app
docker compose logs -f pdm        # tail logs
docker compose down               # stop & remove the container (data stays in ./database)
git pull && docker compose up -d --build   # update to a new version
# rebuild the analytics extracts inside the container:
docker compose exec pdm python scripts/build_analytics_dataset.py
# back up the data: just copy the ./database folder (and .env, stored separately/securely)
```

> Notes: keep `.env` out of version control (it holds the Grafana password). On Linux,
> bind-mounted files are created as `root`; adjust ownership if needed. MySQL remains
> dormant — this deployment is CSV-only.

---

## Developer guide

### Architecture
```
core/      config, structured logging, Grafana auth/fetch/inspect, storage
           abstraction (CSV active / MySQL dormant), module registry, runner,
           scheduler, audit.
modules/   one self-registering plugin per equipment type (lift, shuttle, conveyor, tracker, gate,
           bin_mech, gtp_station, decant_station, network, controller, meta) — 11/11, set complete.
           meta is a store-only correlation layer (no Grafana source).
webapp/    FastAPI app, JSON API, services, exporting, templates, static.
db/        MySQL schema (designed).
docs/      the PdM book (notebook chapters + mapping).
database/  CSV store (gitignored): store/ live tables + analytics/ (trend/EDA/ML
           extracts) + archive/ + exports/. Data dictionary: database/README.md.
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
- `scripts/build_analytics_dataset.py` — build tidy trend/EDA/ML CSV extracts from the
  store into `database/analytics/` (universal time-series + per-module feature matrices +
  data dictionary). Read-only; safe to re-run.
- `scripts/build_exec_summary.py` — build the weekly Executive Summary (`docs/ASRS_PdM_Executive_Summary.docx`):
  renders charts + architecture/workflow diagrams from the live analytics data and lays out a
  ~5-page stakeholder report. Re-run each week after refreshing the analytics.
- `scripts/discover_dashboards.py` — log in + list/match dashboards via `/api/search`.
- `scripts/inspect_<module>.py` — enumerate (`meta`) + sample (`sample`) panels
  (`inspect_lift.py`, `inspect_shuttle.py`, `inspect_tracker.py`, `inspect_gate.py`,
  `inspect_gtp.py`, `inspect_decant.py`, `inspect_network.py`, `inspect_controller.py`, …); the
  `inspect_gtp/decant/network/controller/bin/gate` scripts have a `discover` mode. `scripts/analyze_<module>_primary.py`
  deep-dives a module's primary against live data before features are written.

### Tooling
- Tests/scratch under `tests/`. Logs at `logs/app.log.jsonl` (JSON lines).
- Never run git here (the user manages the repo). Never use MySQL without permission.
- Docker-ready by design (env-driven config, healthcheck, persistent data volume).
