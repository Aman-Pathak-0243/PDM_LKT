# CLAUDE.md — Durable conventions for the ASRS Predictive Maintenance system

> **Read this first, every session.** Then read `pdm_notebook.md`,
> `docs/mapping/module_dashboard_mapping.md`, and every existing
> `modules/*/README.md`. Those four sources recover full project context.
> This file is the contract; it changes rarely and deliberately.

---

## 0. What this project is

A **Predictive Maintenance (PdM)** system for a **six-aisle ASRS** at a Lenskart
fulfilment plant. It infers equipment health **purely from Grafana operational +
error data** (there is **no maintenance logbook**) and predicts, per physical
component, whether maintenance is needed, when, and why.

Built **one module at a time, each in its own Claude Code session.** A module =
a self-registering package under `modules/<name>/`. The first module is **Lift**;
the build order for this project is Lift → Shuttle → … (see the mapping file's
build sequence; note this project does Lift first per the kickoff prompt).

The grounding chapter on the physical system is `docs/notebook/01_intro_to_asrs.md`
— read it to understand aisles, lifts, buffers, totes, and the WES.

---

## 1. Hard rules (do not violate)

1. **Never run git.** No `git init/add/commit/push`. The user manages the repo and
   does not want Claude in the contributors list. At session end only *print* a
   one-line commit message.
2. **Never use MySQL until the user explicitly grants permission.** MySQL is
   reachable but off-limits. The active storage backend is **CSV** (`STORAGE_BACKEND=csv`).
   The MySQL schema is designed (`db/schema.sql`) and a dormant MySQL backend
   exists, but it must not connect until permission is given. The exact DB name
   will be shared after the Lift + Shuttle modules. **All data persists to CSV
   datasets under `database/` (the single CSV store folder, `DATA_DIR=database`).**
   Analysis-ready extracts for trends/EDA/ML (tidy time-series + per-module feature
   matrices) are generated under `database/analytics/` by
   `scripts/build_analytics_dataset.py`; the data dictionary is `database/README.md`.
3. **Read `.env` for secrets and dashboard URLs. Never hardcode credentials.
   Never print the password** (not in logs, not in terminal output, not in docs).
4. **Local/LAN only.** The app runs on one company PC, reachable only on company
   WiFi/LAN. No public hosting. No external network calls except to
   `GRAFANA_BASE_URL` and (when permitted) the local MySQL.
5. **Always ignore `ignore.txt`.** Never read, edit, or reference it.
6. Use **Playwright (Chromium, Python)** for all Grafana CSV fetching
   (username+password login). Reuse the authenticated cookie for JSON API calls.
7. **Cross-module sync.** When a fetched panel is relevant to another module,
   update that module's code AND README AND the mapping markdown the same session.
8. **Docs ship with code, every session.** Documentation is not optional.

---

## 2. Tech stack

- **Python 3.11+** (developed on 3.14) in a `.venv`; deps in `requirements.txt`.
- **Fetching:** Playwright (Chromium) + httpx (authenticated JSON API).
- **Backend:** FastAPI + Uvicorn. **Scheduler:** APScheduler (in-process, time-triggered).
- **Frontend:** server-rendered Jinja2 templates, vendored JS charts (no runtime CDN),
  offline-capable on a LAN PC.
- **Modelling:** numpy / pandas / scikit-learn. No GPU, no heavy deps.
- **Storage:** abstraction layer (`core/storage/`) — **CSV backend active**, MySQL
  backend dormant behind `STORAGE_BACKEND`. Schema mirrored in `db/schema.sql`.

---

## 3. Repository layout

```
core/                  shared, module-agnostic infrastructure
  config.py            load + validate .env, resolve paths
  logging_setup.py     structured JSON logging (file + console)
  grafana_auth.py      Playwright login -> reusable session/cookies
  grafana_fetcher.py   panel CSV via &inspect=<id>&inspectTab=data + Download CSV
  panel_inspector.py   enumerate panels from dashboard JSON API; sample + describe
  storage/             storage abstraction (CSV now, MySQL later)
    base.py            StorageBackend interface + dataset schema definitions
    csv_backend.py     CSV implementation (active)
    mysql_backend.py   MySQL implementation (dormant, gated by permission)
    __init__.py        get_storage() factory reading STORAGE_BACKEND
  registry.py          module plugin registry (modules self-register)
  scheduler.py         APScheduler: time-triggered PdM runs (automation)
  runner.py            PdM run orchestration: fetch -> features -> health -> persist
modules/<name>/        one self-registering module per equipment type
  __init__.py          registers the module in core.registry
  README.md            the module's notebook chapter (panels, features, formulas)
  module.yaml          resolved panel mapping + data window + thresholds
  fetch.py             which dashboards/panels this module consumes
  features.py          raw + derived feature extraction
  health.py            per-component health score + risk tier + time-to-maintenance
  rca.py               root-cause attribution per flagged component
webapp/                FastAPI app: main dashboard + per-module pages + APIs
db/schema.sql          MySQL schema (designed; applied only once permitted)
docs/                  the PdM book (notebook chapters + mapping)
database/              CSV data store (gitignored): store/ (live tables) + analytics/
                       (tidy trend/EDA/ML extracts) + raw/ (per-run gzipped raw fetched
                       panel data, RAW_CAPTURE) + archive/ + exports/; see database/README.md
logs/                  structured logs (gitignored)
```

