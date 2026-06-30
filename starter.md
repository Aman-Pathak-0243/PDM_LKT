# Claude Code Kickoff Prompt — Predictive Maintenance System (Session 1: Lift)

> Paste everything below the line into a fresh Claude Code session opened in
> `/Users/amanpathak/Documents/Lenskart/Projects/predictive maintenance`.

---

You are building a **Predictive Maintenance (PdM) system** for a six-aisle ASRS at a Lenskart fulfilment plant. We build it **one module at a time, each in its own Claude Code session**. This session builds the **shared infrastructure + the FIRST module: LIFT**. Everything must be production-grade, well-documented, and self-describing so a future maintainer can read a chapter per module and understand it fully.

Work in the current directory: `/Users/amanpathak/Documents/Lenskart/Projects/predictive maintenance`. I have already placed the module↔dashboard mapping markdown here (or I will paste it now). Read it before doing anything.

## 0. Hard rules (do not violate)

1. **Never run git.** Do not `git init`, `git add`, `git commit`, or `git push`. I manage the repo myself and do not want Claude in the contributors list. At session end you only *print* a one-line commit message for me to use.
2. At the very end of the session, after everything works and docs are updated, print exactly: `done master`, then the one-line commit message, then the ready-to-paste kickoff prompt for the **next** module's session.
3. Read `.env` for secrets and dashboard URLs. Never hardcode credentials. Never print the password.
4. **Local-only deployment.** The web app runs on one company PC and is reachable only on the company WiFi/LAN. No public hosting, no external calls except to `GRAFANA_BASE_URL` and the local MySQL.
5. Use **Playwright** (Python) for all Grafana data fetching (username+password login).
6. When you finish discovering panel data, **check whether that data is also relevant to other modules.** If yes, update that module's code AND its README AND the mapping markdown. Keep all docs in sync every session.
7. Documentation is not optional. Code and docs ship together in the same session.

## 1. First action — create `CLAUDE.md`

Before writing app code, create `CLAUDE.md` at the repo root capturing the durable conventions below so **every future session inherits them**. Summarise sections 0–9 of this prompt into it (rules, architecture, fetch mechanics, per-module SOP, PdM methodology, DB schema, web app contract, documentation system, session-end protocol). Future sessions will read `CLAUDE.md` + `pdm_notebook.md` + the mapping markdown + all existing module READMEs to recover full context.

## 2. Tech stack

- **Language:** Python 3.11+. Use a virtualenv (`.venv`) and `requirements.txt`.
- **Fetching:** Playwright (Chromium). Reuse the authenticated session cookie for Grafana HTTP API calls.
- **Storage:** MySQL (driver: `mysqlclient` or `PyMySQL` + SQLAlchemy). Schema in `db/schema.sql`, applied idempotently on startup.
- **Backend:** FastAPI + Uvicorn. **Scheduler:** APScheduler (in-process, time-triggered).
- **Frontend:** server-rendered templates (Jinja2) or a light React build — your call, but keep it simple, dependency-light, and runnable offline on a LAN PC. Charts via a vendored JS lib (no CDN at runtime).
- **Modelling:** numpy / pandas / scikit-learn. No GPU, no heavy deps.

## 3. Repository structure (create this)

```
predictive maintenance/
├── .env                      
├── .env.example              
├── .gitignore                # ignore .env, .venv, __pycache__, data/, *.csv caches, node_modules
├── CLAUDE.md                 # durable conventions (you create in step 1)
├── README.md                 # MAIN readme: operator guide + developer guide (keep updated every session)
├── pdm_notebook.md           # MASTER INDEX of the PdM book (links every chapter + module README)
├── requirements.txt
├── docs/
│   ├── mapping/
│   │   └── module_dashboard_mapping.md     # the file I paste; you keep it in sync
│   └── notebook/
│       ├── 01_intro_to_asrs.md             # Chapter 1 — seed content provided in §10
│       ├── 02_grafana_dashboards.md        # Chapter 2 — panels/types/fields/why; grows each session
│       ├── 03_data_volume.md               # Chapter — daily data volume per dashboard/panel
│       └── methodology.md                  # PdM methodology, cold-start, scalability, confidence
├── core/                     # shared, module-agnostic infrastructure
│   ├── config.py             # load .env
│   ├── grafana_auth.py       # Playwright login -> reusable session/cookies
│   ├── grafana_fetcher.py    # panel CSV via &inspect={id}&inspectTab=data + Download CSV
│   ├── panel_inspector.py    # enumerate panels from dashboard JSON API; sample + describe fields
│   ├── db.py                 # engine, schema apply, run/health/ack writers + readers
│   ├── registry.py           # module plugin registry (modules self-register)
│   └── scheduler.py          # APScheduler: time-triggered PdM runs
├── modules/
│   └── lift/
│       ├── __init__.py       # registers the module in core.registry
│       ├── README.md         # the LIFT chapter — comprehensive (panels, features, formulas, health, RCA)
│       ├── module.yaml       # resolved panel mapping + data window + thresholds (you populate after inspection)
│       ├── fetch.py          # declares which dashboards/panels this module consumes
│       ├── features.py       # raw + derived feature extraction
│       ├── health.py         # per-component health score + risk tier + predicted time-to-maintenance
│       └── rca.py            # root-cause attribution per flagged component
├── webapp/
│   ├── main.py               # FastAPI app: main dashboard + per-module pages + APIs
│   ├── templates/
│   └── static/
└── db/
    └── schema.sql
```

