# TRACKER / Position-Sensor module — the Tracker PdM chapter

Predictive maintenance for the ASRS **grid position sensors / tracker readers** — the
fixed devices that resolve where each tote's tracker tag is on the grid. When the
system loses a tote, its tracker tag sticks at an anomalous grid cell: a **bad-tracker
event**. Unlike Lift (time) and Shuttle (cycles), this is an **anomaly/recurrence**
module: a healthy position produces isolated one-offs; a degrading one accumulates a
**cluster** of mislocated totes at the same location and keeps **recurring across runs**.

This chapter documents the resolved source, every feature/formula, and **how each
position's verdict and the module's overall status are reached**. Tunables in
[`module.yaml`](module.yaml); pipeline `fetch.py → features.py → health.py` (calls
`rca.py`); self-registers in `__init__.py`.

> **Mapping + kickoff correction (Session 4).** The kickoff framed the component as a
> "tracker ID (grid position sensor)". Live inspection shows the `tracker` field is a
> **per-tote position tag** — **86 distinct tags in 86 rows, zero recurrence within a
> snapshot** — so a tag is not a fixable, recurring unit. The unit that physically
> degrades and *clusters* is the grid **`location`** (uniform shape `aisle_<NN>_bt_<NN>`):
> `aisle_03_bt_10` had **5** stuck totes, `aisle_04_bt_5` had **4**. The component is
> therefore the **location (position sensor)**, scored from the cluster of bad-tracker
> events on it. The mapping's secondary, **Aggregate Error Report**, was verified to be
> `shuttle_error UNION lift_error` keyed by `robot_id` with **no tracker/location column**
> (14,012 SHUTTLE + 3,356 LIFT rows) — it carries no tracker signal and is already covered
> by the Shuttle + Lift modules, so it is **dropped as a tracker source**.

---

## 1. Data sources (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary** | Bad Tracker Diagnosis (`VAW2nmqIz`) | `#2` "Bad Tracker" | `tracker, container, location, created_time, shuttle_id, task_type, status, shuttle Status Description, lift_id, lift_status, lift Status Description` | Current set of mislocated totes → per-location cluster. |
| Context | Bad Tracker Diagnosis | `#4` "Total BT Totes" | `Value` | Scalar count of bad-tracker totes (snapshot context). |
| Drill-down (not used) | Bad Tracker Diagnosis | `#8/#6/#10` | template-var panels (`${tracker}`/`${lift}`/`${shuttle}`) | Per-entity drill-downs (e.g. tracker journey); documented as future RCA enrichment, **not** population signals. |

**Component universe:** the grid **locations** that currently exhibit bad-tracker events
(dynamic, data-driven; ~54 this snapshot). Absence of a location ⇒ it is healthy (standard
anomaly-detection semantics — only anomalous positions are scored).

**Current-state panel.** `#2` returns the **same 86 rows at `now-2d` and `now-90d`** — the
dashboard window does **not** filter it. The 2-day-retention limit is overcome by **our
store**: each PdM run snapshots the bad locations, so recurrence/persistence accrue over
runs (CLAUDE.md §6). The module's `window` drives the **recent-vs-stale split** applied
in-code to `created_time`, not a server-side filter. `status 8 = SHUTTLE_PICK_ERROR`,
`lift_status 2 = ERROR` (from the panel SQL `CASE`).

## 2. Features (`features.py`)

Per grid location over the current snapshot. `as_of = max(created_time)`; a tote is
**recent/active** if its age ≤ `min(recent_days, window_days)`.

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `bad_count` | count of mislocated totes at the location | **Cluster size — the core signal.** |
| `recent_bad_count` | totes with age ≤ active-days | Active vs long-abandoned. |
| `recent_share` | `recent_bad_count / bad_count` | Fraction currently active. |
| `newest/oldest/median_age_days` | age of stuck totes (days) | Staleness profile. |
| `distinct_shuttles` | unique `shuttle_id` at the location | Robot breadth (many ⇒ the position is the common cause). |
| `dominant_shuttle` / `dominant_shuttle_share` | top shuttle + its share | Drives the shuttle cross-flag. |
| `distinct_containers` | unique containers stuck | Independent totes affected. |
| `lift_involved_count` / `lift_error_count` | lifts present / lifts in ERROR | Lift cross-feature. |
| `pick_error_count` | rows with `SHUTTLE_PICK_ERROR` | Pick-side failures at the position. |
| `dominant_task` | top `task_type` (PICKING/REALLOCATION/PUTAWAY) | Operation context. |
| `stuck_trackers` | up to 10 tracker tags (for RCA drill-down) | Evidence for the flag. |
| `bad_count_peer_z` | robust z of `bad_count` vs all locations (MAD, std fallback) | Peer deviation. |
| `recurrence_runs` | *(added in `health.py`)* prior runs that flagged this location | **Longitudinal recurrence — the strongest signal as history grows.** |

