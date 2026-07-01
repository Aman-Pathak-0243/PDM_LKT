# BIN / TOTE-MECHANICAL module — the Bin PdM chapter

Predictive maintenance for the ASRS **storage bin slots / rails** — the ~56,000 grid
positions (`Aisle–Level–Location–Deep`) a shuttle seats totes into. When a tote won't seat
or tilts, the slot **blocks** (a *bin block* / *tote tilt*). Like Tracker, this is an
**anomaly / recurrence** module: a healthy slot blocks a tote rarely and briefly; a degrading
**slot/rail** blocks totes repeatedly, keeps a block **unresolved** for a long time, and
**recurs at the same location** (not random).

This chapter documents the resolved sources, every feature/formula, and **how each slot's
verdict and the module's overall status are reached**. Tunables in [`module.yaml`](module.yaml);
pipeline `fetch.py → features.py → health.py` (calls `rca.py`); self-registers in `__init__.py`.

> **Mapping correction (Session 6).** The mapping (§5) listed **Aggregate Error Report** as
> the bin secondary ("location-level error aggregation"). Live SQL re-confirms it is
> `shuttle_error UNION lift_error` keyed by `robot_id` with **no location column** (6,081
> rows) — it carries no bin/slot signal and is covered by the Shuttle + Lift modules, so it is
> **dropped**. The real bin signal is the live `bin_blocked` table (tote-tilt) plus the
> historical block log. (**Bin Blocked Statistics** `wNp3FGZNk11` reads the *same* live
> `bin_blocked` table server-side — its `#14 "Repeated Location"` / `#6 total` / `#8 aisle-wise`
> are equivalent to our primary, so it is documented but not separately fetched.)

---

## 1. Data sources (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary** | Bin blocked (i.e. tote tilted) (`GOqISik4k`) | `#2` "Bin Blocked report" | `tracker, aisle, zone, level, location, container, quantity, blockedTime` | Current set of blocked bins (`bin_blocked` status=0) per **location**. Component universe. |
| Secondary (historical) | Bin Block History (`hIVZMtGVz`) | `#2` "Bin block Block History" | `shuttle_id, tracker, source, destination, bay, zone, TIMING` | Per-location **historical** block frequency (chronic-slot enrichment). Frozen 2022-24. Best-effort. |
| Non-signal (skipped) | Bin blocked (i.e. tote tilted) | `#4` update_bin_block / `#5` bids | — | `#4` is an UPDATE (write/action) panel; `#5` is unacknowledged bids — neither is a bin-block signal. |

**Component universe:** the grid **bin locations currently blocked** (live `bin_blocked`,
`status=0`) — a dynamic anomaly set (~40 this snapshot, each blocked once; **no within-snapshot
clustering**). Only currently-blocked slots are scored; a slot with no active block is healthy
(standard anomaly-detection semantics).

**Current-state primary.** `#2` reads the live `bin_blocked` table, so all current blocks are
recent. Its partition `LEFT JOIN` inflates rows (one per material partition), so rows are
**deduped** to blocked-tote events (`location, tracker, blockedTime`) before grouping by location.
The 2-day retention is overcome by **our store**: each run snapshots the blocked slots, so
cross-run recurrence accrues (CLAUDE.md §6) — **regular automation is what makes this module
predictive**.

**Historical secondary.** Bin Block History `#2` (`shuttle_command status=10` with `source`/
`destination` bin locations) is **frozen** (2022-12 → 2024-09, ~26k rows, max **263** blocks at
one slot). We count each location's **SOURCE** frequency (bin-format `NNN-NN-N-NNN-N-NN`) as a
chronic-slot fingerprint. It barely overlaps the current blocks (chronic slots are mostly not
blocked right now), so it **enriches** cold-start / RCA rather than dominating, and is fetched
best-effort (the run continues on current + store recurrence if it fails).

## 2. Features (`features.py`)

Per currently-blocked location. `as_of = max(blockedTime)` in the set (tz-robust — `blockedTime`
is plant-local); a block's age = `as_of − its blockedTime`.

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `blocked_now` | in the current `bin_blocked` set | The slot has a stuck tote right now. |
| `current_block_count` | distinct blocked totes at the slot (post-dedup) | **Cluster** — usually 1; >1 = several totes stuck at one slot. |
| `block_age_hours` | `as_of − oldest blockedTime` at the slot | **How long the block has stayed unresolved** (stuck vs being cleared). |
| `distinct_containers` | unique containers stuck at the slot | Independent totes affected. |
| `historical_block_count` | occurrences as SOURCE in the frozen block log | **Chronic-slot fingerprint.** |
| `aisle` / `level` / `deep` | parsed from the slot address | Location. |
| `aisle_block_count` / `aisle_is_outlier` | blocks on this aisle / peer-relative concentration outlier | Common-cause context (drives the cross-module flag). |
| `recurrence_runs` | *(health.py)* prior runs this slot appeared blocked | **Cross-run recurrence — the strongest live signal as history grows.** |
| `block_age_peer_z` | *(health.py)* robust z of `block_age_hours` vs peer blocked slots | Blocked far longer than peers. |

