# GTP Station + Scanner module — the GTP Station + Scanner PdM chapter

Predictive maintenance for the **GTP** (goods-to-person) pick area: the **barcode scanners**
that read totes/containers and the **pick stations** where operators fulfil orders. This is
the first module that scores **two physical component types** in one plugin, because the
mapped signal is dual — *"scanner misread-rate trend + station downtime pattern → scanner/
station hardware failure"* — and both signals are strongly present in live data:

- **`gtp_scanner`** — a barcode scan device. **263 devices** (272 in the feed minus the 9
  decant/compaction devices now owned by Module 8 — see below): pick-station slot scanners
  (`GS<NN>-SL<NN>`), inbound scanners (`aisle_<NN>_inbound_scanner_<NN>`), GTP/zone scanners, and
  diverters. **Signal = misread rate** = `NoReadCount / (ReadCount + NoReadCount)`. A healthy
  scanner reads nearly every barcode (fleet median **0.3%** misread); a dirty/failing/mis-aimed
  scanner's no-read rate climbs.

  > **Session 8:** the 7 `aisle_<NN>_decant_diverter` + 2 `Compaction_scanner*` devices (subtypes
  > `decant`/`compaction`) are now **excluded** here and **owned by the Decanting Station + Scanner
  > module (Module 8)** — each device is owned by exactly one module (CLAUDE.md §7). The exclusion is
  > `module.yaml → scanner.exclude_subtypes`; GTP Scanner logs `#8` is a **shared** panel.
- **`gtp_station`** — a GTP pick station. **63 stations** (`GS001`–`GS063`). **Signal =
  per-station pick-verification discrepancy rate** (verification_events) + peer deviation +
  cross-run recurrence/trend. `active_status` (Active/Inactive) is **context**, plus a
  low-weight offline-persistence signal from the store.

The pick-station scanner **is** the `GS<NN>-SL<NN>` device, so a station's discrepancy climb
and its slot-scanner's misread climb **corroborate** each other — the RCA cross-links them.

This chapter documents the resolved sources, every feature/formula, and — per the project
requirement — **exactly how each component's verdict and the module's overall status are
reached**. Tunables live in [`module.yaml`](module.yaml); the pipeline is
`fetch.py → features.py → health.py` (which calls `rca.py`); it self-registers in
`__init__.py`. The data is **live/current** (not frozen).

> **Mapping corrections (Session 7).** The mapping (§7) listed five candidate sources and
> called two of them station uptime/throughput. Re-verifying every candidate by **live SQL +
> sampling** showed:
> - **GTP Station Information** (`j-fIgfqnk`) `#2` is per-station `remaining_quantity /
>   remaining_lines / remaining_skus / occupancy` — **pendency/inventory, not health**. Dropped.
> - **Live GTP Summary** (`j_cdWK_7z`) is station pendency / wave / outbound / current-inventory
>   panels — **operational state, not health**. Dropped.
> - The real scanner-misread signal is **GTP Scanner logs `#8`** (a per-scanner Read/NoRead
>   table the mapping never singled out), and a **`scanner_events`** dashboard the mapping never
>   listed backs it.
> - **Discrepancy Report Events** (`D6sQle2Vz`) — reassigned here from Conveyor in Session 3 —
>   is confirmed as `verification_events` keyed by **station**, the station primary. Its `.env`
>   key moved `CONVEYOR__ → GTP_STATION__`.

---

## 1. Data sources (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary (scanner)** | GTP Scanner logs (`pK7-8NmVz`) | `#8` "Scanner Read /No read Data" | `scanner, ReadCount, NoReadCount, efficiency_percentage` | Per-scanner misread rate + the **scanner universe** (263 devices, after excluding the 9 decant/compaction devices owned by Module 8). |
| Secondary (scanner volume) | GTP Scanner logs | `#4` "Scanner Hits" | `scanner, hits` | Per-scanner usage/volume proxy (best-effort). |
| **Primary (station)** | Discrepancy Report Events (`D6sQle2Vz`) | `#2` "Discrepancy Report Events" | `station, operation_type, user, container, type, discrepancy_type, create_time` | Per-station pick-verification discrepancies over the window. |
| **Primary (station roster)** | GTP Stations (`GlGBwgY4z`) | `#2` "Station Summary" | `id, Type, operation_type, active_status, updated_on` | The **63-station universe** + Active/Inactive status + recency. |