**Plugin rule:** adding a module requires **no edits to `core/`** — only creating
`modules/<name>/` and importing it so it self-registers. The main dashboard
discovers modules from the registry.

---

## 4. Grafana fetch mechanics

- **Login:** Playwright opens `${GRAFANA_BASE_URL}/login`, fills
  `GRAFANA_USERNAME_SELECTOR`/`GRAFANA_PASSWORD_SELECTOR`, clicks
  `GRAFANA_SUBMIT_SELECTOR`. Persist storage state/cookies for reuse within a run.
- **Panel enumeration (metadata):** parse the `uid` from `/d/<uid>/<slug>`. Call
  `GET ${GRAFANA_BASE_URL}/api/dashboards/uid/<uid>` (reuse cookie). Read every
  panel's `id`, `title`, `type`, field/column names, and the SQL/query target.
  Never guess `inspect=N` — derive panel IDs from this model.
- **Dashboard discovery:** `GET /api/search` lists all dashboards (uid, title,
  folder). Use it to locate a module's dashboards by name and confirm with the user.
- **Panel data (CSV):** build `${dashboardURL}&inspect=<panelId>&inspectTab=data`,
  open with Playwright, activate the Data tab, click the button whose text is
  `GRAFANA_DOWNLOAD_BUTTON_TEXT`, capture the download, load into pandas.
- **Template variables:** leaving aisle/level/Lift/Tracker/Shuttle vars empty
  returns the full dataset. Support `&var-<Name>=<value>` overrides; default empty.
- **Time window:** always parameterise `from`/`to` (Grafana-style `now-2d`, etc.).
  Default `FETCH_DEFAULT_WINDOW`. Nothing hard-codes 2 days.
- **Sampling:** `panel_inspector` pulls a small slice first to list fields/rows so
  relevance can be judged cheaply before fetching the full window.

---

## 5. Per-module SOP (follow exactly each session)

1. **Load context** — CLAUDE.md, pdm_notebook.md, mapping, all module READMEs.
   For the target module, list mapped dashboards AND scan the whole mapping for
   other dashboards carrying this module's signals.
2. **Get dashboard links** — discover candidates via `/api/search`, confirm with
   the user, and write the full URLs into `.env` under `MODULE__DASHBOARD_NAME` keys.
3. **Enumerate panels** for each dashboard via the JSON API (id/title/type/fields/SQL).
4. **Sample each panel** (small slice). Decide relevance; write the verdict +
   reasoning into the module README and Chapter 2. Mark action/write panels
   (e.g. `update_bin_block`) as non-signal and skip.
5. **Resolve `module.yaml`** — concrete {dashboard, panelId, role, fields}, plus the
   module's default data window and thresholds.
6. **Build features** (`features.py`) — raw + derived; document each formula.
7. **Build health** (`health.py`) — per-component score, risk tier, predicted
   time-to-maintenance, confidence, prediction regime. Document the formula.
8. **Build RCA** (`rca.py`) — dominant contributing signals per flagged component.
8b. **Methodology (required)** — give the module class a `methodology` dict (summary,
   `signals`, `entity_verdict` steps, `formulas`). It is served at
   `/api/modules/<name>/methodology` (merged with the shared overall-status rollup in
   `core/registry.py`) and rendered as an in-page "Methodology" section, so the page
   itself explains how each component's verdict AND the module's overall status are reached.
9. **Persist** — a PdM run writes `pdm_run` + per-component `component_health`
   rows (to CSV now; same schema as `db/schema.sql`).
10. **Wire into webapp** — register module; add its module page; surface on main dashboard.
11. **Cross-module check** — propagate any panel useful elsewhere (code + README + mapping).
12. **Update docs** — module README, Chapter 2, data-volume chapter, methodology,
    main README, `pdm_notebook.md` index.
13. **Session-end protocol** (§8).

---

## 6. PdM methodology (see `docs/notebook/methodology.md`)

- Health inferred **purely from operational + error data**. No logbook dependency.
- **Per-component scoring.** Each physical unit (each lift, id e.g.
  `aisle_04_inbound_lift_02`) gets: health score (0–100), risk tier
  (`ok`/`watch`/`warn`/`critical`), estimated time-to-maintenance (hours/days),
  confidence, and an RCA.
