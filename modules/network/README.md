# Network / Comms module — the Network / Comms PdM chapter

Predictive maintenance for the **controller communication layer** — the wireless comms link
between the WES/controller and each shuttle. Unlike the equipment modules, this is an
**infrastructure / cross-feature** module: comms degradation on a shuttle **precedes and causes**
its pick/handling errors, so a flagged link is an early warning for the Shuttle module and, when
downtime clusters on an aisle, for a possible aisle access-point/controller common cause (the future
meta-module). It is the upstream counterpart to the `→ network` flags the **Lift** (comm error codes
3/4) and **Shuttle** (servo-drive faults) modules already emit.

- **`network_link`** — a per-shuttle comms link. **124 links** (`QD_Shuttle_<aisle>_<unit>`, keyed by
  `shuttle_id`). **Signal = network downtime%** = `100 − uptime%`, where `uptime%` comes from Quadron
  Network status: the fraction of window time each shuttle spent in a `SHUTTLE_NETWORK_STATUS`
  disconnect. A healthy link is disconnected only ~0–3% of the time (fleet median **3.25%**); a
  flaky/degrading link's downtime% climbs (worst **29.7%** this snapshot).

**This is the only live network feed, and it is per-shuttle.** The mapping (§9) called it "latency,
packet loss, link state"; live SQL shows it is actually per-shuttle **uptime% / disconnect-duration**
(link state over time) — there is no latency-ms or packet-loss-% metric. Scoped honestly to downtime%.

This chapter documents the resolved source, every feature/formula, and — per the project requirement —
**exactly how each component's verdict and the module's overall status are reached**. Tunables live in
[`module.yaml`](module.yaml); the pipeline is `fetch.py → features.py → health.py` (which calls
`rca.py`); it self-registers in `__init__.py`. The data is **live/windowed** (not frozen).

> **Mapping finding (Session 9).** The single candidate — **Quadron Network status** (`gL0OBnq7z`,
> Maintenance) — is genuine health data (not operational/inventory, unlike Sessions 7/8's dropped
> dashboards), but re-verifying by live SQL corrected two things:
> - The metric is **per-shuttle uptime%** derived from `shuttle_error` where
>   `error_type='SHUTTLE_NETWORK_STATUS'` — **not** latency/packet-loss, and the component key is the
>   **shuttle** (its comms link), not a per-controller/per-link device.
> - `SHUTTLE_NETWORK_STATUS` is a **different error subset** than the Shuttle module's mechanical
>   FORK/TELESCOPIC errors (which are frozen at 2023 and do **not** include network status), so scoring
>   comms here does **not** double-count the Shuttle module. This is a distinct facet of the same shuttle.

---

## 1. Data source (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary (windowed)** | Quadron Network status (`gL0OBnq7z`) | `#4` "Shuttle network status specific date" | `shuttle_id, Value` (uptime%) | Per-shuttle **windowed** downtime% + the 124-link roster. |
| Secondary (recency) | Quadron Network status | `#2` "shuttle/day %uptime" | `shuttle_id, Value` (uptime%) | Per-shuttle **today** downtime% (since midnight) — flags links degrading *now*. |

**Windowing (important).** `#4` is filtered by a `${Date}` template var (`WHERE created_time > ${Date}`),
so the fetch sets `${Date}` = the **window start** (`now − N`) → a windowed uptime% (a wider window
smooths the average). `#2` is scoped to **since-midnight today** (`GETDATE()`), giving a recency
signal. Both are **live-computed** from `shuttle_error` (`error_type='SHUTTLE_NETWORK_STATUS'`,
`status=1`). Default window `now-2d`. Nothing hard-codes 2 days.

**The uptime formula (from the panel SQL):**
`uptime% = (1 − Σ DATEDIFF(second, created_time, updated_timestamp) / elapsed_seconds_since_${Date}) × 100`
— i.e. one minus the fraction of window time the shuttle spent in a network-disconnect state.

## 2. Features (`features.py`)

Per link (`component_type=network_link`) from `#4` (+ `#2` joined by `shuttle_id`):

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `uptime_pct` / `downtime_pct` | from `#4`; `downtime = 100 − uptime` | **The core comms signal.** |
| `today_uptime_pct` / `today_downtime_pct` | from `#2` (best-effort) | Today's comms state (recency). |
| `today_delta_pct` | `today_downtime − window_downtime` | `> 0` ⇒ the link is degrading *now* vs its window average. |
| `aisle` | `aisle_<NN>` parsed from `QD_Shuttle_<NN>_<unit>` | For the aisle-clustering cross-feature. |
| `downtime_peer_z` | *(within-snapshot)* robust z of `downtime_pct` vs the 124-link fleet | Peer deviation (MAD, std fallback). |
| `aisle_mean_downtime_pct` / `aisle_link_count` | mean downtime% over the aisle's links | Aisle common-cause detection. |

## 3. How a single component's verdict is reached (`health.py`)

`health = clamp(100 − Σ penaltyᵢ, 0, 100)`, `penaltyᵢ = min(valueᵢ·weightᵢ, capᵢ)`:

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `downtime_abs` | `downtime_pct − downtime_abs_floor_pct` (floor 3%) | 3.0 · 45 |
| `downtime_peer_z` | `downtime_peer_z` — **gated**: only when `downtime_pct ≥ peer_z_min_downtime_pct` (4%) | 4.0 · 16 |
| `recent_spike` | `today_downtime_pct − recent_spike_floor_pct` (5%) — **only when `today_delta > 0`** (worse today than the window) | 1.5 · 20 |
| `recurrence` | prior runs whose **downtime%** was ≥ `recur_min_downtime_pct` (6%) — downtime-specific | 6.0 · 30 |