**Windowing (important).** Unlike the current-state Gate/Bin panels, GTP Scanner logs `#8`
and Discrepancy Report Events `#2` are **time-filtered** (`create_time BETWEEN $__timeFrom ..
$__timeTo`), so a **wider `from=now-<window>` sharpens** the misread/discrepancy rates. GTP
Stations `#2` is a current roster snapshot (63 rows regardless of window). The default window
is `now-2d`.

**Non-signal / deferred panels (documented, not fetched):** GTP Scanner logs `#2` "GTP Time
wise scanner logs" (raw `scanner_events` with `decision`/`decision_reason`; heavy, no
Download-CSV — `#8` already aggregates it), `#6` "Tote Hits" (per-container), `#10` container
location, `#12` "Latest Hit Inbounds" (29 inbound scanners only). GTP Stations `#6` "Time
Elapsed For Tote Inside Station" (a **gauge**, no CSV) is the **future true-downtime signal**;
`#8` "Marry_time" (gauge). **GTP Throughput v2** (`ZR7Z2FR4z`) per-scanner/station hit-rate
timeseries is a documented **future secondary** (per-run trend already accrues in our store).

## 2. Features (`features.py`)

**Scanner** (`component_type=gtp_scanner`), per device from `#8` (+ `#4` joined by scanner):

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `read_count` / `no_read_count` / `total_scans` | summed per scanner (`total = read + noread`) | Scan volume in the window. |
| `misread_rate` / `misread_pct` | `no_read / total` (0 if no scans) | **The core scanner signal.** |
| `efficiency_percentage` | as reported by the panel | Cross-check (= `100·read/total`). |
| `subtype` | parsed from the name | `station_scanner` (`GS<NN>-SL<NN>`), `inbound_scanner`, `gtp_scanner`, `zone_scanner`, `diverter`, `decant`, `compaction`, `other`. |
| `parent_station` | `GS<NN>` from `GS<NN>-SL<NN>` | Links a slot scanner to its pick station. |
| `hits` | from `#4` | Independent usage proxy. |
| `misread_peer_z` | *(within-snapshot)* robust z of `misread_pct` vs scanners with ≥ `min_volume_peer` scans | Peer deviation (MAD, std fallback). |

**Station** (`component_type=gtp_station`), per station from roster `#2` (+ discrepancy `#2`):

| Feature | Formula / definition | Meaning |
|---------|----------------------|---------|
| `active_status` / `is_active` | from the roster | Active/Inactive (context). |
| `operation_type` / `station_type` | from the roster | PICKING / SUPERVISOR_STOCK_CHECK / COMPACTION; FR01/BULK/JIT/… |
| `discrepancy_count` | events for this station in the window | Raw pick-verification discrepancies. |
| `short_count` / `discrepancy_type_mix` | count where `discrepancy_type=SHORT`; full mix | SHORT = short-pick outcome; ALRIGHT = verified-clean. |
| `discrepancy_per_day` | `discrepancy_count / window_days` | Window-normalised rate (window parsed from `now-Nd/Nh/Nw`). |
| `discrepancy_peer_z` | *(within-snapshot)* robust z of `discrepancy_per_day` vs stations that verified (count > 0) | Peer deviation — the dominant station signal. |
| `recurrence_runs` | *(health.py)* prior runs whose **discrepancies** were elevated (`peer_z ≥ recur_peer_z` **or** `per_day > floor`) | Cross-run recurrence — **discrepancy-specific**, so offline-only runs never count. |
| `consecutive_inactive` | *(health.py)* consecutive most-recent runs Inactive incl. now | Offline persistence (downtime). |

