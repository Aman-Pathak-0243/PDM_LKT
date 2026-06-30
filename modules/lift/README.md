# LIFT module — the Lift PdM chapter

Predictive maintenance for the ASRS **lifts** (rotating, load-bearing assets; two
per aisle face, see `docs/notebook/01_intro_to_asrs.md` §1.4). Health is inferred
purely from per-lift error data plus current-status and load context — no
maintenance logbook.

This chapter documents the resolved data sources, every feature and its formula,
the health/TTM/confidence model, and the RCA. Tunables live in
[`module.yaml`](module.yaml); the pipeline is `fetch.py → features.py → health.py`
(which calls `rca.py`). The module self-registers in `__init__.py`.

---

## 1. Data sources (resolved by live inspection)

| Role | Dashboard | Panel | Fields used | Use |
|------|-----------|-------|-------------|-----|
| **Primary** | Lift Error History (`wQds52G4z`) | `#2` table | `lift_id, error_code, error_desc, created_time, updated_timestamp` | Per-lift fault events — rate, severity, recurrence, code mix, inter-fault timing. |
| Secondary | Bad Tracker Diagnosis (`VAW2nmqIz`) | `#2` table | `lift_id, lift Status Description, created_time` | Lift recurrence in bad-tracker rows + **current ERROR status**. |
| Secondary | Lift Error Analysis (`EqDhnQ9Sz`) | `#2` table | `Aisle, {Front/Back}{Inbound/Outbound} Lift` | Per-lift cumulative task counts (relative **load** context). |

**Component universe:** 16 lifts, id format `aisle_<NN>_<inbound|outbound>_lift_<NN>`.
The primary panel returns full history regardless of the dashboard window; the
window is applied in-code, anchored to `as_of = max(created_time)` so the model
behaves identically on live and historical/frozen data.

Observed error-code semantics (drives severity + RCA) — see `module.yaml`
`error_catalog`: e.g. code 14 *Lift Motor exceeded software limit* (drive_motor,
sev 0.9), code 5 *brake tear / belt slipped* (mechanical_wear, sev 1.0), codes
10/11 *roller faulty* (mechanical_wear, 0.8), code 1 *axis error* (0.85), code 4
*Ethernet communication error* (communication, 0.5 — also a cross-feature to the
future Network module).

## 2. Features (`features.py`)

Computed per lift over the window `[as_of − window, as_of]`. Let `n` = error count
in window, `D` = window length in days.

| Feature | Formula / definition | What it tells you |
|---------|----------------------|-------------------|
| `error_count` | `n` | Raw fault volume in window. |
| `error_rate_per_day` | `n / D` | Fault intensity (window-normalised). |
| `share_of_total` | `n / Σ n_all_lifts` | This lift's share of all lift errors. |
| `distinct_codes` | unique error codes | Breadth of fault types (systemic vs single). |
| `severity_mean` | `mean(severity(code))` over the window | Average fault seriousness (0–1). |
| `mechanical_count` / `mechanical_share` | count / fraction in mechanical-wear categories | Physical-degradation fingerprint (most predictive). |
| `recurrence_max` | max repeats of any single code | Same fault recurring (degradation, not random). |
| `median_gap_hours` / `min_gap_hours` | median / min of consecutive inter-fault gaps | MTBF proxy; shrinking gaps = accelerating wear. |
| `last_error_age_hours` | `as_of − last error time` | Recency of the most recent fault. |
| `load_tasks` | per-lift task count (Lift Error Analysis) | Relative load/stress context. |
| `bad_tracker_events` | bad-tracker rows referencing this lift | Independent recurrence signal. |
| `current_error_status` | any bad-tracker row with this lift in `ERROR` | Live fault state. |
| `peer_median_rate` | median `error_rate_per_day` across all lifts | Peer baseline. |
| `rate_peer_z` | robust z: `(rate − median) / (1.4826·MAD)` | How far above peers this lift sits (degenerate-spread safe). |

## 3. Health model (`health.py`)

Penalty model: `health = clamp(100 − Σ penaltyᵢ, 0, 100)`. Each penalty is
`min(value · weight, cap)` with weights/caps from `module.yaml`:

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `rate_peer_z` | peer-relative rate (robust z) | 9.0 · 40 |
| `abs_rate` | absolute error/day | 2.0 · 20 |
| `severity` | mean severity | 30.0 · 30 |
| `mechanical` | mechanical-wear share | 22.0 · 22 |
| `recurrence` | `max(recurrence_max − 2, 0)` | 1.5 · 18 |
| `diversity` | `max(distinct_codes − 2, 0)` | 2.0 · 12 |
| `current_error` | currently in ERROR | 12.0 · 12 |

**Risk tier** (from score): `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40`.

**Time-to-maintenance + regime:**
- **`coldstart`** (run history `< 5` snapshots): coarse band by tier — critical→24 h,
  warn→96 h, watch→336 h, ok→none. Confidence `0.35 + 0.35·data_factor (+0.1 if any history)`,
  where `data_factor = min(1, n/30)`.
- **`trend`** (≥5 snapshots): fit a line to the lift's historical `health_score` vs
  time (hours). If declining and above the critical line (40), project
  `ttm = (score − 40) / |slope|` (capped at 1 year). Confidence
  `≈ trend_base(0.7) + 0.2·history_depth_factor`, scaled by data sufficiency.

The penalty breakdown is stored in `metrics_json.penalties` for transparency.

## 4. Root-cause attribution (`rca.py`)

For each lift, contributors are ranked by the points each penalty removed from
health. `primary_cause` is a one-line summary (current ERROR > dominant
mechanical/severe error > peer-relative rate > dominant error). The RCA payload
also carries the dominant error (code/desc/category/severity/count), the top-6
error mix, mechanical share, share-of-total, and **cross-module flags** — e.g. when
≥20 % of window errors are communication-class, it flags the future Network module.

## 5. Validation (this session)

A run over `now-365d` (full history) ranked `aisle_04_inbound_lift_02` worst
(health 0, **50 % of all lift errors**, code 14 motor, mechanical share 1.0,
currently ERROR). Tiers distributed sensibly across the 16 lifts; cold-start regime
labelled correctly with confidence scaling by data sufficiency. See the per-module
dashboard at `/module/lift`.

## 6. Running it

- Dashboard: open `/module/lift`, pick a window, click **Run lift now**.
- API: `POST /api/run {"module":"lift","window":"now-30d"}`.
- Automation: enable the `lift` (or `global`) scope on the Automation page.

## 7. Future enrichment (documented candidates)

OPC - Lift Datalogger (raw per-lift telemetry), Process - Lift (cycle-time /
throughput / idle per lift), and Lift_Supply_Tote (load) are high-value sources
that need template-variable handling (date/shift) or time handling before they
yield CSV. Adding them means extending `fetch.py` + `features.py` and updating this
chapter — no `core/` changes.