- **2-day window design.** Most dashboards retain ~2 days. Signals are built to
  work short-window: error/fault **rate**, error-code mix, fault recurrence on the
  same unit, time-between-faults, deviation from the unit's own baseline and from peers.
- **The store overcomes the 2-day limit.** Every PdM trigger snapshots each
  component's metrics. Over runs this accumulates a longitudinal history far longer
  than any single fetch. **Cold-start** (little history) → coarse rate/anomaly tiers,
  low confidence. As history grows → trend/regression RUL, rising confidence. Always
  label the `prediction_regime` (`coldstart` | `trend`).
- **Scalable window.** Larger `from=now-<window>` ⇒ sharper predictions; nothing
  hard-coded to 2 days.
- **Optional operator acknowledgement.** Marking a component serviced only
  annotates/silences a flag and resets its baseline; it never drives detection.

---

## 7. Storage & schema

- Persistence goes through `core/storage`. **CSV is the active backend.** Datasets
  mirror the MySQL tables 1:1 so switching to MySQL later changes no calling code.
- Core datasets/tables (`db/schema.sql` is the source of truth for columns):
  - `pdm_run` — one row per PdM run (module, trigger_type, window, timing, status, counts).
  - `component_health` — **the longitudinal store**; one row per component per run
    (health_score, risk_tier, predicted_ttm_hours, confidence, prediction_regime,
    primary_cause, rca_json, metrics_json). Indexed `(module, component_id, created_at)`.
  - `panel_catalog` — machine-readable twin of Chapter 2 (dashboard/panel/fields/SQL/is_signal).
  - `automation_config` — per-scope (`global` or module) automation enable/interval/window.
  - `maintenance_ack` — optional operator acknowledgements only.
  - `trigger_log` / `event_log` — trigger execution records and structured app events.
- Timestamps are stored in UTC ISO-8601. JSON columns hold flexible metadata so the
  schema stays AI/ML- and analytics-friendly (no design that blocks future
  forecasting, embeddings, or warehouse export).

---

## 8. Session-end protocol

When the module works end-to-end and all docs are updated:
1. Run the end-of-session verification checklist (business logic, algorithms,
   queries/dataset writes, fetch integration, plugin/registry health, performance,
   exception handling, logging, security, scalability) and report results.
2. Print `done master`.
3. Print a single-line conventional commit message
   (e.g. `feat(lift): add lift PdM module, Grafana fetch core, CSV storage, dashboard`).
4. Print the **next session's kickoff prompt** (short; relies on this file; names the
   next module = **Shuttle**; tells the new session to read CLAUDE.md +
   pdm_notebook.md + mapping + module READMEs, then follow the §5 SOP).
5. **Do not run git.** Remind the user to review and commit themselves.

---

## 9. Web app contract

**Automation independence (critical):** automation runs in the terminal process
(APScheduler), **independent of the dashboard**. Closing the browser/dashboard must
never stop background jobs, scheduled runs, automation, or trigger monitoring. Only
stopping the service (Ctrl-C / killing the process) halts automation. Reopening the
dashboard reconnects to the running app without interrupting anything.

**Main dashboard:** Grafana-style duration control; module health overview (one tile
per registered module, worst-component status, last-run time); "Run PdM now" manual
trigger; automation control (enable/disable + interval + window, persisted, with
"next trigger at…"). Manual and automatic triggers coexist.

**Per-module dashboard:** per-component health/tier/TTM/confidence; RCA per flagged
component; historical trend from `component_health`; optional "Mark maintenance done".

**Plus (from the master development prompt):** dashboards for system status,
automation, PdM triggers, logs (searchable), storage management, database/store
health, performance metrics, active/failed jobs, scheduling, plugin management,
settings. Every trigger is traceable (id, type, status, duration, counts, retries,
logs). Structured logging everywhere.

**Storage Management section:** total/used/remaining store size, per-dataset sizes &
record counts, growth stats, backup/health status; download by date range / trigger /
table / filtered set, export CSV/JSON/Excel (SQL when MySQL is live); delete by
date/trigger/selection with confirmation + logging; archive + restore.

All endpoints bind `APP_HOST:APP_PORT`. README notes Windows/Mac firewall + same-subnet access.

---

## 10. Quality bar

Clean architecture, SOLID, DRY, KISS, high cohesion / low coupling, input
validation, type hints, secure coding (no secret leakage), structured logging,
graceful exception handling, and Docker-ready (Dockerfile + compose + healthcheck +
volumes) for client delivery. Every change leaves the project more stable and
maintainable than before. Behave like a senior engineering team, not a code generator.
