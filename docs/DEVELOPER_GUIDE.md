# Developer Guide — building, maintaining & extending the ASRS PdM system

> **Audience:** an engineer who will develop, maintain, update, or operate the code base.
> Read [`CLAUDE.md`](../CLAUDE.md) (durable conventions + hard rules) and
> [`pdm_notebook.md`](../pdm_notebook.md) first; this guide is the practical how-to that
> ties them together, and it documents the **database backup / export / migration**
> workflow (with a ready-to-run script).

---

## 1. Architecture at a glance

```
core/                     shared, module-agnostic infrastructure
  config.py               load + validate .env, resolve paths, mask secrets
  logging_setup.py        structured JSON logging (file + console)
  grafana_auth.py         Playwright login -> reusable session/cookies
  grafana_fetcher.py      panel CSV via &inspect=<id>&inspectTab=data + Download CSV
  panel_inspector.py      enumerate panels from the dashboard JSON API; sample + describe
  registry.py             PdMModule base class + plugin registry + shared tier/rollup helpers
  runner.py               a PdM run: fetch -> features -> health -> persist (trigger-wrapped)
  scheduler.py            APScheduler automation (in-process, independent of the dashboard)
  audit.py                structured event_log writer
  storage/                storage abstraction — CSV active, MySQL dormant (gated)
    base.py               TABLE_SCHEMAS (runtime source of truth) + StorageBackend interface
    csv_backend.py        CSV implementation (locking, atomic writes, type coercion)
    mysql_backend.py      MySQL implementation (dormant; gated by MYSQL_CONFIRM)
    __init__.py           get_storage() factory reading STORAGE_BACKEND
modules/<name>/           one self-registering plugin per equipment type (11 total)
  __init__.py             subclass PdMModule + register(...) + methodology dict
  module.yaml             resolved panels + thresholds (the tunables; no magic numbers in code)
  fetch.py                which dashboards/panels this module consumes
  features.py             raw + derived features (rates/ratios/robust z — never raw counts)
  health.py               per-component score, tier, TTM, confidence, regime
  rca.py                  root-cause attribution + cross-module flags
  README.md               the module's notebook chapter (panels, fields, formulas)
webapp/                   FastAPI app: pages (main.py) + JSON API (api.py) + services + exporting + background
db/schema.sql             MySQL schema (designed; the CSV backend mirrors it 1:1)
docs/                     the PdM book (notebook chapters, mapping, these guides, audit report)
scripts/                  discover/inspect/analyze helpers + db_migrate_export.py
data/                     CSV store + fetched-panel caches + exports/archives (gitignored)
logs/                     structured logs (gitignored)
tests/                    offline unit + regression tests
```

**The core invariant:** a PdM run is `fetch → features → health → persist`
([`core/runner.py`](../core/runner.py)). Manual runs go through a background thread pool
([`webapp/background.py`](../webapp/background.py)); automated runs through APScheduler
([`core/scheduler.py`](../core/scheduler.py)). Both call the **same** runner and write the
**same** datasets. Everything persists through `core.storage`, so CSV↔MySQL is a config
switch, not a code change.

---

