# Chapter 3 — Data volume

> Per-dashboard/panel fetch volumes and the PdM store's write footprint + growth.
> Updated each session as modules are added. Numbers are observed via sampling.

## How volume is measured

`scripts/inspect_lift.py sample` downloads each panel's CSV for a window and records
the row count, columns, and dtypes into `data/inspection/`. The PdM write footprint
is derived from the schema (rows written per run) and the CSV row sizes.

## Fetch volume — LIFT sources (sampled 2026-06-30)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| Lift Error History `#2` | **4,751** | Full retained history (2022-09 → 2023-02, ~5 months), 16 lifts. Panel ignores the time window and returns all rows; the model windows in-code. ≈ 31 error rows/day system-wide over that span. |
| Bad Tracker `#2` | ~85 | Current (now-2d); typically a handful carry `lift_id`. |
| Lift Error Analysis `#2` | 6 | One row per aisle (per-position task counts). |
| QUADRON CYCLES `#2` (shuttle) | ~124 | Reassigned to Shuttle. |
| QUADRON ERROR HISTORY `#2` (shuttle) | ~85–94 | Reassigned to Shuttle. |

A full LIFT fetch (primary + 2 secondaries) pulls ≈ **4.8k rows** in ~20–35 s
(dominated by Playwright CSV downloads, ~3–5 s/panel).

## Write footprint — per PdM run (LIFT)

| Dataset | Rows written per run | Approx size/row |
|---------|---------------------:|-----------------|
| `pdm_run` | 1 | ~0.3 KB |
| `component_health` | 16 (one per lift) | ~1.5–2 KB (rca_json + metrics_json) |
| `trigger_log` | 1 (insert + finalize) | ~0.4 KB |
| `panel_catalog` | 3 (upsert, not append) | ~0.4 KB |
| `event_log` | ~1–2 (trigger complete, etc.) | ~0.3 KB |

≈ **18 new rows / run**, dominated by `component_health` (~30 KB/run).

## Growth projection

`component_health` is the longitudinal store and the main growth driver:

| Automation interval | Rows/day (lift) | Store growth/day | Per year |
|---------------------|----------------:|-----------------:|---------:|
| hourly | 16 × 24 = 384 | ~0.6 MB | ~0.2 GB |
| every 15 min | 1,536 | ~2.4 MB | ~0.9 GB |

These are comfortably within a single-PC CSV store. As more modules register, scale
roughly linearly with `Σ components`. The Storage Management page reports live
sizes/record-counts/growth, and supports **archive** (move old rows to
`data/archive/`) and **delete by range** to cap footprint. When the store is later
moved to MySQL, the same row counts apply and the `(module, component_id, created_at)`
index keeps trend queries fast.

## Fetch volume — SHUTTLE sources (sampled 2026-06-30)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| QUADRON ERROR HISTORY `#2` | ~94 | Frozen (2023-08-11), 4 shuttles faulting. |
| QUADRON CYCLES `#2` | **124** | One row per shuttle (cumulative cycles). The roster. |
| Daily Shuttle Errors `#2` | ~16 | Current aggregated error descriptions. |
| Bad Tracker `#2` | ~76 (shuttle rows) | Current shuttle recurrence / pick errors. |
| Quadron Alerts `#2` | ~11 | Current free-text alerts. |

A full shuttle fetch pulls ≈ **320–350 rows** in ~20–35 s.

## Write footprint — per PdM run (SHUTTLE)

`component_health` dominates: **124 rows/run** (one per shuttle), ≈ 200–280 KB/run
(rca_json + metrics_json incl. cycles). Plus 1 `pdm_run`, 1 `trigger_log`, 5
`panel_catalog` upserts, ~1–2 `event_log`.

| Automation interval | component_health rows/day (shuttle) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 124 × 24 = 2,976 | ~5 MB | ~1.8 GB |
| every 15 min | 11,904 | ~20 MB | ~7 GB |

Shuttle is the largest per-run writer so far (124 components). Combined with Lift (16),
hourly automation writes ≈ 3,360 `component_health` rows/day. Still fine for the CSV store;
the Storage page's archive/delete-by-range caps footprint, and the
`(module, component_id, created_at)` index keeps trend/RUL queries fast under MySQL later.

## Fetch volume — CONVEYOR sources (sampled 2026-06-30)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| Conveyor Zone Count `#6/#8/#10/#12/#14/#16` | ~6k–17k **per zone** | Per-minute(ish) live samples; ~65k rows total for 6 zones over 24 h. |
| GTP HOLD/TRANSIT `#2/#4` | ~200 + ~180 | Current on-hold / in-transit counts. |

A full conveyor fetch pulls ≈ **65k rows** in ~30–60 s (the 6 heavy live timeseries
dominate — the fetcher uses `domcontentloaded` + a generous Download-CSV wait to handle
dashboards that never reach network-idle). The window is short by design (`now-24h`),
which bounds this; a wider window scales the timeseries linearly.

## Write footprint — per PdM run (CONVEYOR)

Only **6 rows/run** in `component_health` (one per zone) — tiny, despite the large fetch.
Plus 1 `pdm_run`, 1 `trigger_log`, up to 8 `panel_catalog` upserts, ~1–2 `event_log`.

Across all three modules, a single "Run all" writes ≈ **16 + 124 + 6 = 146** `component_health`
rows. Hourly automation ≈ 3,500 rows/day — comfortably within the CSV store; archive/delete-by-range
caps it.

## Fetch volume — TRACKER sources (sampled 2026-06-30)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| Bad Tracker `#2` | **~85–86** | **Current-state** (identical at `now-2d` and `now-90d` — window not server-filtered). One row per mislocated tote. |
| Total BT Totes `#4` | 1 | Scalar count context. |

A full tracker fetch pulls ≈ **86 rows** in ~15–20 s (two light table panels; the
template-var drill-downs `#8/#6/#10` are **not** fetched in the core run). The window
governs the in-code recent-vs-stale split, not the fetch size.

## Write footprint — per PdM run (TRACKER)

`component_health` rows/run = **the number of currently-bad locations** (≈ 54 this
snapshot), not a fixed roster — it shrinks/grows with the anomaly set. Each row ≈
1.5–2 KB (rca_json carries the cluster + stuck tracker tags). Plus 1 `pdm_run`, 1
`trigger_log`, 5 `panel_catalog` upserts, ~1–2 `event_log`.

| Automation interval | component_health rows/day (tracker, ~54) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 54 × 24 ≈ 1,296 | ~2.2 MB | ~0.8 GB |
| every 15 min | ~5,184 | ~9 MB | ~3.2 GB |

Tracker is the module whose store **most** rewards accumulation: recurrence across runs
is its strongest signal, so its longitudinal history is doing predictive work the single
2-day fetch cannot. Across all four modules a single "Run all" writes ≈ **16 + 124 + 6 +
~54 = ~200** `component_health` rows; hourly automation ≈ 4,800 rows/day — still well
within the CSV store, with archive/delete-by-range to cap footprint.

*(Subsequent sessions append their module's fetch volumes + write footprint here.)*