## 3. How a single position's status is reached (`health.py`)

Penalty model: `health = clamp(100 − Σ penaltyᵢ, 0, 100)`, `penaltyᵢ = min(valueᵢ·weightᵢ, capᵢ)`.

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `cluster` | `bad_count` (totes stuck at the position) | 8 · 34 |
| `recent_cluster` | `recent_bad_count` (active totes) | 9 · 30 |
| `recurrence` | `recurrence_runs` (prior runs flagged) | 7 · 30 |
| `multi_shuttle` | `distinct_shuttles − 1` | 5 · 15 |
| `lift_involved` | `lift_error_count` | 6 · 12 |
| `peer_z` | `bad_count_peer_z` | 5 · 18 |

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`.

**Time-to-maintenance + regime:** no cycle counter and a current-state panel, so RUL is
time/recurrence-based — **cold-start** uses a coarse band by tier (critical 48 h, warn 240 h,
watch 720 h); **trend** (≥ 5 runs) projects the location's health trajectory over time.
Cold-start confidence rises with cluster size (more evidence) and any prior history;
trend confidence rises with history depth.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by points removed; `primary_cause` describes the cluster
("5 totes mislocated at this position", "N recent totes mislocated", "Position keeps
mislocating totes — flagged in K prior runs", "N shuttles mislocated here — the position
is the common cause"). **Cross-module flags:** one shuttle dominating a clustered/recurring
position (≥60 % share) → **Shuttle** module (possible shuttle positioning fault, e.g.
`NOT_AT_CENTRE`); a lift in ERROR on the row → **Lift** module. The payload carries the
stuck tracker tags for drill-down via Bad Tracker `#8` (Tracker Journey).

## 5. How the overall module status is reached

The **Tracker / Position-Sensor PdM** tile shows the **worst risk tier among all scored
locations** (critical > warn > watch > ok), per-tier counts, and the last-run time; the
per-location table (sorted worst-first) shows the full picture. Identical rollup for every
module (`core/registry.py`).

## 6. Validation (this session)

A `now-7d` run on **live data** scored **54 locations**: `aisle_03_bt_10` (5-tote cluster,
peer-z 4.0) → **critical**; `aisle_04_bt_5` (4), `aisle_01_bt_15` (3), `aisle_03_bt_2`
(2 recent) → **warn**; multi-tote and recent singles → **watch**; isolated long-stale
totes (1 tote stuck 130–420 days) → **ok**. A **second run** dropped `aisle_03_bt_10`
39 → 32 as `recurrence_runs` accrued (1 prior run), demonstrating the longitudinal
sharpening. See `/module/tracker` (with its in-page Methodology section) and
`data/inspection/s4_tracker.png`.

## 7. Running it

- Dashboard: `/module/tracker` → pick a window → **Run tracker now**.
- API: `POST /api/run {"module":"tracker","window":"now-7d"}`.
- Automation: enable the `tracker` (or `global`) scope on the Automation page.

## 8. Future enrichment

- **Tracker Journey (`#8`)** drill-down: for a flagged location's worst stuck tracker,
  fetch `&var-tracker=<id>` to show its source→destination history (extends `fetch.py` +
  `rca.py`, no `core/` change).
- As automation accumulates runs, the **trend** RUL activates automatically — recurrence
  frequency becomes a time-to-maintenance projection, with rising confidence.
- A discrete `location_tracker`-history feed (if exposed) would let recurrence be measured
  server-side rather than only across our snapshots.


---

> **Audit hardening (Session 12 — 2026-07-01).** `cluster` now scores **stale** totes only (disjoint from `recent_cluster`) and `peer_z` cap reduced, so one cluster is no longer triple-counted. `dominant_shuttle_share` divides by shuttle-attributed rows (NaN-shuttle rows no longer dilute the ≥0.6 cross-flag). Window parser fixed: Grafana `m`=minutes, `M`=months. RCA surfaces `pick_error_count`. `polyfit` guarded. See `docs/AUDIT_REPORT.md` and `docs/notebook/methodology.md §12` for the cross-cutting invariants.