## 2. Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium         # one-off browser download
cp .env.example .env                            # fill GRAFANA_* + MODULE__* URLs
.venv/bin/python run.py                          # dashboard + automation on APP_PORT (8800)
```

Run the tests any time (offline, no network):
```bash
.venv/bin/python -m pytest -q          # 31 tests: storage + every module + regressions
```

---

## 3. Configuration (`.env`) — never hardcode

`core/config.py` loads `.env` once into an immutable, secret-masking `Config`. Keys:

| Group | Keys | Notes |
|-------|------|-------|
| Grafana | `GRAFANA_BASE_URL`, `GRAFANA_USERNAME`, `GRAFANA_PASSWORD`, `GRAFANA_*_SELECTOR`, `GRAFANA_DOWNLOAD_BUTTON_TEXT`, `GRAFANA_NAV_TIMEOUT_MS`, `PLAYWRIGHT_HEADLESS` | Login + fetch mechanics. Password is masked in `repr`. |
| Storage | `STORAGE_BACKEND` (`csv`\|`mysql`), `DATA_DIR`, `LOG_DIR` | CSV is active. |
| MySQL (dormant) | `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_CONNECTION_LIMIT`, plus the runtime gate `MYSQL_CONFIRM=ENABLE` | Never connects without the gate. |
| App | `APP_HOST`, `APP_PORT`, `APP_TITLE` | Binds the dashboard. |
| Fetch | `FETCH_DEFAULT_WINDOW` (e.g. `now-2d`) | Default analysis window. |
| Module dashboards | `MODULE__DASHBOARD_NAME` (e.g. `LIFT__LIFT_ERROR_HISTORY`) | Full Grafana URLs per module panel. `Config.module_dashboard_urls("lift")` reads them. |

Process env overrides `.env` (handy for Docker/systemd). Empty values are treated as
unset so blank placeholders don't masquerade as real config.

---

## 4. Adding a new module (the plugin contract)

**No `core/` edits.** Follow the per-module SOP in `CLAUDE.md §5`; the mechanics:

1. **Discover & confirm dashboards** — `scripts/discover_dashboards.py` lists Grafana
   dashboards via `/api/search`; confirm the module's sources, then add their full URLs to
   `.env` under `MODULE__DASHBOARD_NAME` keys.
2. **Enumerate + sample panels** — `scripts/inspect_<module>.py meta` (panel ids/titles/
   fields/SQL from the dashboard JSON API) and `... sample` (a small slice into
   `data/inspection/`). Judge relevance; write the verdict into the module README + Chapter 2.
3. **Create `modules/<name>/`:**
   - `module.yaml` — resolved `{dashboard, panelId, role, fields}` + `thresholds`
     (weights, caps, tiers, confidence, catalogs). **All tunables live here**, loaded by
     `spec.py`; keep magic numbers out of Python.
   - `fetch.py` — `fetch(session, window) -> FetchBundle` (frames + rows_fetched + panel
     catalog entries + notes). Always thread the run `window` through; never hardcode `now-2d`.
   - `features.py` — `compute_features(bundle) -> {component_id: {…}}`. Build
     **normalised** signals (rates, ratios, robust z-scores). Never penalise on a raw count.
   - `health.py` — `score(features, history) -> [ComponentHealth]`. Penalty model
     (`health = clamp(100 − Σ capped_penaltyᵢ, 0, 100)`), tiers, TTM, confidence, regime.
   - `rca.py` — `build_rca(...) -> (primary_cause, rca_dict)`; rank contributors; name the
     physical fault; emit `cross_module_flags` where a causal chain exists.
   - `spec.py` — loads `module.yaml` (usually copy an existing one).
   - `__init__.py` — subclass `PdMModule`, set `name/title/component_type/description/
     methodology`, wire `fetch/compute_features/score`, and `register(TheModule())`.
   - `README.md` — the module's chapter (panels, fields, formulas, validation).
4. **Register it:** add one import line to `modules/__init__.py` so it self-registers.
5. **Methodology dict** — give the class a `methodology` (summary, `signals`,
   `entity_verdict` steps, `formulas`). It's merged with the shared rollup in
   `core/registry.py` and served at `/api/modules/<name>/methodology`, rendered in-page.
6. **Test + document** — add unit tests to `tests/test_pdm.py`; update the module README,
   Chapter 2, the data-volume chapter, the mapping markdown, and the notebook index.

The dashboard, runner, scheduler, and storage discover the new module from the registry
automatically — no wiring beyond the import line.

### Scoring conventions every module must uphold (audit invariants)
From [`methodology.md §12`](notebook/methodology.md) / [`AUDIT_REPORT.md`](AUDIT_REPORT.md):
1. **Confidence reflects evidence, not severity** — cold-start confidence tracks store
   depth (prior runs), capped ~0.85; never the magnitude of the current reading.
2. **No raw counts drive penalties** — use rates, ratios, robust z, binary states, or
   volume-gated intensities.
3. **Trend fits are crash-safe** — guard every `np.polyfit` against zero time-spread
   (identical snapshot timestamps) + wrap in `try/except`.
4. **Percentages are physically bounded** — clamp downtime/utilisation/shares at source.
5. **Peer-deviation never double-counts the absolute signal**, and is gated by an
   absolute floor.

---

## 5. Storage abstraction & backend switching

All persistence goes through a `StorageBackend` ([`core/storage/base.py`](../core/storage/base.py)):
`insert / select / count / delete / distinct / upsert / latest_per / stats`. The schema
(`TABLE_SCHEMAS`) is the **runtime source of truth**; `db/schema.sql` is its MySQL twin.

- **Active:** CSV (`database/store/<table>.csv` + a `.seq` id counter). Writes take an
  OS-level `flock` + in-process lock and are atomic (temp-file + `os.replace`), so
  concurrent manual + scheduled runs never corrupt a file.
- **Dormant:** MySQL, behind a two-key gate — `STORAGE_BACKEND=mysql` **and**
  `MYSQL_CONFIRM=ENABLE`. Without the confirm, `get_storage()` raises
  `MySQLPermissionError`. This enforces the hard rule "never use MySQL until permitted."
- **Switching changes no calling code** — every module + the webapp use only the
  abstraction. Flip the env, apply `db/schema.sql`, migrate the data (§6), restart.

Datetimes are UTC ISO-8601 strings in both backends (lexicographic range filters +
ordering behave identically). JSON columns (`rca_json`, `metrics_json`, …) hold flexible
metadata so future AI/ML/analytics never needs a migration.

**Analysis-ready extracts (trends / EDA / ML).** The store keeps model features in JSON
columns — great for the app, awkward for a data scientist. `scripts/build_analytics_dataset.py`
reads the store (read-only) and writes flat, tidy CSVs under `database/analytics/`: a
universal `component_health_timeseries.csv` (consistent columns across all modules — the
trend backbone), per-module `by_module/<module>.csv` feature matrices (JSON flattened to
`m_*` columns), `runs.csv`, and `data_dictionary.csv`. Re-run it after PdM runs or on a
schedule. Full guide: [`database/README.md`](../database/README.md).

---

## 6. Database full → back up & export to another database

When the active store (CSV now, or MySQL later) fills a disk or must move to a
bigger/faster database, use **[`scripts/db_migrate_export.py`](../scripts/db_migrate_export.py)**.
It reads through `core.storage` (so the source respects `STORAGE_BACKEND`), preserves JSON
columns and types faithfully, re-assigns surrogate `id`s on the target (joins use
`run_uid`/`trigger_id`, so nothing breaks), and **never touches MySQL without the gate**.

### The workflow

**Step 0 — see what you have**
```bash
.venv/bin/python scripts/db_migrate_export.py stats
```

**Step 1 — take a portable backup** (safety net; a timestamped folder of JSONL + manifest)
```bash
.venv/bin/python scripts/db_migrate_export.py backup
# -> database/exports/backup_<UTC-timestamp>/  (one .jsonl per table + manifest.json)
```

**Step 2a — move to a fresh CSV store** (e.g. a bigger disk / new location)
```bash
.venv/bin/python scripts/db_migrate_export.py copy --to-csv /mnt/big/pdm_store
# then point the app at it:  DATA_DIR=/mnt/big/pdm_store   (STORAGE_BACKEND stays csv)
```

**Step 2b — migrate into MySQL** (only after permission is granted)
```bash
# 1) put the real DB_* creds + name in .env, apply the schema once:
#      mysql < db/schema.sql
# 2) copy the whole store in (the gate is mandatory):
MYSQL_CONFIRM=ENABLE .venv/bin/python scripts/db_migrate_export.py copy --to-mysql
# 3) switch the app over:  STORAGE_BACKEND=mysql  MYSQL_CONFIRM=ENABLE   then restart run.py
```

**Step 3 — verify the migration moved everything**
```bash
.venv/bin/python scripts/db_migrate_export.py verify --to-csv /mnt/big/pdm_store
# or:  MYSQL_CONFIRM=ENABLE .venv/bin/python scripts/db_migrate_export.py verify --to-mysql
```

**Restore a backup** (inverse of Step 1) into the active store or an explicit target:
```bash
.venv/bin/python scripts/db_migrate_export.py load --from database/exports/backup_<ts>
.venv/bin/python scripts/db_migrate_export.py load --from <folder> --to-csv /mnt/big/pdm_store
```

### Notes & safety
- The **source is read-only** — `copy`/`backup`/`verify` never delete source rows. To
  actually free space after a verified migration, use the dashboard **Storage → delete by
  range** (confirmed + logged) or archive old rows first.
- Keyed tables (`automation_config` by `scope`, `panel_catalog` by
  `(module, dashboard_uid, panel_id)`) are **upserted** so re-running is idempotent;
  append tables (`component_health`, `pdm_run`, `trigger_log`, `event_log`,
  `maintenance_ack`) get fresh surrogate ids on the target.
- Large stores stream in batches of 1,000 rows — memory stays bounded even for millions
  of `component_health` rows.
- The same tool doubles as your **periodic backup**: schedule
  `db_migrate_export.py backup` (cron / Task Scheduler) to snapshot the store to your
  backup target. See [Hosting Resources → Backup & retention](HOSTING_RESOURCES.md#5-backup--retention).

---

## 7. Grafana fetch mechanics (for module authors)

- **Login** — Playwright opens `${GRAFANA_BASE_URL}/login`, fills the configured
  selectors, submits, and persists cookies for reuse within a run.
- **Enumerate panels** — parse the `uid` from `/d/<uid>/<slug>`, then
  `GET /api/dashboards/uid/<uid>` for each panel's id/title/type/fields/SQL. Never guess
  `inspect=N` — derive ids from this model.
- **Fetch panel data (CSV)** — build `${dashboardURL}&inspect=<panelId>&inspectTab=data`,
  open it, activate the Data tab, click the `Download CSV` button, load into pandas.
- **Template variables** — leaving aisle/level/etc. empty returns the full dataset;
  support `&var-<Name>=<value>` overrides.
- **Time window** — always parameterise `from`/`to` (Grafana relative syntax, e.g.
  `now-2d`); default `FETCH_DEFAULT_WINDOW`. Some panels ignore the window (current-state);
  those modules anchor "now" to the data `as_of` or the run time (documented per module).

---

## 8. Testing, logging, conventions

- **Tests** — `tests/test_pdm.py` (offline; storage round-trip + every module's scoring +
  the Session-12 regression suite). Add a test for any new signal or fix. Target: keep the
  suite green (`pytest -q`).
- **Logging** — structured JSON via `core/logging_setup.py` to `logs/app.log.jsonl` +
  console. Domain/audit events go to the `event_log` table via `core.audit.record_event`
  and surface on the dashboard **Logs** page. Log silent-signal-loss conditions (missing
  columns, dropped rows) so drift is visible.
- **Quality bar** — clean architecture, SOLID/DRY/KISS, type hints, input validation,
  secure coding (no secret leakage), graceful exception handling. Every change leaves the
  project more stable than before.
- **Hard rules (do not violate):** never run git (the user manages the repo); never use
  MySQL without the gate; read secrets from `.env` and never print the password; LAN-only;
  ignore `ignore.txt`; keep docs in sync with code every session.

---

## 9. Where to look for what

| I need to… | File(s) |
|------------|---------|
| Understand the methodology | [`docs/notebook/methodology.md`](notebook/methodology.md) (+ §12 invariants) |
| See how a module scores | that module's `README.md` + `health.py`/`features.py`/`rca.py` |
| See the per-module signals in one place | [`docs/MODULE_METHODOLOGY.md`](MODULE_METHODOLOGY.md) |
| Trace a route/endpoint | [`docs/URL_MAP.md`](URL_MAP.md), `webapp/main.py`, `webapp/api.py` |
| Change the schema | `core/storage/base.py` (source of truth) **and** `db/schema.sql` (keep in sync) |
| Add/adjust automation | `core/scheduler.py` + the **Automation** page |
| Back up / migrate the store | `scripts/db_migrate_export.py` (§6) |
| Review recent correctness work | [`docs/AUDIT_REPORT.md`](AUDIT_REPORT.md) |
