# Chapter 3 — Data volume

> Per-dashboard/panel fetch volumes and the PdM store's write footprint + growth.
> Updated each session as modules are added. Numbers are observed via sampling.

## How volume is measured

`scripts/inspect_lift.py sample` downloads each panel's CSV for a window and records
the row count, columns, and dtypes into a dev-time `data/inspection/` scratch dir (panel
sampling only, not persisted PdM data). The PdM write footprint is derived from the schema
(rows written per run) and the CSV row sizes.

All **persisted** PdM data is **CSV-only**, under the single **`database/`** folder (`DATA_DIR=database`):
`store/` (live tables), `analytics/` (tidy trend/EDA/ML extracts built by
`scripts/build_analytics_dataset.py`), `archive/`, and `exports/`. Data dictionary:
[`database/README.md`](../../database/README.md).

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
`database/archive/`) and **delete by range** to cap footprint. When the store is later
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

## Fetch volume — GATE sources (sampled 2026-07-01)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| Quadron-gate-status `#2` | **52** | **Current-state** (identical at `now-2d` and `now-90d`). One row per gate = the roster. |
| Quadron-gate-status `#4` | 1–2 | Open/open-requested subset (= the non-closed gates); integrity cross-check. |
| Quadron Alerts `#2` | ~20–30 | Free-text alert rows (UNION); only the `front_gate`/`rear_gate` messages (one per non-closed gate) are parsed for latency. |

A full gate fetch pulls ≈ **75–85 rows** in ~5–6 s (three light table panels). The window is
nominal (the gate panel is current-state); it does not scale the fetch.

## Write footprint — per PdM run (GATE)

`component_health` = **52 rows/run** (one per gate, the fixed roster), ≈ 1–1.5 KB/row
(rca_json + metrics_json carry status, latency, and the cross-run stats). Plus 1 `pdm_run`,
1 `trigger_log`, up to 3 `panel_catalog` upserts, ~1–2 `event_log`.

| Automation interval | component_health rows/day (gate, 52) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 52 × 24 = 1,248 | ~1.5 MB | ~0.5 GB |
| every 15 min | 4,992 | ~6 MB | ~2.2 GB |

Gate is a fixed-roster module (52 rows/run regardless of state) whose store is essential:
persistence + non-closed recurrence — its strongest signals — only exist because state is
snapshotted repeatedly, so **regular automation is what makes it predictive**. Across all five
modules a single "Run all" writes ≈ **16 + 124 + 6 + ~54 + 52 = ~250** `component_health` rows;
hourly automation ≈ 6,000 rows/day — still comfortably within the CSV store, with
archive/delete-by-range to cap footprint and the `(module, component_id, created_at)` index
keeping trend/RUL queries fast under MySQL later.

## Fetch volume — BIN / TOTE-MECHANICAL sources (sampled 2026-07-01)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| Bin blocked / tote-tilted `#2` | ~220 | Current blocked bins (live `bin_blocked`); partition-inflated → **~40 distinct locations** after dedup. |
| Bin Block History `#2` | **~26,600** | Frozen block log (2022-12 → 2024-09); per-location historical block frequency. The heavy fetch. |

A full bin fetch pulls ≈ **27k rows** in ~5–8 s (dominated by the historical log). The history is
frozen and re-fetched each run (best-effort) — a future optimisation is to cache it, since it does
not change; correctness (self-contained runs) is preferred for now.

## Write footprint — per PdM run (BIN / TOTE-MECHANICAL)

`component_health` rows/run = **the number of currently-blocked slots** (≈ 40 this snapshot), not
a fixed roster — it shrinks/grows with the block anomaly set. Each row ≈ 1–1.5 KB. Plus 1
`pdm_run`, 1 `trigger_log`, ~3 `panel_catalog` upserts, ~1–2 `event_log`.

| Automation interval | component_health rows/day (bin, ~40) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 40 × 24 ≈ 960 | ~1.3 MB | ~0.5 GB |
| every 15 min | ~3,840 | ~5 MB | ~1.8 GB |

Like Tracker, this module's store **most** rewards accumulation: cross-run recurrence (a slot
blocked run after run) is its strongest signal, so its longitudinal history does predictive work
the single fetch cannot. Across all six modules a single "Run all" writes ≈ **16 + 124 + 6 + ~54 +
52 + ~40 = ~292** `component_health` rows; hourly automation ≈ 7,000 rows/day — comfortably within
the CSV store, with archive/delete-by-range to cap footprint and the `(module, component_id,
created_at)` index keeping trend/RUL queries fast under MySQL later.

## Fetch volume — GTP STATION + SCANNER sources (sampled 2026-07-01)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| GTP Scanner logs `#8` (Read/NoRead) | **272** | One row per scan device; **windowed** (2.6M scans aggregated over 2d). The scanner universe. |
| GTP Scanner logs `#4` (Scanner Hits) | ~272 | Per-scanner volume proxy (best-effort). |
| Discrepancy Report Events `#2` | **~1,150** | verification_events over the window (~575/day); 47 of 63 stations. Windowed → scales ~linearly with the window. |
| GTP Stations `#2` (Station Summary) | **63** | Station roster + Active/Inactive; current snapshot (not window-filtered). |