A new module = a new `modules/<name>/` package that self-registers. Adding it must require **no edits** to `core/` — only registration. The main dashboard discovers modules from the registry.

## 4. Grafana fetch mechanics (implement in `core/`)

**Login:** Playwright opens `${GRAFANA_BASE_URL}/login`, fills `GRAFANA_USERNAME_SELECTOR` / `GRAFANA_PASSWORD_SELECTOR`, clicks `GRAFANA_SUBMIT_SELECTOR`. Persist cookies/storage state for reuse within the run.

**Panel enumeration (metadata):** From a dashboard URL, parse the `uid` (the `/d/<uid>/<slug>` segment). Call the authenticated API `GET ${GRAFANA_BASE_URL}/api/dashboards/uid/<uid>` (reuse the login cookie). From the returned model read every panel's `id`, `title`, `type`, field/column names, and the **SQL/query target** behind it. This is how you know which panels exist, what each is, and what it queries — capture all of it for Chapter 2. Do **not** guess `inspect=N`; derive panel IDs from this model.

**Panel data (CSV):** For each relevant panel build:
`${dashboardURL}&inspect=<panelId>&inspectTab=data`
e.g. `…/d/N8QvGxQIk/daily-shuttle-errors?orgId=1&from=now-2d&to=now&inspect=2&inspectTab=data`.
Open it with Playwright, ensure the Data tab is active, click the button whose text is `GRAFANA_DOWNLOAD_BUTTON_TEXT` ("Download CSV"), capture the download, load into pandas.

**Template variables:** Some dashboards have variables (aisle, level, Lift, Tracker, Shuttle). Leaving them empty returns the full dataset (confirmed from the dashboards). Support overriding via `&var-<Name>=<value>` when a module needs filtering; default to empty/all.

**Time window:** Always parameterise `from`/`to`. The UI sends the window (Grafana-style: `now-1h`, `now-6h`, `now-24h`, `now-2d`, `now-7d`, or absolute). Default `FETCH_DEFAULT_WINDOW` (now-2d).

**Sampling:** `panel_inspector` first pulls a *small* slice of each panel to list fields and a few rows so you (and I) can judge relevance cheaply before fetching the full window.

## 5. Per-module workflow / SOP (follow this exactly, this session for LIFT)

1. **Load context.** Read `CLAUDE.md`, `pdm_notebook.md`, `docs/mapping/module_dashboard_mapping.md`, and every existing `modules/*/README.md`. For the target module, list the mapped dashboards **and** scan the whole mapping for any *other* dashboard that may carry this module's signals (for LIFT: e.g. Bad Tracker Diagnosis exposes `lift_id`, `lift_status`, `lift Status Description`).
2. **Ask me for the dashboard links.** Present an interactive question listing each dashboard name you need for this module (mapped + cross-relevant). I paste the full Grafana dashboard URLs one by one. You then **write them into `.env`** under this module's block with clear `MODULE__DASHBOARD_NAME` keys.
3. **Enumerate panels** for each dashboard via the JSON API. Record id/title/type/fields/SQL.
4. **Sample each panel** (small slice). Inspect fields. **Decide relevance** to this module; write the verdict and reasoning into the module README and Chapter 2. Mark action/write panels (e.g. `update_bin_block`, "No data" controls) as non-signal and skip them.
5. **Resolve `module.yaml`** — the concrete list of {dashboard, panelId, role(primary/secondary), fields used}, plus this module's default data window and thresholds.
6. **Build features** (`features.py`): raw fields + derived features. Document every derived feature: its formula, the panel(s)/fields it combines, and what it tells you about lift health.
7. **Build health** (`health.py`): per-component (per lift) health score, risk tier, and predicted time-to-maintenance (hours/days) + confidence. Document the formula.
8. **Build RCA** (`rca.py`): for each component flagged, the dominant contributing signals.
9. **Persist**: a PdM run writes per-component rows to MySQL (see §7). 
10. **Wire into webapp**: register the module; add its module dashboard page; surface it on the main dashboard.
11. **Cross-module check**: if any panel you pulled is useful to another module, update that module (code + README) and the mapping markdown.
12. **Update docs**: module README, Chapter 2, data-volume chapter, methodology if changed, main README, and `pdm_notebook.md` index.
13. **Session end protocol** (§9).

