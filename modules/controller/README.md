# Controller / Compute module — the Controller / Compute PdM chapter

Predictive maintenance for the **controller compute node(s)** — the compute host that runs the WES /
database driving the whole ASRS. Like Network, this is an **infrastructure / cross-feature** module: a
saturating controller starves the WES and slows **every** shuttle/lift/GTP operation, so it is an early
warning for the whole plant and the hook for the future meta-module (Module 11).

- **`compute_node`** — a controller compute node. **A single node** this snapshot: **`db_controller`**
  (the SQL/DBA database–controller server whose CPU the `getCPUDetails` proc reports). **Signal = CPU
  utilization%** = `100 − cpu_idle`, with the SQL Server's CPU share (`cpu_sql`) as context. A healthy
  controller keeps idle headroom (this snapshot: **30–44% utilization**, ~28–41% of it SQL); a
  saturating controller (utilization climbing toward 80–95%) is a **crash/throttle precursor**.

**This is CPU-only, single-node, and current-state.** The mapping (§10) billed it as "CPU / memory
utilization trend" across "controller compute nodes" (plural); live SQL shows one aggregate CPU row, no
memory, no per-host breakdown, and no in-feed trend. Scoped honestly to CPU utilization%. The feature
extractor **keys by a host/node column if the proc ever returns per-host rows**, so the module scales to
N nodes with no code change.

This chapter documents the resolved source, every feature/formula, and — per the project requirement —
**exactly how each component's verdict and the module's overall status are reached**. Tunables live in
[`module.yaml`](module.yaml); the pipeline is `fetch.py → features.py → health.py` (which calls
`rca.py`); it self-registers in `__init__.py`. The data is **live/current-state**.

> **Mapping finding (Session 10).** The single candidate — **CPU Stats** (`CwTEp_GSz`, CPU Utilization)
> — is genuine health data (not operational/inventory), but re-verifying by live SQL corrected the shape:
> - Panel `#17 "CPU Utilisation"` runs `EXEC [DBA].[dbo].[getCPUDetails]` and returns a **single row**:
>   `cpu_idle`, `cpu_sql` (e.g. 56/41 or 70/28). **CPU-only**, **one node**, **no timeseries** — the same
>   row is returned at `now-6h`, `now-2d`, `now-30d` (the window does **not** filter the proc).
> - So there is **no in-feed trend or memory metric**. As with Gate/Bin/Tracker, **the store overcomes
>   this**: each PdM run snapshots the current utilization%, so sustained-high + trend accrue across runs.
> - **Ruled out:** "JIT Frame Unallocated" (`sales_order_line` JIT frames = inventory, not compute) and
>   the OPC/Kepware dataloggers (raw per-device telemetry, no CPU, no CSV).

---

## 1. Data source (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary** | CPU Stats (`CwTEp_GSz`) | `#17` "CPU Utilisation" | `cpu_idle, cpu_sql` (`EXEC getCPUDetails`) | Current CPU utilization% (`100 − cpu_idle`) + SQL CPU share; the compute-node universe. |

**Current-state (not a timeseries, unlike Conveyor).** `#17` returns the same single row regardless of
the fetch window, so the window does not scale the fetch. **The store provides the history** the feed
lacks — regular automation is what makes sustained-high + trend predictive. Default window `now-2d`.

## 2. Features (`features.py`)

Per node (`component_type=compute_node`) from `#17`:

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `cpu_idle_pct` | as reported | Idle headroom. |
| `utilization_pct` | `100 − cpu_idle` | **The core compute signal.** |
| `cpu_sql_pct` | `cpu_sql` | SQL Server's CPU share. |
| `cpu_other_pct` | `100 − cpu_idle − cpu_sql` | Non-SQL CPU (OS/other processes). |
| `sql_share` | `cpu_sql / utilization_pct` | Share of **used** CPU that is SQL (context). |
| `consecutive_high` | *(health.py)* consecutive recent runs `utilization ≥ sustained_high_pct` incl. now | Store-driven persistence. |

**Component id** = a `host`/`node`/`server` column if the proc returns one (scalable to N nodes), else
the single `db_controller`.

## 3. How a single component's verdict is reached (`health.py`)

`health = clamp(100 − Σ penaltyᵢ, 0, 100)`, `penaltyᵢ = min(valueᵢ·weightᵢ, capᵢ)`:

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `saturation` | `utilization_pct − saturation_floor_pct` (floor 60%) | 2.5 · 70 |
| `sustained_high` | `max(consecutive_high − 1, 0)` — consecutive recent runs `utilization ≥ sustained_high_pct` (80%) | 6.0 · 30 |