A full GTP fetch pulls ≈ **1,750 rows in ~33–37 s** (four table panels; the discrepancy log is
the largest and scales with the window). The heavy raw `scanner_events` feed (`#2`) and the
gauge panels are **not** fetched.

## Write footprint — per PdM run (GTP STATION + SCANNER)

`component_health` rows/run = **272 scanners + 63 stations ≈ 334** — the **largest single-module
writer** (more than Shuttle's 124), because it monitors two whole populations. Each row ≈
1–1.5 KB (rca_json carries the misread/discrepancy detail + cross-links). Plus 1 `pdm_run`, 1
`trigger_log`, ~4 `panel_catalog` upserts, ~1–2 `event_log`.

| Automation interval | component_health rows/day (gtp, ~334) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 334 × 24 ≈ 8,016 | ~10 MB | ~3.6 GB |
| every 15 min | ~32,000 | ~40 MB | ~14 GB |

GTP is the module whose **rates** most reward a wider window (misread/discrepancy are
server-side windowed), and whose **store** most rewards accumulation (recurrence + trend on both
scanners and stations). Across all seven modules a single "Run all" writes ≈ **16 + 124 + 6 +
~54 + 52 + ~40 + ~334 = ~626** `component_health` rows; hourly automation ≈ 15,000 rows/day —
still within the CSV store, with the Storage page's archive/delete-by-range to cap footprint and
the `(module, component_id, created_at)` index keeping trend/RUL queries fast under MySQL later.
For very frequent automation, GTP is the first module worth a tighter interval or a scanner-tier
filter (e.g. persist only non-ok scanners) if the store grows faster than desired.

## Fetch volume — DECANTING STATION + SCANNER sources (sampled 2026-07-01)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| GTP Scanner logs `#8` (Read/NoRead) | **272** | The full scanner table (**shared** with GTP); filtered in-code to the **9** decant/compaction devices. **Windowed**. |
| Decanting station report `#2` | **10** | The `DS001`–`DS010` roster + Active/Inactive; current snapshot (not window-filtered). |
| StationWise Decanted Cartons Count `#2` | **~7** | Per-station carton throughput (only stations that decanted appear); **windowed** → scales with the window/load. |

A full decant fetch pulls ≈ **289 rows in ~13–14 s** (three light table panels; the scanner table is
the largest, and it is the same fetch the GTP module already makes). The two frozen "Discrepancy
Marked" drill-downs and the var-gated material-wise panel are **not** fetched.

## Write footprint — per PdM run (DECANTING STATION + SCANNER)

`component_health` rows/run = **9 scanners + 10 stations = 19** — a small writer (both populations are
tiny). Each row ≈ 1–1.5 KB (rca_json carries the misread detail / status / cross-run stats). Plus 1
`pdm_run`, 1 `trigger_log`, ~3 `panel_catalog` upserts, ~1–2 `event_log`.

| Automation interval | component_health rows/day (decant, 19) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 19 × 24 = 456 | ~0.7 MB | ~0.25 GB |
| every 15 min | 1,824 | ~2.7 MB | ~1 GB |

Decant is a small module by volume, but its **store** is what makes the station entity work at all:
with no live discrepancy feed, a decant station's only signal is **persistence** across runs (offline
or idle-while-active), so **regular automation is what makes it predictive** — a single run scores
every station `ok`. Across all eight modules a single "Run all" writes ≈ **16 + 124 + 6 + ~54 + 52 +
~40 + ~326 + 19 ≈ 637** `component_health` rows (GTP is now ~326 = 263 scanners + 63 stations after
the 9 decant/compaction devices moved to Module 8; decant adds them back as 9 scanners plus 10 new
stations); hourly automation ≈ 15,000 rows/day — still within the CSV store, with the Storage page's
archive/delete-by-range to cap footprint and the `(module, component_id, created_at)` index keeping
trend/RUL queries fast under MySQL later.

## Fetch volume — NETWORK / COMMS sources (sampled 2026-07-01)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| Quadron Network status `#4` (windowed) | **124** | Per-shuttle uptime% since `${Date}`=window start; the full roster. **Windowed** (a wider window smooths the average). |
| Quadron Network status `#2` (today) | **~100** | Per-shuttle uptime% since midnight today (shuttles active today); recency signal. |

A full network fetch pulls ≈ **224 rows in ~8 s** (two light table panels; both live-computed in MSSQL
from `shuttle_error`). One of the fastest fetches in the system.

## Write footprint — per PdM run (NETWORK / COMMS)

`component_health` = **124 rows/run** (one per shuttle link, the fixed roster), ≈ 1–1.5 KB/row
(rca_json carries downtime detail + cross-feature flags). Plus 1 `pdm_run`, 1 `trigger_log`, ~2
`panel_catalog` upserts, ~1–2 `event_log`.

