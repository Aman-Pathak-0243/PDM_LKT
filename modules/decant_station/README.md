# Decanting Station + Scanner module — the Decanting Station + Scanner PdM chapter

Predictive maintenance for the **decant** (inbound goods-receiving) area: the **barcode
scanners** on the decant/compaction line and the **decant operator stations** where cartons
are decanted into totes. Like `gtp_station`, this module scores **two physical component
types** in one plugin, because the mapped signal is dual — *"per-station scan-failure /
discrepancy climb → scanner or station degradation"*. Re-verifying every candidate source by
live inspection (the mapping has been wrong every session) showed the two signals are **very
unevenly supported** in Grafana:

- **`decant_scanner`** — a decant/compaction-line scan device. **9 devices** this snapshot:
  **7 decant infeed diverter-scanners** (`aisle_0N_decant_diverter`, incl.
  `aisle_01_decant_diverter_2`) + **2 compaction scanners** (`Compaction_scanner`,
  `Compaction_scanner_2`). **Signal = misread rate** = `NoReadCount / (ReadCount + NoReadCount)`.
  The decant diverters read almost everything (0.008–0.167% misread this snapshot); both
  compaction scanners run ~4% (they read harder/deformed barcodes) → **watch**. This is the
  **strong, live signal**, and it comes from the **GTP Scanner logs** feed (`lenskart_gtp`).
- **`decant_station`** — a decant operator station. **10 stations** (`DS001`–`DS010`) from
  Decanting station report #2 (roster + Active/Inactive). **There is NO live per-station
  fault/discrepancy feed** (see the correction below), so the station is scored **coarsely and
  honestly**: `active_status` is context, and only **offline-persistence** (Inactive across
  consecutive runs) or a **persistent idle-while-active** anomaly (Active but decanting nothing
  while the line is busy, across consecutive runs) subtract points. A single idle/Inactive run
  adds nothing; station verdicts carry deliberately **modest confidence**.

Decant scanners are **per-aisle infeed diverters** and decant stations are **operator
stations**, so — unlike GTP's `GS<NN>-SL<NN>` ↔ `GS<NN>` — there is **no 1:1 device↔station
mapping**. The RCA therefore adds only a **line-level** corroboration note when both entity
types look unhealthy in the same run.

This chapter documents the resolved sources, every feature/formula, and — per the project
requirement — **exactly how each component's verdict and the module's overall status are
reached**. Tunables live in [`module.yaml`](module.yaml); the pipeline is
`fetch.py → features.py → health.py` (which calls `rca.py`); it self-registers in
`__init__.py`. The data is **live/current** (not frozen).

