# CONVEYOR module — the Conveyor PdM chapter

Predictive maintenance for the **GTP conveyor zones** (belts, motors, diverters that
move totes between the ASRS and the goods-to-person stations). Unlike Lift (time) and
Shuttle (cycles), the conveyor exposes a **per-zone queue-vs-limit** signal, so health
is a **congestion model**: a healthy belt clears totes; a worn/jamming belt lets the
queue build above its limit, spike, and back up into its buffer.

This chapter documents the resolved sources, every feature/formula, and **how each
zone's verdict and the module's overall status are reached**. Tunables in
[`module.yaml`](module.yaml); pipeline `fetch.py → features.py → health.py` (calls
`rca.py`); self-registers in `__init__.py`. The data is **live/current** (not frozen).

> **Mapping correction.** The mapping listed *Discrepancy Report Events* as
> "jam/misroute per zone". Live inspection shows it is **GTP-station pick verification**
> (`verification_events`: `station, operation_type, type, discrepancy_type` — values like
> `EMPTY_SUPPLY_CONTAINER_CONFIRM`/`SHORT`), 17.8k current rows keyed by **station**, not
> zone. It is **reassigned to the GTP Station + Scanner module (Module 7)** — now **built
> (Session 7)**, which owns it as its per-station primary (the `.env` key moved
> `CONVEYOR__ → GTP_STATION__`). Grafana has no discrete conveyor jam-event feed, so conveyor
> health uses congestion (the symptom).

---

## 1. Data sources (resolved by live inspection)

| Role | Dashboard | Panels | Fields used | Use |
|------|-----------|--------|-------------|-----|
| **Primary** | Conveyor Zone Count (`lavIciTDk`) | `#6/#8/#10/#12/#14/#16` (Zone 1–6) | `time, Conveyor Actual, Conveyor Limit, Buffer Actual, Buffer Limit` | Per-zone congestion over time. |
| Context | Conveyor Zone Count | `#4` snapshot | latest Actual/Limit per zone | Best-effort current snapshot. |
| Secondary | GTP (HOLD, TRANSIT) (`C8jMvAcIk`) | `#2/#4` | order/tray flow state (`station_id`) | Module-level flow-stress **counts** (not per-zone). |

**Component universe:** 6 zones (`zone_1 … zone_6`), one per `Conveyor Zone Count` panel.
Notably **all zones run above their soft limit** (≈1.0–1.5×), so absolute saturation is
not discriminating — the model leans on excess-above-1.0, severe-saturation share, peaks,
buffer fill, and peer deviation.

## 2. Features (`features.py`)

Per zone over the window, from the queue timeseries. `congestion = conveyor_actual / conveyor_limit`.

| Feature | Formula | Meaning |
|---------|---------|---------|
| `congestion_mean` | mean(actual/limit) | How full the zone runs on average. |
| `congestion_peak` | max(actual/limit) | Worst backup spike. |
| `congestion_p90` | p90(actual/limit) | Sustained high congestion. |
| `severe_saturation_share` | share of samples with congestion ≥ `severe_ratio` (1.5) | Time spent severely backed up. |
| `buffer_congestion_mean` | mean(buffer_actual/buffer_limit) | Downstream backup (buffer filling). |
| `throughput_mean` | mean(conveyor_actual) | Activity/load level. |
| `idle_share` | share of samples with actual = 0 | Possible stalls / quiet periods. |
| `congestion_peer_z` | robust z of `congestion_mean` vs the 6 zones | Peer deviation (MAD, std fallback). |
| `system_on_hold` / `system_in_transit` | counts from GTP HOLD/TRANSIT | Module flow-stress context. |

## 3. How a single zone's status is reached (`health.py`)

Penalty model: `health = clamp(100 − Σ penaltyᵢ, 0, 100)`, `penaltyᵢ = min(valueᵢ·weightᵢ, capᵢ)`.

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `congestion_excess` | `congestion_mean − 1.0` | 40 · 35 |
| `severe_saturation` | severe-saturation share | 30 · 25 |
| `peak_excess` | `congestion_peak − peak_ref(2.0)` | 15 · 15 |
| `buffer_congestion` | `buffer_congestion_mean − buffer_normal(0.30)` | 25 · 18 |
| `congestion_peer_z` | peer-relative congestion | 6 · 18 |

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`.

**Time-to-maintenance + regime:** no cycle counter and no discrete faults, so RUL is
time-based — **cold-start** uses a coarse band by tier (critical 24 h, warn 96 h, watch
336 h); **trend** (≥ 5 snapshots) projects the zone's health trajectory over time. Confidence
scales with the number of timeseries samples and history depth.

## 4. Root-cause attribution (`rca.py`)

Contributors are ranked by points removed; `primary_cause` describes the backup
("Queue runs 1.46× its limit", "Severely saturated 42% of the window", "Peak backup
2.7× limit", "Buffer filling …"), or "Flowing normally" when nothing is material.
Cross-module flag: sustained buffer fill → downstream/outbound module.

## 5. How the overall module status is reached

The **Conveyor PdM** tile shows the **worst risk tier among the 6 zones** (critical >
warn > watch > ok), the per-tier counts, and the last-run time; the per-zone table (sorted
worst-first) shows the full picture. Identical rollup for every module (`core/registry.py`).

## 6. Validation (this session)

A `now-24h` run on **live data** scored 6 zones: `zone_2` (1.46× limit, 42% severe
saturation) and `zone_6` (1.38×, peak 2.7×) → **warn**; `zone_1`/`zone_3` slightly elevated
but **ok**; `zone_4`/`zone_5` **ok / flowing normally**. Cold-start regime, confidence 0.85
(8k+ samples/zone). See `/module/conveyor` (with its in-page Methodology section).

## 7. Running it

- Dashboard: `/module/conveyor` → pick a window → **Run conveyor now**.
- API: `POST /api/run {"module":"conveyor","window":"now-24h"}`.
- Automation: enable the `conveyor` (or `global`) scope on the Automation page.

## 8. Future enrichment

If a discrete conveyor jam/diverter-fault feed becomes available it can be added as a
fault-rate signal (normalised by throughput) alongside congestion. The GTP HOLD/TRANSIT
counts could be mapped to zones if a zone/station map is provided, turning stuck-in-transit
into a per-zone signal. As automation accumulates runs, the **trend** RUL activates
automatically — no code change.


---

> **Audit hardening (Session 12 — 2026-07-01).** Added a **`stall_idle`** signal (peer-anomalous idleness) so a seized/dead zone — zero throughput, congestion 0 — is now flagged instead of scoring a perfect 100; a plant-wide quiet period yields no false stall. Wired the documented `congestion_p90` as a **`sustained_congestion`** penalty. Secondary HOLD/TRANSIT fetch now honours the run window; trend `polyfit` guarded. See `docs/AUDIT_REPORT.md` and `docs/notebook/methodology.md §12` for the cross-cutting invariants.