The absolute term is the backbone (downtime above a fleet-normal floor); peer-z is **gated** by a
minimum absolute downtime so a fleet-median link is never flagged; the recency spike catches
accelerating degradation (a link far worse today than its window average — e.g. `QD_Shuttle_01_19`
was 29.7% over the window but 67% today); recurrence is **downtime-specific** so peer-z/recency
artifacts don't self-reinforce. Downtime is partly environmental (RF interference/congestion), so the
model leans on peer deviation + recurrence + the today-spike to isolate a genuinely degrading link
from fleet-wide noise.

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`.

**Time-to-maintenance + regime:** no cycle counter, so RUL is time/recurrence-based — **cold-start**
uses a coarse band by tier (critical 48 h, warn 240 h, watch 720 h); **trend** (≥ 5 runs) fits the
link's `health_score` trajectory and projects when it crosses the critical line (capped at 1 year).
Confidence is decent even at cold-start (the downtime% metric is meaningful immediately) and rises
with downtime severity, the today signal, and history.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by points removed; `primary_cause` names the dominant symptom, e.g.
*"High network downtime: 29.7% (70.3% uptime) — flaky/degrading comms link"*, *"Comms degrading now:
67.0% downtime today vs 29.7% over the window"*, *"Network downtime elevated across N prior runs —
persistent comms degradation"*, or the healthy state *"Comms healthy (99.9% uptime, 0.1% downtime)"*.

**Cross-feature flags (the point of this module):**
- Every **flagged** link (tier ≠ ok) cross-links to the **Shuttle module** — comms drops precede/cause
  that shuttle's pick/handling errors, so its mechanical verdict should be read together with this one.
- When downtime **clusters on an aisle** (mean downtime ≥ `aisle_cluster_downtime_pct` **or** ≥
  `aisle_cluster_min_links` flagged links), an aisle-level **`meta`** flag is added (a candidate aisle
  access-point / zone-controller common cause) — the chain `network → shuttle → downstream` the future
  meta-module correlates.

## 5. How the overall module status is reached

The **Network / Comms PdM** tile shows the **worst risk tier among all links** (`critical > warn >
watch > ok`), the per-tier counts, and the last-run time; the per-component table (sorted worst-first)
shows the full picture. Identical rollup for every module (`core/registry.py`).

## 6. Validation (this session)

Two `now-2d` runs on **live data** scored **124 links** each (224 rows fetched, ~8 s/run):

- **Live downtime distribution:** median **3.25%**, p90 6.5%, p99 16.9%; latest run **3 critical / 6
  warn / 12 watch / 103 ok**.
- **Worst links, live:** `QD_Shuttle_01_19` = **29.7%** downtime (70.3% uptime) and **67% today** →
  **critical** (all four penalties near max); `QD_Shuttle_04_06` 13.5% window / 31.5% today (recency
  spike) → **critical**; `QD_Shuttle_06_06` 17.6% → **critical**. Healthy links (`QD_Shuttle_06_22/23/24`
  ~0.4%) → **ok** at 100.
- **Aisle clustering, live:** **aisle_01** is the worst (mean 6.74%, driven by `01_19` + `01_12` +
  `01_11` + `01_16/17/18`); 20 links carried the aisle-level `meta` cross-flag (aisles 01/04/06) — a
  candidate aisle AP/controller common cause.
- **Recency, live:** the today-vs-window delta caught `01_19` accelerating (29.7% → 67% today) and
  `04_06` (13.5% → 31.5%) — the `recent_spike` penalty fired for both.
- **Cross-run recurrence, live:** run 2 gave every run-1 offender `recurrence_runs = 1` (+6 points),
  dropping health (`01_19` 19.0 → 13.0) — the store-driven longitudinal signal on real data.
- **Cross-feature, verified:** every flagged link carries a `shuttle` flag; healthy links carry none.
- **Trend** was proven with an offline logic check (a declining-health link entered the **trend** regime).

See `/module/network` (with its in-page Methodology section), `scripts/inspect_network.py`, and
`scripts/analyze_network_primary.py`.

## 7. Running it

- Dashboard: `/module/network` → pick a window → **Run network now**.
- API: `POST /api/run {"module":"network","window":"now-2d"}`.
- Automation: enable the `network` (or `global`) scope on the Automation page. Downtime% is windowed,
  so a single run is already meaningful; **regular automation** turns recurrence + trend RUL predictive
  and lets the today-vs-window recency signal track accelerating degradation between runs.
- Discovery/inspection: `.venv/bin/python scripts/inspect_network.py discover | meta | sample`;
  distribution analysis: `.venv/bin/python scripts/analyze_network_primary.py --window now-2d`.

## 8. Future enrichment

- **A true latency / packet-loss feed** (from the OPC/Kepware layer or SNMP) would add continuous
  quality metrics beyond uptime% — the mapping's original intent. The OPC dataloggers (`3HJAGPbVk`,
  `SBaBnPb4z`) are candidate raw sources if their telemetry becomes fetchable.
- **Lift comms** — the Lift module already classifies comm error codes (3 drive-ethercat, 4 ethernet);
  once a per-lift network feed exists it would extend this module beyond shuttles.
- **Meta-module chaining** — the aisle-cluster + shuttle cross-flags are the hooks for the Module 11
  meta layer to correlate `network → shuttle errors → bin blocks` compound failures.
- As automation accumulates runs, the **trend** RUL and recurrence penalties sharpen automatically.