## 3. How a single component's verdict is reached (`health.py`)

`health = clamp(100 − Σ penaltyᵢ, 0, 100)`, `penaltyᵢ = min(valueᵢ·weightᵢ, capᵢ)`. Two
penalty models, one per entity type:

**Scanner** — weight · cap:

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `misread` | `misread_pct`, **scaled by `volume_factor = min(1, total/min_volume_full)`** | 3.0 · 75 |
| `peer_z` | `misread_peer_z` — **gated**: only when `total_scans ≥ min_volume_peer` **and** `misread_pct ≥ peer_z_min_misread_pct` | 4.0 · 16 |
| `recurrence` | prior runs whose **misread%** was ≥ `recur_min_misread_pct` (misread-specific) | 6.0 · 30 |

The **volume gate** is the key calibration: a scanner with few scans has a noisy rate, so its
misread penalty is scaled down, its **peer-z penalty is suppressed entirely**, and its confidence
lowered (e.g. `GS029-SL01` at 21% on only 52 scans → **watch**, conf 0.50, not critical), while a
high-volume 25–53% scanner → **critical**. Peer-z and recurrence are made **signal-specific** (a
minimum absolute misread) so a scanner reading cleanly but sitting slightly above a very tight
fleet median is not flagged, and recurrence never self-reinforces a peer-z-only flag.

**Station** — weight · cap:

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `discrepancy_peer_z` | `discrepancy_peer_z` vs peer stations | 6.0 · 40 |
| `discrepancy_abs` | `discrepancy_per_day − floor` (very-high absolute rate) | 1.5 · 20 |
| `recurrence` | prior runs whose **discrepancies** were elevated (peer-z ≥ `recur_peer_z` or per-day > floor) — **discrepancy-specific** | 6.0 · 30 |
| `offline_persistence` | `max(consecutive_inactive − 1, 0)` (only when currently Inactive) | 4.0 · 20 |

Recurrence is keyed on the **discrepancy** signal (not aggregate health), which is what
guarantees the `offline_persistence` cap holds: a legitimately-Inactive station drops to the
WATCH ceiling and **stays** there run after run — it never accrues a discrepancy recurrence, so it
cannot be escalated into warn/critical by pure downtime.