> **Mapping corrections (Session 8).** The mapping (§8) listed five candidate sources and called
> two of them "barcode/carton scan-failure rate". Re-verifying every candidate by **live SQL +
> sampling** showed:
> - **Decanting station report** (`B4i1-HpVz`) `#2` is `select station_id, active_status, user_id
>   from station` — the decant **station roster** (10 stations), NOT "activity & faults".
> - **Discrepancy Marked Barcode** (`E_nYUnU4z`) `#2` and **Discrepancy Marked Carton**
>   (`LQMn4RU4k`) `#2` are **drill-down lookups** into `discrepancy_details` filtered by
>   `${Serial_No}` / `${Carton_Id}` (one barcode/carton at a time). `discrepancy_details` has **no
>   station column** (keyed `carton_id`/`serial_id`/`tote_id`) and the data is **frozen at 2022**
>   (sampled `create_timestamp` `2022-12-21`). They **cannot** yield a live per-station discrepancy
>   rate. **Dropped as health sources.**
> - **StationWise Decanted Cartons Count** (`n1oZnY_Vz`) `#2` is per-station `carton_count` over the
>   window — a real, live **throughput** signal (kept as the station secondary).
> - **Station-Material Wise Decants** (`3TbhR4TSz`) `#2` needs a `${hsn_classification}` var (no
>   population without it) — a per-material load profile, not health. **Not fetched.**
> - The real live decant health signal is therefore the **scanner misread rate** (from GTP Scanner
>   logs #8) + the **station roster/status/throughput** — no live discrepancy feed exists.
>
> **Cross-module reconciliation (Session 8).** The 9 decant/compaction scan devices were scored by
> the **GTP module (Module 7)** until this session (tagged subtype `decant`/`compaction`). They are
> now **owned here** and **excluded from GTP** (`gtp_station/module.yaml → scanner.exclude_subtypes`;
> `gtp_station/features.py` drops them from the universe + peer baseline), so **each device is owned
> by exactly one module** (CLAUDE.md §7). **GTP Scanner logs (`pK7-8NmVz`) #8 is a SHARED panel.**

---

## 1. Data sources (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary (scanner)** | GTP Scanner logs (`pK7-8NmVz`, shared) | `#8` "Scanner Read /No read Data" | `scanner, ReadCount, NoReadCount, efficiency_percentage` | Per-device misread rate; **filtered to the 9 decant/compaction devices** this module owns. |
| **Primary (station roster)** | Decanting station report (`B4i1-HpVz`) | `#2` "Decanting Station Report" | `Station ID, active_status (Active/Inactive), User` | The **10-station universe** (`DS001`–`DS010`) + status + assigned user. |
| Secondary (station throughput) | StationWise Decanted Cartons Count (`n1oZnY_Vz`) | `#2` "Station-Wise-Decanted-Cartons" | `station_id, carton_count` | Per-station decanted-carton throughput over the window (idle-while-active + utilization). |

**Windowing (important).** GTP Scanner logs `#8` and StationWise Decanted Cartons Count `#2` are
**time-filtered** (`create_time` / `updated_date BETWEEN $__timeFrom .. $__timeTo`), so a wider
`from=now-<window>` sharpens the misread rate + throughput. Decanting station report `#2` is a
current roster snapshot (10 rows regardless of window). The default window is `now-2d`.

**Dropped / deferred (documented, not fetched):** Discrepancy Marked Barcode (`E_nYUnU4z`) + Carton
(`LQMn4RU4k`) — frozen-2022 per-serial/carton drill-downs into `discrepancy_details`, **no station
key** → no live per-station discrepancy rate. Station-Material Wise Decants (`3TbhR4TSz`) — needs a
`${hsn_classification}` var. Decanting station report `#4` "Material Type Available" — partition
inventory. (These are recorded in `panel_catalog` with `role=none, is_signal=False`.)

## 2. Features (`features.py`)

**Scanner** (`component_type=decant_scanner`), per device from `#8` (filtered to decant/compaction):

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `read_count` / `no_read_count` / `total_scans` | summed per device (`total = read + noread`) | Scan volume in the window. |
| `misread_rate` / `misread_pct` | `no_read / total` (0 if no scans) | **The core scanner signal.** |
| `subtype` | parsed from the name | `decant` (diverter) or `compaction`. |
| `aisle` | `aisle_0N` from the name | The decant infeed aisle (decant diverters only). |
| `efficiency_percentage` | as reported by the panel | Cross-check (= `100·read/total`). |
| `misread_peer_z` | *(within-snapshot)* robust z of `misread_pct` vs decant devices with ≥ `min_volume_peer` scans | Peer deviation (MAD, std fallback). |

**Station** (`component_type=decant_station`), per station from roster `#2` (+ throughput `#2`):

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `active_status` / `is_active` | from the roster | Active/Inactive (context). |
| `user` | from the roster | Assigned operator (context / RCA). |
| `carton_count` / `throughput_per_day` | summed per station; `count / window_days` | Decant throughput over the window. |
| `line_busy` / `line_total_cartons` | `Σ carton_count ≥ line_busy_min_cartons` | Is the decant line busy this window (so idle-while-active is meaningful)? |
| `idle_while_active` | `is_active AND carton_count ≤ idle_floor AND line_busy` | **The one within-run station anomaly** (Active but decanting nothing while the line is busy). |
| `throughput_peer_z` | *(within-snapshot)* robust z of `carton_count` vs stations that decanted | **Context only** — low throughput is NOT penalized (it may be low load). |
| `consecutive_inactive` / `consecutive_idle_active` | *(health.py)* consecutive most-recent runs Inactive / idle-while-active incl. now | Offline / idle persistence (store-driven). |

## 3. How a single component's verdict is reached (`health.py`)

`health = clamp(100 − Σ penaltyᵢ, 0, 100)`, `penaltyᵢ = min(valueᵢ·weightᵢ, capᵢ)`. Two penalty
models, one per entity type:

**Scanner** (identical calibration to the proven `gtp_station` scanner model) — weight · cap:

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `misread` | `misread_pct`, **scaled by `volume_factor = min(1, total/min_volume_full)`** | 3.0 · 75 |
| `peer_z` | `misread_peer_z` — **gated**: only when `total_scans ≥ min_volume_peer` **and** `misread_pct ≥ peer_z_min_misread_pct` | 4.0 · 16 |
| `recurrence` | prior runs whose **misread%** was ≥ `recur_min_misread_pct` (misread-specific) | 6.0 · 30 |

The **volume gate** keeps a low-scan device's noisy rate from over-firing, and the peer-z gate
(min misread) keeps a clean decant diverter that sits slightly above a tight fleet median from being
flagged. Both compaction scanners (~4% misread, high volume) land at **watch** (misread ≈ 12 + peer-z
capped 16), not critical — they read genuinely harder barcodes, so the model flags them for
inspection without over-claiming.

**Station** — weight · cap. **Both penalties are cross-run** (a single idle/Inactive run adds
nothing), so a cold-start station is honestly `ok` at low confidence:

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `offline_persistence` | `max(consecutive_inactive − 1, 0)` (only when currently Inactive) | 4.0 · 20 |
| `idle_recurrence` | `max(consecutive_idle_active − 1, 0)` (Active + 0 cartons while the line is busy, run after run) | 6.0 · 40 |

`offline_persistence` caps a sustained-Inactive station at the **watch** ceiling (it may be
intentionally unstaffed). `idle_recurrence` lets a station that is **Active** while the line is busy
but decants **nothing** run-after-run escalate to **warn** (a real "station down / scanner-blind"
anomaly). Low throughput on its own is **never** penalized (it may just be low load) — only
`idle_while_active` persistence is. **There is no live discrepancy feed, so a decant station cannot
reach `critical`** — the ceiling is honest given the available data.

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`.

**Time-to-maintenance + regime:** no cycle counter, so RUL is time/recurrence-based —
**cold-start** uses a coarse band by tier (critical 48 h, warn 240 h, watch 720 h); **trend**
(≥ 5 runs) fits the component's `health_score` trajectory over time and projects when it crosses
the critical line (capped at 1 year). Scanner cold-start confidence rises with scan volume; station
cold-start confidence is deliberately lower (base 0.30) and rises with throughput disclosure +
accumulated persistence evidence + history.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by points removed; `primary_cause` names the dominant symptom, e.g.
*"High no-read rate: 4.0% (20/494) — compaction-line scanner failing/dirty/mis-aimed"*, *"Reading
cleanly (0.03% misread over 21,417 scans) — decant infeed diverter (aisle_02)"*, *"Idle while
Active across N consecutive runs (line busy, 0 cartons) — station down / scanner-blind suspect"*,
*"Inactive across N consecutive runs — station down (verify if intentional)"*, or the healthy state
*"Nominal — 749 cartons decanted (374/day)"*.

**Cross-module / cross-entity flags:** every scanner records a `gtp_station` provenance note (it was
reconciled from the GTP feed in Session 8 — now owned here); the station RCA states plainly that no
live per-station discrepancy feed exists (so the verdict is coarse); and a **line-level
corroboration** note is added to both entity types when the decant scanners **and** the decant
stations are **both** flagged in the same run (a decant-line issue, since there is no per-device
station mapping).

## 5. How the overall module status is reached

The **Decanting Station + Scanner PdM** tile shows the **worst risk tier among all components**
(scanners + stations; `critical > warn > watch > ok`), the per-tier counts, and the last-run time;
the per-component table (sorted worst-first) shows the full picture. Identical rollup for every
module (`core/registry.py`).

## 6. Validation (this session)

Two `now-2d` runs on **live data** scored **19 components (9 decant/compaction scanners + 10
stations)** each (289 rows fetched, ~13–14 s/run):

- **Scanner misread, live:** the 7 decant infeed diverters read cleanly — `aisle_04_decant_diverter`
  0.008%, `aisle_03` 0.012%, `aisle_02` 0.028% … `aisle_01_decant_diverter_2` 0.167% (12k–21k scans
  each) → all **ok**. Both compaction scanners are elevated — `Compaction_scanner` **4.0%** (20/498),
  `Compaction_scanner_2` **3.8%** (1,492/38,498 scans) → **watch** (misread ≈ 12 + peer-z capped 16).
- **Station, live:** 10 stations `DS001`–`DS010`, **9 Active / 1 Inactive** (`DS009`); throughput
  `DS003`=749 … `DS010`=116 cartons; `DS001`/`DS002` were **Active but idle** (0 cartons while the
  line was busy) → `idle_while_active` surfaced in the RCA (not yet penalized). All stations **ok**
  at cold-start (honest — no live fault feed), at modest confidence (0.52–0.62).
- **Cross-run recurrence, live:** run 2 saw both compaction scanners carry `recurrence_runs = 1`
  (+6-point penalty), dropping health (`Compaction_scanner` 72.0→66.0, `Compaction_scanner_2`
  72.5→66.5), and the persistent idle/Inactive stations begin accruing (`DS001`/`DS002` idle → 94,
  `DS009` Inactive → 96) — the store-driven longitudinal signal activating on real data.
- **Offline logic checks** proved: sustained `idle_while_active` (Active + line busy + 0 cartons
  across 9 runs) → **warn**; sustained Inactive (9 runs) → **watch** ceiling; a declining-health
  scanner across ≥5 runs → **trend** regime with a projected RUL; and the line-level corroboration
  flag when a scanner and a station are both flagged.
- **Reconciliation, verified:** the GTP module no longer scores any of the 9 decant/compaction
  devices (its scanner universe drops from 272 to 263); each device is owned by exactly one module.

See `/module/decant_station` (with its in-page Methodology section), `scripts/inspect_decant.py`, and
`scripts/analyze_decant_primary.py`.

## 7. Running it

- Dashboard: `/module/decant_station` → pick a window → **Run decant_station now**.
- API: `POST /api/run {"module":"decant_station","window":"now-2d"}`.
- Automation: enable the `decant_station` (or `global`) scope on the Automation page. The misread
  rate is windowed, so a single run is already meaningful for scanners; **regular automation** is
  what turns the station offline/idle-persistence, scanner recurrence, and trend RUL predictive.
- Discovery/inspection: `.venv/bin/python scripts/inspect_decant.py discover | meta | sample`;
  distribution analysis: `.venv/bin/python scripts/analyze_decant_primary.py --window now-2d`.

## 8. Future enrichment

- **A live station-keyed discrepancy feed** is the missing piece. `discrepancy_details` has the
  signal (`discrepancy_type` per carton/serial) but no station column and is frozen at 2022; a
  join `discrepancy_details.carton_id → grn_pick_list.station_id` over a live window would give a
  per-station discrepancy rate that would slot in as the station **primary** (mirroring the
  `gtp_station` discrepancy model exactly, including peer-z + SHORT mix).
- **Decant diverter throughput normalisation** — normalising misread by live decant throughput
  (once a per-diverter hit-rate timeseries is fetchable) would sharpen the scanner signal.
- As automation accumulates runs, the **trend** RUL, scanner recurrence, and station
  offline/idle-persistence penalties sharpen automatically — no code change.