| Automation interval | component_health rows/day (network, 124) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 124 × 24 = 2,976 | ~4 MB | ~1.5 GB |
| every 15 min | 11,904 | ~16 MB | ~6 GB |

Network is a fixed-roster module (124 rows/run) and a light fetch, but its **store** is what makes the
recurrence + trend RUL work, and its **cross-feature** flags (a degrading link → the Shuttle module; an
aisle downtime cluster → the meta layer) are the hooks the Module 11 meta-module will chain into
compound-failure detection. Across all nine modules a single "Run all" writes ≈ **16 + 124 + 6 + ~54 +
52 + ~40 + ~326 + 19 + 124 ≈ 761** `component_health` rows; hourly automation ≈ 18,000 rows/day — still
comfortably within the CSV store, with archive/delete-by-range to cap footprint and the
`(module, component_id, created_at)` index keeping trend/RUL queries fast under MySQL later.

## Fetch volume — CONTROLLER / COMPUTE sources (sampled 2026-07-01)

| Dashboard / panel | Rows fetched | Notes |
|-------------------|-------------:|-------|
| CPU Stats `#17` | **1** | `EXEC getCPUDetails` → one row (`cpu_idle, cpu_sql`). Current-state (identical across windows). |

A full controller fetch pulls **1 row in ~1.8 s** — the **smallest + fastest fetch in the system** (one
stored-proc call). The window does not scale it (current-state).

## Write footprint — per PdM run (CONTROLLER / COMPUTE)

`component_health` = **1 row/run** (one compute node; scales with N nodes if per-host CPU appears), ≈
0.6–1 KB/row. Plus 1 `pdm_run`, 1 `trigger_log`, 1 `panel_catalog` upsert, ~1–2 `event_log`.

| Automation interval | component_health rows/day (controller, 1) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 24 | ~30 KB | ~11 MB |
| every 15 min | 96 | ~120 KB | ~44 MB |

Controller is the **smallest writer** in the system, but its **store** is essential: the feed is a
current-state snapshot with no in-feed trend, so sustained-high + trend RUL exist **only** because the
store snapshots the current CPU each run — **regular automation is what makes it predictive**, letting it
warn before a controller saturates. Its `meta` cross-flag is the hook the Module 11 meta-module chains
into compound-failure detection. Across all ten modules a single "Run all" writes ≈ **16 + 124 + 6 + ~54
+ 52 + ~40 + ~326 + 19 + 124 + 1 ≈ 762** `component_health` rows; hourly automation ≈ 18,000 rows/day —
still comfortably within the CSV store, with archive/delete-by-range to cap footprint and the
`(module, component_id, created_at)` index keeping trend/RUL queries fast under MySQL later.

## Fetch volume — SYSTEM-WIDE ANOMALY (META) — **no fetch**

| Source | Rows read | Notes |
|--------|----------:|-------|
| PdM store `component_health` (latest per component) | **~770** | **No Grafana call.** Reads the latest verdict of every other module from the store (~0.3 s). |

Meta is the only module with **no Grafana fetch** — it reads the store (`latest_per(component_health)`),
correlates in-memory, and writes back. The "fetch" is a fast in-process store read (~0.3 s for ~770
components), independent of any dashboard or window.

## Write footprint — per PdM run (META)

`component_health` = **7 rows/run** (6 aisles + system; the aisle roster is dynamic = observed aisles),
≈ 1–2 KB/row (rca_json carries the flagged-member list + chain edges). Plus 1 `pdm_run`, 1 `trigger_log`,
1 `panel_catalog` upsert, ~1–2 `event_log`.

| Automation interval | component_health rows/day (meta, 7) | growth/day | per year |
|---------------------|-----------:|-----------:|---------:|
| hourly | 168 | ~0.25 MB | ~0.09 GB |
| every 15 min | 672 | ~1 MB | ~0.35 GB |

Meta is a tiny writer, but its rows are the **system's compound-risk trend** — the store lets it detect a
compound incident **persisting** across runs (its recurrence signal). Because it reads (not re-fetches) the
other modules' verdicts, it adds cross-module insight at near-zero fetch cost.

## Whole-system footprint (all 11 modules)

A single "Run all" writes ≈ **16 + 124 + 6 + ~54 + 52 + ~40 + ~326 + 19 + 124 + 1 + 7 ≈ 769**
`component_health` rows across the **11 modules** (Lift, Shuttle, Conveyor, Tracker, Gate, Bin, GTP,
Decant, Network, Controller, Meta). Hourly automation ≈ 18,000 rows/day — comfortably within the CSV store,
with the Storage page's archive/delete-by-range to cap footprint and the `(module, component_id,
created_at)` index keeping trend/RUL queries fast under MySQL later. **The module set is complete (11/11).**

*(End of the data-volume chapter — the notebook is complete.)*
