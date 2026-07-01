# Hosting Resources — what it takes to run the ASRS PdM system

> **Audience:** whoever provisions and maintains the host machine (and, later, the MySQL
> database). Covers the machine spec (CPU / RAM / disk), the **database-size projection**
> (measured, not guessed), network/firewall needs, and the software footprint.
>
> **Deployment shape:** one on-premise PC on the company LAN runs a single Python process
> that serves the web dashboard **and** the automation scheduler. It reaches out only to
> the Grafana server (and, once enabled, a local MySQL). No public hosting, no cloud, no
> GPU. See [System Overview](SYSTEM_OVERVIEW.md) and [Operator SOP](OPERATOR_SOP.md).

---

## 1. Machine spec (recommended)

| Resource | Minimum | Recommended | Why |
|----------|---------|-------------|-----|
| **CPU** | 2 cores | **4 cores** | Fetching is I/O-bound (waiting on Grafana); scoring is light numpy/pandas. No GPU, ever. |
| **RAM** | 4 GB | **8 GB** | Baseline Python ~150–300 MB; Chromium (Playwright) spikes ~300–700 MB during a fetch; pandas transiently holds the largest fetch (Conveyor ~65 k rows, Bin history ~27 k rows). 8 GB leaves comfortable headroom. |
| **Disk** | 50 GB free | **100–256 GB SSD** | OS + venv + Chromium (~500 MB) + the growing PdM store + archives/exports. SSD makes the CSV backend and (later) MySQL snappy. See §3 for the store growth. |
| **OS** | Windows 10/11, macOS 12+, or Linux | any of these | Developed/tested on macOS (Darwin) + Python 3.14; Windows is a first-class target for the plant PC. |
| **Python** | 3.11+ | 3.11–3.14 | Pure-Python + numpy/pandas/scikit-learn; no native build chain needed beyond wheels. |

The machine is **idle between runs** — it only works during a fetch+score cycle (seconds
to ~1 minute per module, see below), then sleeps until the next scheduled trigger. A
modest office PC is plenty.

### Per-run compute cost (observed)
| Module | Fetch time | Rows fetched | Notes |
|--------|-----------:|-------------:|-------|
| Controller | ~1.8 s | 1 | smallest/fastest |
| Network | ~8 s | ~224 | |
| Gate | ~5–6 s | ~75–85 | |
| Decant | ~13–14 s | ~289 | |
| Tracker | ~15–20 s | ~86 | |
| Lift | ~20–35 s | ~4.8 k | |
| Shuttle | ~20–35 s | ~320–350 | |
| GTP | ~33–37 s | ~1,750 | largest population scored |
| Conveyor | ~30–60 s | ~65 k | heavy live timeseries |
| Bin | ~5–8 s | ~27 k | frozen history log |
| Meta | ~0.3 s | ~770 (store read) | **no Grafana fetch** |

A full **"Run all"** is dominated by Playwright CSV downloads (~3–5 s/panel), not by
scoring. Scoring all ~770 components is sub-second. Peak RAM during a run is Chromium +
the single largest DataFrame, not the sum of all modules.

---

## 2. Software footprint

- **Python venv** with `requirements.txt` (FastAPI, Uvicorn, APScheduler, Playwright,
  httpx, numpy, pandas, scikit-learn, PyYAML, python-dotenv). Pure wheels; no compiler
  needed on mainstream platforms.
- **Playwright Chromium** — one browser download (~150–300 MB on disk) via
  `playwright install chromium`, done once; runs headless and offline thereafter.
- **`python-docx`** — only needed to (re)build the Word notebook (`scripts/build_notebook.py`);
  not required to run the PdM system.
- **No runtime CDN / internet** — the frontend uses vendored JS/CSS so the dashboard
  works fully on an air-gapped LAN.
- **Docker-ready** — a `Dockerfile` + `docker-compose.yml` exist for client delivery
  (env-driven config, healthcheck on `/api/health`, a persistent `data/` volume).

---

## 3. Database-size projection (the store)

The **`component_health`** table is the longitudinal store and ~95 %+ of all growth. Every
other table is negligible by comparison.

### Measured row size
The live CSV store gives a real number: **`component_health` averages ≈ 1.6 KB per row**
(each row carries `rca_json` + `metrics_json`). Under MySQL/InnoDB with the JSON columns
and the `(module, component_id, created_at)` index, plan for **≈ 2 KB per row effective**
(row + index + overhead).