The saturation term is the backbone: a controller loses no points below the floor (healthy headroom),
then degrades steeply toward saturation — the calibration gives **≤ 60% → ok, 70% → watch, 80% → warn,
90%+ → critical** on the within-run reading alone. `sustained_high` is **store-driven**: a controller
pinned near saturation *run after run* (not a transient spike) accrues an escalating persistence penalty
(a genuine crash/throttle precursor). `cpu_sql` share is **context** (a DB-controller is expected to be
SQL-heavy) — surfaced in the RCA, not penalised.

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`.

**Time-to-maintenance + regime:** the feed has no in-feed trend, so RUL is store-based — **cold-start**
uses a coarse band by tier (tighter than the event modules — critical 24 h, warn 96 h, watch 336 h,
since compute saturation escalates fast); **trend** (≥ 5 runs) fits the node's `health_score` trajectory
and projects when it crosses the critical line (capped at 1 year). Confidence is decent at cold-start
(a clear utilization% reading is meaningful immediately) and rises with history.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by points removed; `primary_cause` names the dominant symptom, e.g.
*"High CPU utilization: 92% (8% idle) — controller throttle/crash risk"*, *"CPU pinned high (85%) across
N consecutive runs — sustained controller saturation"*, or the healthy state *"CPU healthy (30%
utilization, 70% idle, 28% SQL)"*. A very high SQL share adds an *"— SQL-dominated load"* note.

**Cross-feature flag (the point of this module):** when the node is saturated (**warn or worse**), the
RCA raises a system-wide **`meta`** cross-flag — *"controller CPU saturated → system-wide throttle risk:
starves the WES and slows every shuttle/lift/GTP operation"* — the hook for the meta-module (Module 11)
to chain `compute-saturation → system-wide throttle → downstream shuttle/lift errors`.

## 5. How the overall module status is reached

The **Controller / Compute PdM** tile shows the **worst risk tier among all compute nodes** (`critical >
warn > watch > ok`), the per-tier counts, and the last-run time. With a single node today it mirrors that
node; the design scales to N nodes if per-host CPU appears. Identical rollup for every module
(`core/registry.py`).

## 6. Validation (this session)

Two `now-2d` runs on **live data** scored **1 node** each (1 row fetched, ~1.8 s/run — the fastest fetch
in the system):

- **Live CPU, live:** `db_controller` read **30% utilization** (70% idle, 28% SQL) → **ok**, health 100.
  (An earlier sample read 44%/56%/41% — confirming it is a live snapshot the store captures over time.)
- **Saturation gradient (offline logic check):** 44% → **ok** (100), 70% → **watch** (75), 80% → **warn**
  (50) + `meta` flag, 92% → **critical** (30), 98% → **critical** — the `meta` cross-flag fires only at
  warn+.
- **Sustained-high (store), verified:** 85% utilization with 5 prior runs ≥ 80% → `consecutive_high = 6`,
  sustained penalty applied on top of saturation → deep critical (the crash-precursor persistence signal).
- **Trend, verified:** a declining-health trajectory across ≥ 5 runs entered the **trend** regime.
- **Scalability, verified:** a synthetic 2-row feed with a `host` column produced two nodes (`ctrl_a` ok,
  `ctrl_b` critical) — the module scales to N nodes with no code change.
- **Confidence, live:** rose 0.625 → 0.725 between run 1 and run 2 as history accrued.

See `/module/controller` (with its in-page Methodology section), `scripts/inspect_controller.py`, and the
distribution helper in `scripts/analyze_controller_primary.py`.

## 7. Running it

- Dashboard: `/module/controller` → pick a window → **Run controller now**.
- API: `POST /api/run {"module":"controller","window":"now-2d"}`.
- Automation: enable the `controller` (or `global`) scope on the Automation page. The feed is
  current-state, so **regular automation is essential** — it is what turns the current CPU snapshot into
  a sustained-high + trend signal and lets the module warn *before* a controller saturates.
- Discovery/inspection: `.venv/bin/python scripts/inspect_controller.py discover | meta | sample`;
  reading helper: `.venv/bin/python scripts/analyze_controller_primary.py --window now-2d`.

## 8. Future enrichment

- **Memory + per-host CPU** — the mapping's original "CPU / memory" intent needs a richer feed (per-host
  CPU% + memory% + load). The OPC/Kepware dataloggers (`3HJAGPbVk`, `SBaBnPb4z`) or an OS-level exporter
  are candidate sources; the feature extractor already keys by host, so adding nodes needs no code change.
- **Meta-module chaining** — the `meta` cross-flag is the hook for Module 11 to correlate
  `controller saturation → network/shuttle degradation → bin blocks` compound failures.
- As automation accumulates runs, the **trend** RUL and sustained-high penalty sharpen automatically.