## 3. How a single slot's status is reached (`health.py`)

Penalty model: `health = clamp(100 − Σ penaltyᵢ, 0, 100)`, `penaltyᵢ = min(valueᵢ·weightᵢ, capᵢ)`.

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `blocked_base` | a tote is blocked here now (flat) | 10 · 10 |
| `block_age` | `block_age_hours` beyond a grace (2 h) | 2.0 · 35 |
| `cluster` | `current_block_count − 1` | 12 · 24 |
| `historical` | `historical_block_count` (frozen chronic freq) | 0.4 · 24 |
| `recurrence` | `recurrence_runs` (prior runs blocked) | 8.0 · 40 |
| `peer_z` | `block_age_peer_z` | 4.0 · 14 |

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`. A one-off,
freshly-blocked slot stays near **ok** (base 10 → health 90); a slot stuck a long time, blocked
by several totes, on a chronic slot, or **recurring across runs** climbs to warn/critical — i.e.
*recurrence, not a single random block, drives the verdict*.

**Time-to-maintenance + regime:** no cycle counter and a current-state panel, so RUL is
time/recurrence-based — **cold-start** uses a coarse band by tier (critical 48 h, warn 240 h,
watch 720 h); **trend** (≥ 5 runs) projects the slot's health trajectory over time. Cold-start
confidence rises with block-age, chronic history, and any prior recurrence.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by points removed; `primary_cause` describes the block ("Slot keeps
blocking totes — flagged in K prior runs", "Block unresolved for N h — tote stuck", "Chronic
slot — blocked N times in history", "N totes blocked at this slot at once"). **Cross-module
flag:** when an aisle has an **anomalous concentration** of current blocks (a peer-relative
outlier, not an absolute floor), the RCA flags that **aisle's shuttle** (it may be mis-seating
totes — Shuttle module; mislocation → Tracker) rather than blaming each slot alone.

## 5. How the overall module status is reached

The **Bin / Tote-Mechanical PdM** tile shows the **worst risk tier among the currently-blocked
slots** (critical > warn > watch > ok), the per-tier counts, and the last-run time; the
per-slot table (sorted worst-first) shows the full picture. Identical rollup for every module
(`core/registry.py`).

## 6. Validation (this session)

A `now-2d` run on **live data** scored **40 blocked slots** (from 224 partition-inflated rows +
the 26,638-row historical log, in ~5.5 s). All current blocks were fresh (0–3 h old, each slot
blocked once), so the model correctly read **32 ok + 8 watch** — the 8 watch being the
longest-blocked / peer-age outliers (`004-10-1-104-1-01` blocked 3.1 h → watch). 3 currently-
blocked slots were also **chronic** in the frozen log (`003-05-1-071-1-02`, hist 7). A **second
run** showed the still-blocked slots accruing `recurrence_runs = 1`, dropping their health
(79.99 → 71.98) with cause *"Slot keeps blocking totes — flagged in 1 prior runs"* — the
longitudinal recurrence mechanic working on live data. The aisle cross-flag correctly did **not**
fire (blocks were spread across aisles, no anomalous concentration); the synthetic test confirms
it fires on a genuine per-aisle concentration. See `/module/bin_mech` (with its in-page
Methodology section) and `data/inspection/s6_bin_mech.png`.

## 7. Running it

- Dashboard: `/module/bin_mech` → pick a window → **Run bin_mech now**.
- API: `POST /api/run {"module":"bin_mech","window":"now-2d"}`.
- Automation: enable the `bin_mech` (or `global`) scope — recurrence across runs is its
  strongest signal, so regular automation materially sharpens it.

## 8. Future enrichment

- A **live** (non-frozen) block-history feed would turn `historical_block_count` into a rolling
  recent-block-rate per slot (sharper than the 2022-24 snapshot).
- Joining the blocked tote's **shuttle** (from Bin Blocked Statistics `#2`, keyed on tracker)
  would let the cross-module flag name the *specific* shuttle rather than the aisle's shuttle.
- As automation accumulates runs, the **trend** RUL activates automatically — recurrence
  frequency becomes a time-to-maintenance projection with rising confidence — no code change.