For step 2, use Claude Code's interactive prompt. Example question text:
> "LIFT module needs these dashboards — paste each full Grafana URL:
> 1) Lift Error History  2) QUADRON CYCLES  3) Lift_Supply_Tote  4) QUADRON ERROR HISTORY  5) Bad Tracker Diagnosis (cross-relevant: has lift columns)."
Ask for them, accept them one per line, confirm what you wrote to `.env`.

## 6. PdM methodology (encode in `docs/notebook/methodology.md` and the model)

- **Health is inferred purely from operational + error data.** There is **no maintenance logbook** and the model must not depend on one. It decides "maintenance needed / not needed" from the signals themselves.
- **Per-component scoring.** Each physical unit (each lift, identified by `lift_id` e.g. `aisle_04_inbound_lift_02`) gets: a health score (0–100), a risk tier (`ok` / `watch` / `warn` / `critical`), an estimated time-to-maintenance (hours/days), a confidence, and an RCA.
- **Works on a 2-day window.** Most dashboards retain ~2 days. Short-window signal design: error/fault **rate**, error-code mix, fault recurrence on the same unit, time-between-faults, and deviation from the unit's own baseline and from peer lifts.
- **The DB overcomes the 2-day limit.** Every PdM trigger snapshots each component's metrics to MySQL. Over successive runs this **accumulates a longitudinal history far longer than any single 2-day fetch**. Cold-start (little/no history) → coarse rate/anomaly tiers with low confidence; as run-history grows → enable trend/regression-based RUL with rising confidence. Always label which regime produced a prediction.
- **Scalable window.** If longer-retention data is available, the same pipeline ingests a larger `from=now-<window>` and produces sharper predictions. Nothing is hard-coded to 2 days.
- **Optional operator acknowledgement.** When maintenance is done, the operator *may* mark a component as serviced (acknowledged). This only annotates/silences the flag and starts a fresh post-service baseline — it never drives detection and is fully optional. No record-keeping burden.

Lift-specific signal ideas (validate against the real fields you fetch): fault frequency per lift; share of `ERROR` lift_status events; inbound vs outbound lift comparison (each aisle has one per face); recurrence of the same lift in Bad Tracker rows; correlation with cycles from QUADRON CYCLES (wear proxy); load/throughput from Lift_Supply_Tote as a stress feature; cross-feature with Quadron Network status latency if/when that module exists.

## 7. MySQL schema (in `db/schema.sql`, applied idempotently)

Design at least:
- `pdm_run(id, module, trigger_type ENUM('manual','auto'), data_window, started_at, finished_at, status, rows_fetched)`
- `component_health(id, run_id FK, module, component_id, component_type, health_score, risk_tier, predicted_ttm_hours, confidence, prediction_regime ENUM('coldstart','trend'), primary_cause, rca_json, metrics_json, created_at)` — **this table is the longitudinal store**; index `(module, component_id, created_at)`.
- `panel_catalog(id, module, dashboard_uid, dashboard_name, panel_id, panel_title, panel_type, fields_json, sql_text, is_signal BOOL, notes)` — the machine-readable twin of Chapter 2.
- `automation_config(scope, enabled, interval_minutes, data_window, updated_at)` — `scope` = 'global' or a module name.
- `maintenance_ack(id, module, component_id, acked_by, acked_at, note)` — optional acks only.

A PdM run = fetch → features → health → write `pdm_run` + `component_health` rows. The dashboards read the latest run per module/component and the history for trends.

## 8. Web app contract (`webapp/`)

**Main dashboard:**
- Grafana-style **duration control** (dropdown + quick ranges + custom from/to) that sets the data window used by fetches/runs.
- **Module health overview** — one card/tile per registered module, worst-component status, last-run time.
- **Run PdM now** — manual trigger (all modules or a chosen module) using the selected window.
- **Automation control** — enable/disable + interval + data window; persists to `automation_config`; APScheduler triggers runs on that interval. Show "next trigger at …" and "showing results as of last run until next trigger".
- Manual and automatic triggers coexist.

