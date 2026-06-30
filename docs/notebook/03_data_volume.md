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

*(Subsequent sessions append their module's fetch volumes + write footprint here.)*