Absolute discrepancy counts are partly **inventory-driven** (plant-wide SHORTs), so the station
model leans on **peer deviation + recurrence** to isolate station-specific degradation; the
absolute term only bites at a very high rate. `active_status` is **context** — a single Inactive
run adds nothing (many stations are legitimately Inactive); only **sustained** Inactivity across
consecutive runs adds a capped penalty that reaches **watch** and no worse (it may be intentional).

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`.

**Time-to-maintenance + regime:** no cycle counter, so RUL is time/recurrence-based —
**cold-start** uses a coarse band by tier (critical 48 h, warn 240 h, watch 720 h); **trend**
(≥ 5 runs) fits the component's `health_score` trajectory over time and projects when it crosses
the critical line (capped at 1 year). Scanner cold-start confidence rises with scan volume;
station cold-start confidence with discrepancy evidence + history; trend confidence with history depth.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by points removed; `primary_cause` names the dominant symptom, e.g.
*"High no-read rate: 53.3% (345/647) — scanner failing/dirty/mis-aimed"*, *"Elevated pick
discrepancies: 65 (32.5/day, +4.9σ vs peers) — scanner/PTL/pick mechanism suspect"*, *"Inactive
across N consecutive runs — station down (verify if intentional)"*, or the healthy states
*"Reading cleanly (0.0% misread over 3,769 scans)"* / *"Nominal — 5 pick discrepancies"*.

**Cross-module / cross-entity flags:** `decant_*` / `Compaction_*` scan devices are **no longer
scored here** — they are excluded and owned by the **Decanting Station module (Module 8)** as of
Session 8 (each device owned by exactly one module); a flagged station points at its slot scanner
and vice-versa; and a **corroboration** flag is added when a station AND its `GS<NN>-SL<NN>` scanner
are **both** flagged — the same physical hardware cause.

## 5. How the overall module status is reached

The **GTP Station + Scanner PdM** tile shows the **worst risk tier among all components**
(scanners + stations; `critical > warn > watch > ok`), the per-tier counts, and the last-run
time; the per-component table (sorted worst-first) shows the full picture. Identical rollup for
every module (`core/registry.py`).

## 6. Validation (this session)

Two `now-2d` runs on **live data** scored **326 components (263 scanners + 63 stations)** each
— the scanner universe is 272 in the feed minus the 9 decant/compaction devices now owned by
Module 8 (see §1) — (1,756 rows fetched, ~33–37 s/run):

- **Scanner misread, live:** the worst scanners are pick-station slot scanners — `GS030-SL02`
  = **53.3%** misread, `GS015-SL02` 51.1%, `GS055-SL01` 46.4%, `GS054-SL03` 28.8%, `GS008-SL01`
  25.6% — plus a **dead** `aisle_03_gtp_diverter` (**100%** no-read, 3,373 scans) → all **critical**.
  Run 1 (263 scanners after the decant/compaction exclusion): 14 critical / 15 warn / 41 watch / 193 ok.
- **Station discrepancy, live:** `GS037` = 65 discrepancies (**+4.9σ** vs peers) → **warn**;
  `GS054`/`GS039`/`GS053`/`GS011`/`GS016`/`GS056` → **watch**; the other 56 stations **ok**.
- **Cross-signal corroboration, live:** `GS054` and `GS056` are flagged as **both** a
  high-discrepancy station **and** a critical-misread slot scanner (`GS054-SL03` 28.8%,
  `GS056-SL01` 22.7%) — the RCA cross-links them.
- **Volume gating, live:** low-volume noisy scanners land at watch with **lower confidence**,
  not critical (honest).
- **Cross-run recurrence, live:** run 2 saw every run-1 offender carry `recurrence_runs = 1`
  (+6-point penalty), dropping health further (`GS037` 51.6→45.6, `GS054` 68.7→62.7, `GS056`
  81.5→75.5) — the store-driven longitudinal signal activating on real data.
- **Offline-persistence + trend** were proven with an offline logic check (a declining-health
  scanner entered the **trend** regime with a ~7 h projected RUL; a station Inactive across 5
  consecutive runs reached **watch**).

See `/module/gtp_station` (with its in-page Methodology section), `scripts/inspect_gtp.py`, and
`scripts/analyze_gtp_primary.py`.

## 7. Running it

- Dashboard: `/module/gtp_station` → pick a window → **Run gtp_station now**.
- API: `POST /api/run {"module":"gtp_station","window":"now-2d"}`.
- Automation: enable the `gtp_station` (or `global`) scope on the Automation page. The misread
  and discrepancy rates are windowed, so a single run is already meaningful; **regular
  automation** is what turns recurrence, offline-persistence, and trend RUL predictive.
- Discovery/inspection: `.venv/bin/python scripts/inspect_gtp.py discover | meta | sample`;
  distribution analysis: `.venv/bin/python scripts/analyze_gtp_primary.py --window now-2d`.

## 8. Future enrichment

- **GTP Stations `#6`** (minutes a tote has sat inside a station) is the true station-stall/
  downtime signal — it is a gauge with no CSV today; exposing it as a table would add a
  server-side latency signal like Gate's stuck-minutes.
- **GTP Throughput v2** (`ZR7Z2FR4z`) per-scanner hit-rate + per-station line-rate timeseries
  would give a within-fetch trend and let misreads be normalised by live throughput.
- **`decision_reason`** from `scanner_events` (why a no-read happened) would sharpen scanner RCA
  once the raw feed is fetchable.
- **Module 8 (Decanting Station + Scanner)** was built in Session 8 and now **owns** the `decant_*`
  + `Compaction_*` scan devices (excluded here via `scanner.exclude_subtypes`) — done.
- As automation accumulates runs, the **trend** RUL and recurrence penalties sharpen
  automatically — no code change.
