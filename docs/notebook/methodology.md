# PdM Methodology — how health is inferred without a logbook

> This chapter is **module-agnostic**: it defines the scoring philosophy every
> module follows so predictions stay consistent across equipment types. Each
> module chapter then specifies its own signals, features, formulas, and thresholds.

## 1. The core constraint: no maintenance logbook

There is **no record of when anything was serviced or replaced.** The model
therefore cannot be trained against labelled failures. It must decide
"maintenance needed / not needed", *when*, and *why* **purely from operational and
error data** exposed by Grafana. This is unsupervised, signal-driven condition
monitoring — not supervised failure-time regression.

Consequence: we never depend on labels. Operators *may* optionally acknowledge a
service (§7), but that only annotates/silences a flag and resets a baseline; it
never trains or drives detection.

## 2. Per-component scoring

The atomic unit is a **single physical component** (for Lift, one lift, e.g.
`aisle_04_inbound_lift_02`). Every PdM run produces, per component:

| Field | Meaning |
|-------|---------|
| `health_score` | 0–100; 100 = healthy, 0 = failed/critical. |
| `risk_tier` | `ok` ≥85, `watch` 65–85, `warn` 40–65, `critical` <40 (default thresholds; a module may override). |
| `predicted_ttm_hours` | Estimated time-to-maintenance in hours (nullable when not estimable). |
| `confidence` | 0–1; how much to trust the prediction given data availability + regime. |
| `prediction_regime` | `coldstart` or `trend` (§5). |
| `primary_cause` + `rca` | The dominant contributing signal(s) (see each module's `rca.py`). |
| `metrics` | The raw + derived features behind the score (stored for trend + audit). |

### Health score shape

Health is a **penalty model**: start at 100 and subtract weighted penalties for
each unhealthy signal, each penalty bounded so no single signal dominates
pathologically:

```
health = 100 − Σ wᵢ · penaltyᵢ        (penaltyᵢ ∈ [0, capᵢ])
```

Penalties are built from **normalised, dimensionless** signals so components and
modules are comparable: rates per hour, ratios, z-scores against the component's
own baseline, and deviation from peer components. Raw counts are never used
directly (a busy lift would always look "worse" than an idle one).

## 3. Designing signals for a ~2-day window

Most Grafana dashboards retain about **two days** of data. Signals are therefore
designed to be meaningful on a short window:

- **Rates, not counts** — errors per active hour, faults per 100 cycles.
- **Error-code mix** — diversity/severity of error codes, not just totals.
- **Recurrence** — the same component faulting repeatedly (a degradation
  fingerprint, distinct from random one-offs).
- **Time-between-faults (MTBF proxy)** — shrinking gaps signal accelerating wear.
- **Self-baseline deviation** — how far a component sits from *its own* recent norm.
- **Peer deviation** — how far it sits from comparable peers (e.g. inbound vs
  outbound lift on the same aisle, or all lifts system-wide).

## 4. The store overcomes the 2-day limit

Every PdM trigger **snapshots each component's metrics** into the longitudinal
store (`component_health`). Over successive runs this accumulates a history far
longer than any single 2-day fetch. The 2-day window is just the *observation
window per run*; the *memory* of the system is unbounded and grows with every run.

This is the mechanism that turns a short-retention dashboard into a long-horizon
predictive dataset — and it is also why running PdM regularly (via automation)
materially improves predictions over time.

## 5. Two prediction regimes (always labelled)

- **`coldstart`** — little or no run history for a component. Predictions use only
  the current window: rate/anomaly tiering and peer comparison. TTM is coarse
  (tier-based bands) and **confidence is low**. This is honest about uncertainty
  rather than fabricating precision.
- **`trend`** — enough history exists. The model fits the component's health /
  error-rate trajectory over time (robust linear trend / slope) and projects when
  it will cross a maintenance threshold, giving a sharper `predicted_ttm_hours` and
  **higher confidence**. The regime is recorded on every prediction so consumers
  know which one produced it.

The transition is gradual: confidence scales with the number of historical
snapshots and the stability of the trend.

## 6. Scalable window

Nothing is hard-coded to two days. If a longer-retention source is available (or
the OPC/historian tables go back further), the same pipeline ingests a larger
`from=now-<window>` and produces sharper predictions immediately. The window is a
parameter, surfaced in the dashboard's Grafana-style duration control.

## 7. Optional operator acknowledgement

When maintenance is performed, an operator **may** mark a component as serviced
(`maintenance_ack`). This is entirely optional and imposes no record-keeping
burden. Its only effects:

1. **Annotate / silence** the current flag for that component.
2. **Reset the baseline** so post-service behaviour is judged against a fresh norm
   rather than the pre-failure history.

It never labels training data and never drives detection.

## 8. Confidence

Confidence combines: data sufficiency (rows fetched, active hours observed),
history depth (number of prior snapshots), regime (`trend` > `coldstart`), and
signal agreement (do independent signals point the same way?). It is reported so a
maintainer can triage: a `critical` tier at 0.9 confidence is actionable now; the
same tier at 0.3 confidence means "watch and let history accumulate."

## 9. Scalability and consistency

- Scoring helpers (tiers, normalisation) live in `core/registry.py` so all modules
  share one methodology.
- Adding a module never edits `core/`; it only adds signals and a scoring function.
- All features are stored (`metrics_json`) so future AI/ML — regression RUL,
  anomaly models, embeddings, cross-module compound-failure detection — can be
  layered on the accumulated history without re-fetching.
