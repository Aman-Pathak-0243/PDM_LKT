# `database/` — the CSV data store (trends, EDA & ML ready)

> **Storage is CSV-only.** All plant data this system produces is persisted here as CSV —
> **no MySQL** (the MySQL backend stays dormant behind `STORAGE_BACKEND`, see
> [CLAUDE.md §1.2](../CLAUDE.md)). This folder is the single home for that data. It is
> **git-ignored** (local plant data never leaves the LAN PC); only this README is tracked.
> The folder and its subfolders are created automatically — `store/` on first app run,
> `analytics/` when you run the analytics builder.

The store is designed so a data scientist can pick it up later for **trend analysis, EDA,
and ML** without touching the app: a normalised source-of-truth, plus flat, tidy,
analysis-ready extracts.

---

## 1. Layout

```
database/
  store/        the live tables — one CSV per table, source of truth (schema = db/schema.sql)
    component_health.csv    ← the longitudinal store: one row per component per run (the ML/EDA gold)
    pdm_run.csv             one row per PdM run (module, window, timing, status, counts)
    trigger_log.csv         one row per trigger (manual/auto), fully traceable
    event_log.csv           structured application/audit events
    panel_catalog.csv       Grafana panels catalogued per module (fields/SQL/is_signal)
    automation_config.csv   per-scope automation schedule
    maintenance_ack.csv     optional operator acknowledgements
    *.seq                   per-table integer-id counters (internal)
  analytics/    analysis-ready, flattened extracts (generated — safe to delete & rebuild)
    component_health_timeseries.csv   universal tidy time-series (consistent cols, all modules)
    by_module/<module>.csv            per-module wide feature matrix (metrics flattened → m_* cols)
    runs.csv                          run-level table (join on run_uid)
    data_dictionary.csv               column → dtype + description
    manifest.json                     what was built, row counts, generated-at
  archive/      rows moved out of the active store by the Storage "archive" action
  exports/      one-off exports produced by the Storage page / migration script
```

Rebuild the `analytics/` extracts any time (read-only on the store):

```bash
python scripts/build_analytics_dataset.py
```

Run it after PdM runs (or on a schedule) to refresh. On an empty store it writes
header-only files so the structure exists for the future.

---

## 2. The longitudinal design (why this is predictive-ready)

Grafana dashboards retain only ~2 days. **Every PdM run snapshots each component's metrics
into `store/component_health.csv`.** Over many runs this accumulates a history far longer
than any single fetch — which is exactly the shape trend analysis and ML want:

- **Entity key:** `component_id` (stable per physical unit across runs), within `module`.
- **Time axis:** `created_at` (UTC ISO-8601); `run_uid` groups all components of one run.
- **Target / trend series:** `health_score` (0–100) and the derived `risk_tier`.
- **Labels of regime & trust:** `prediction_regime` (`coldstart`/`trend`), `confidence`.
- **Flexible features:** `metrics_json` (all raw + derived model features) and `rca_json`
  (root-cause) are JSON per row — the analytics builder flattens these into columns.

A component's trajectory = its `component_health` rows ordered by `created_at`. Fleet trend
= average `health_score` per time bucket. Both are one `groupby` away in the extracts below.

---

## 3. Analysis-ready extracts (`analytics/`)

**`component_health_timeseries.csv`** — the backbone. One row per component per run, the
same columns for every module, sorted by `(module, component_id, created_at)`:

| column | meaning |
|--------|---------|
| `created_at`, `created_date`, `created_hour` | snapshot time (+ split-out date/hour for grouping) |
| `module`, `component_id`, `component_type`, `aisle` | entity keys (`aisle` parsed where applicable) |
| `run_uid` | run this snapshot belongs to (join → `runs.csv`) |
| `health_score`, `risk_tier` | health 0–100 + tier (`ok`/`watch`/`warn`/`critical`) |
| `predicted_ttm_hours`, `confidence`, `prediction_regime` | RUL estimate + trust + regime |
| `primary_cause`, `penalty_total` | dominant cause + total penalty applied |

**`by_module/<module>.csv`** — one file per module: the same rows plus **every** model
feature for that module flattened out of `metrics_json` as `m_*` columns (e.g.
`m_error_rate_per_day`, `m_penalties_severity`) — a ready, consistent ML feature matrix.

**`runs.csv`** — one row per PdM run: window, timing, status, rows fetched, components
scored. Join to the time-series on `run_uid` for run-level context.

**`data_dictionary.csv`** — machine-readable column reference for the above.

---

## 4. Quick starts

```python
import pandas as pd
ts = pd.read_csv("database/analytics/component_health_timeseries.csv", parse_dates=["created_at"])

# Fleet health trend (daily average)
ts.groupby("created_date")["health_score"].mean()

# One component's trajectory
ts[ts.component_id == "aisle_04_inbound_lift_02"].sort_values("created_at")[["created_at","health_score","risk_tier"]]

# Aisle × module risk snapshot (latest per component)
latest = ts.sort_values("created_at").groupby(["module","component_id"]).tail(1)
latest.pivot_table(index="aisle", columns="module", values="health_score", aggfunc="mean")

# ML feature matrix for one module (predict next-run health, etc.)
lift = pd.read_csv("database/analytics/by_module/lift.csv", parse_dates=["created_at"])
```

The same rollups power the dashboard's **Graphical Overview** tab (see
[docs/DASHBOARD_UI.md](../docs/DASHBOARD_UI.md)); this folder lets you take them further
offline. To copy/verify the store or move to a bigger disk, use
[`scripts/db_migrate_export.py`](../scripts/db_migrate_export.py)
([Developer Guide §6](../docs/DEVELOPER_GUIDE.md)).