### Rows written per full "Run all" (all 11 modules)
≈ **769** `component_health` rows (Lift 16, Shuttle 124, Conveyor 6, Tracker ~54, Gate 52,
Bin ~40, GTP ~326, Decant 19, Network 124, Controller 1, Meta 7) — plus 11 `pdm_run`, 1
`trigger_log`, a couple of `event_log`, and `panel_catalog` upserts (which **replace**, so
they don't grow). Anomaly-set modules (Tracker, Bin) vary run-to-run with the number of
currently-faulting units.

### Growth by automation interval
| Interval | `component_health` rows/day | rows/year | Store size/year (CSV @1.6 KB) | Store size/year (MySQL @2 KB) |
|----------|-----------:|-----------:|------------------------------:|------------------------------:|
| every 4 h | ~4,600 | ~1.7 M | ~2.7 GB | ~3.4 GB |
| **hourly (typical)** | **~18,500** | **~6.7 M** | **~10.8 GB** | **~13.5 GB** |
| every 15 min | ~74,000 | ~27 M | ~43 GB | ~54 GB |

Other tables per year at hourly cadence: `pdm_run` ≈ 96 k rows (~30 MB), `trigger_log` ≈
9 k rows (~4 MB), `event_log` ≈ 20–40 k rows (~10 MB). Combined they are **< 1 %** of the
`component_health` volume.

### Practical guidance
- **Hourly automation** — the recommended default — produces ~**13.5 GB of MySQL per
  year**. A **50–100 GB** disk holds **3–7 years** of full-resolution history plus
  archives/exports.
- To bound growth without losing signal, use the **Storage** page's **archive** (move old
  rows to `data/archive/`) or **delete-by-range**. A common policy: keep ~90 days at full
  resolution live, archive the rest.
- **GTP** (~326 rows/run) and **Shuttle/Network** (124 each) are the biggest writers. If
  the store grows faster than desired, tighten those scopes' intervals or archive them
  first — they dominate the row count.
- The `(module, component_id, created_at)` index keeps per-component trend/RUL queries
  fast even as the table reaches tens of millions of rows.

### MySQL instance sizing (when enabled — currently dormant)
This is an **append-mostly, indexed-range-scan** workload — light for MySQL.
- **InnoDB buffer pool:** 1–2 GB is ample (the hot set is recent rows per component).
- **CPU/RAM for MySQL:** it can share the host PC; if separated, 2 vCPU / 4 GB RAM is
  plenty. Disk per the projection above.
- **Charset:** utf8mb4; datetimes are stored as ISO-8601 strings for parity with CSV
  (lexicographic range filters + ordering) — see [`db/schema.sql`](../db/schema.sql).
- MySQL stays **off until explicitly enabled** (`STORAGE_BACKEND=mysql` +
  `MYSQL_CONFIRM=ENABLE` + the real DB name). Switching backends changes **no application
  code**. Migrating the accumulated CSV history into MySQL is a one-command job — see
  [Developer Guide → DB migration/export](DEVELOPER_GUIDE.md#database-full--back-up--export-to-another-database).

---

## 4. Network & firewall

| Flow | Direction | Port | Notes |
|------|-----------|------|-------|
| Dashboard / API | **inbound** to the host | `APP_PORT` (default **8800**) | LAN only. Allow inbound TCP 8800 in the host firewall for other devices to reach it. |
| Grafana fetch | **outbound** from the host | Grafana's port (usually 443/80/3000) | To `GRAFANA_BASE_URL` only. Playwright login + JSON API + CSV download. |
| MySQL (when enabled) | outbound from the host | `DB_PORT` (default **3306**) | To the local DB host only. Dormant until permitted. |
| Internet | — | — | **None required.** No public hosting, no CDN, no external calls beyond Grafana/MySQL. |

- **Bind address:** `APP_HOST` defaults to `0.0.0.0` (all interfaces) so LAN devices can
  reach it; set it to a specific interface IP to restrict further.
- **Firewall setup:** Windows → inbound rule for TCP 8800; macOS → System Settings →
  Network → Firewall → allow the Python binary / port; Linux → `ufw allow 8800/tcp`.
- **Same-subnet only** — reach it at `http://<host-ip>:8800`. There is deliberately no
  authentication layer because access is confined to the trusted plant LAN; if you ever
  expose it more widely, put it behind a reverse proxy with auth (out of current scope).
- **Healthcheck:** `GET http://<host-ip>:8800/api/health` (used by Docker + monitoring).

---

## 5. Backup & retention

- **What to back up:** the entire **`data/`** directory (the CSV store, archives, and
  exports) — that is the whole longitudinal history. Plus **`.env`** (secrets/URLs) stored
  securely and separately.
- **How often:** a nightly copy/snapshot of `data/` is sufficient (append-mostly, so
  incremental backups are cheap).
- **When on MySQL:** use normal DB backups (`mysqldump` / snapshots) of the PdM database;
  the `scripts/db_migrate_export.py` tool also produces portable per-table exports and can
  copy the whole store into a fresh database when one fills up (see the Developer Guide).
- **Retention policy suggestion:** live = last 90 days at full resolution; archive older
  rows monthly; keep archives on the backup target. Confidence and trend RUL only need a
  few dozen snapshots per component, so archiving old rows never hurts prediction quality.

---

## 6. Sizing cheat-sheet

- **Typical plant PC (4 cores / 8 GB / 256 GB SSD)** running **hourly** automation:
  comfortably handles all 11 modules with **years** of history headroom.
- **Rule of thumb:** `MySQL GB/year ≈ (runs/day) × 769 × 2 KB × 365`. Hourly ⇒ ~13.5 GB/yr.
- **Scale knob:** growth is ~linear in `Σ components × runs/day`. Halve the interval →
  double the growth. Archive/delete by range to cap it.