**Per-module dashboard:**
- Per-component (per-lift) health score, risk tier, predicted time-to-maintenance, confidence.
- **RCA** for every component flagged, with the contributing signals.
- Historical trend (from `component_health`).
- Optional **"Mark maintenance done"** per component (writes `maintenance_ack`); clearly optional.

All endpoints local/LAN. Bind `APP_HOST:APP_PORT`. Note Windows/Mac firewall + same-subnet access in the README.

## 9. Session-end protocol

When the module works end-to-end and all docs are updated:
1. Print `done master`.
2. Print a single-line conventional commit message (e.g. `feat(lift): add lift PdM module, Grafana fetch core, MySQL schema, dashboard`).
3. Print the **next session's kickoff prompt** (short — it can rely on `CLAUDE.md`; it names the next module = **Shuttle**, tells the new session to read `CLAUDE.md` + `pdm_notebook.md` + mapping + existing module READMEs, then follow the §5 SOP for Shuttle).
4. Do **not** run git. Remind me to review and commit myself.

## 10. Chapter 1 seed — Intro to the ASRS (write into `docs/notebook/01_intro_to_asrs.md`)

Use this as the basis (from the plant's ASRS Operations Review). Expand into prose; this is the maintainer's grounding chapter.

- **System:** six-aisle ASRS buffering inventory between inbound QC (IQC) and order fulfilment. Unit of movement is the **tote**, not loose items. A **WES** (warehouse execution system) coordinates every movement; barcodes on each tote face and partition give end-to-end traceability. Monitored in real time on **Grafana** (the source of all PdM data).
- **Aisles & geometry:** 6 aisles, ~70 m rack span each. Levels per aisle: aisles 1–4 = 19 (grouped 5·5·5·4), aisles 5–6 = 24 (grouped 5·5·5·5·4); level-groups are called **grounds**. Two racks per level either side of a central shuttle lane. Each rack has **deep 1** (front, shuttle side) and **deep 2** (rear).
- **Capacity:** per level = 2 racks × 113 locations × 2 deeps = **452** positions. Aisles 1–4 = 8,588 each; aisles 5–6 = 10,848 each; system gross = **56,048**. A vacancy reserve is held by design for reshuffles.
- **Shuttle:** one shuttle per aisle, telescopic forks reach both racks; deep 2 requires relocating the deep-1 tote first (reshuffle).
- **Lifts & buffers (PdM-critical for Module 1):** **two lifts and two buffers per aisle — one of each on each face** (inbound and outbound), each handling **two totes at a time**. On inbound: tote enters the inbound lane → placed on a lift → **the lift rises only once it holds two totes** → moves to a buffer → shuttle stores it. On retrieval the path reverses (shuttle → buffer → lift → outbound lane → conveyor → GTP). **Lifts and buffers sense only presence, not identity** — identity is carried by barcodes scanned along the path. Lift identifiers look like `aisle_04_inbound_lift_02`; lift status surfaces values such as a numeric `lift_status` and a textual description (e.g. `ERROR`).
- **Addressing:** `Aisle–Level–Location–Deep`, e.g. `01-12-16-02`.
- **Tote types:** TS (short) / TL (tall), same footprint; 2/4/8 partitions, one PID per partition; all four faces + every partition barcoded.
- **Inbound/put-away & retrieval:** decant at IQC → WES assigns address → conveyor → lift → buffer → shuttle → store; retrieval reverses to GTP for **picking, compaction, cycle count**; unresolved discrepancies block a tote until verified.
- **Control & connectivity:** WES is the brain; almost everything is wired (LAN/EtherCAT) — **only the moving shuttle is on Wi-Fi**. Acknowledgement at every handoff; the whole sensor/ack system is visualised in Grafana.

(The final Word notebook compiled at project end will lead with this chapter, then Chapter 2 dashboards, then one chapter per module, then the data-volume chapter. That Word build happens later in claude.ai — your job is to keep all markdown comprehensive enough to compile cleanly.)

## 11. This session's goal

Build the shared `core/`, `db/schema.sql`, the `webapp/` skeleton with the main dashboard, the documentation skeleton (with Chapter 1 seeded and `pdm_notebook.md` index started), and the **complete LIFT module** end-to-end (fetch → features → health → RCA → DB → module dashboard), following the §5 SOP. **Begin by reading the mapping markdown, then ask me for the LIFT dashboard links** as described in §5 step 2. Then proceed.

Remember: keep docs in lockstep with code, check cross-module relevance of every panel you fetch, never run git, and finish with `done master` + commit message + next-session prompt.