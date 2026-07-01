# System-Wide Anomaly (Meta) module — the final PdM chapter

The **meta-module** — Module 11, the last in the build sequence. Unlike the ten equipment/infra
modules it has **no Grafana source**: it is a **correlation layer over the PdM store**. It reads the
latest scored component of every other module (and each one's `rca.cross_module_flags`) and correlates
them into **ranked compound-risk incidents**, surfacing compound failures with a **likely common cause**
— e.g. *"controller saturation → network downtime → shuttle errors → bin blocks on the same aisle"* — as
**one** incident instead of ten unrelated per-module flags. This is information no single module can see.

- **`incident_scope`** — a correlation scope. **6 ASRS aisles** (`aisle_01…06`, the observed
  `metrics_json.aisle` values) **+ 1 `system` scope** = 7 fixed components. An **aisle** scope groups the
  flagged components of every module that maps to that aisle (`lift`, `shuttle`, `tracker`, `gate`,
  `bin_mech`, `network`, + decant infeed diverters); the **system** scope groups the `controller` + the
  non-aisle areas (GTP, decant stations, conveyor) + a breadth-of-compound-aisles signal.

This chapter documents the correlation model, every feature/formula, and — per the project requirement —
**exactly how each incident's verdict and the module's overall status are reached**. Tunables live in
[`module.yaml`](module.yaml); the pipeline is `fetch.py (reads the store) → features.py (correlate) →
health.py (compound-risk, calls rca.py)`; it self-registers in `__init__.py` (with `is_configured()`
overridden to `True` since it has no dashboards). Registered **last**, so a "Run all" trigger has the
other modules persist their fresh rows **before** meta correlates them.

> **Design decisions (Session 11, confirmed with the operator).**
> - **No new fetch.** Every mapped §11 candidate (Aggregate Error Report, QUADRON ERROR HISTORY, Quadron
>   Alerts, Quadron Network status, CPU Stats) is **already owned** by another module (Network = Quadron
>   Network status, Controller = CPU Stats, Shuttle = QUADRON ERROR HISTORY, Gate/Shuttle = Quadron Alerts)
>   or was **dropped** as redundant (Aggregate Error Report = `shuttle_error ∪ lift_error`, covered by
>   Shuttle + Lift). Re-fetching them would double-count — so meta reads **only the store**.
> - **Meta components = 6 aisles + system** (fixed roster, always present so the tile is meaningful).
> - **Compound-risk, not a re-tally.** The score reflects module **co-occurrence + realized causal chains
>   + persistence**, not the sum of member health — so it never double-counts a module's own verdict.
> - **Surfaced on the generic `/module/meta` page** (ranked incidents + in-page Methodology) + an Overview
>   tile. No `core/` or `webapp/` changes (the plugin rule).

---

## 1. Data source — the PdM store (no Grafana)

| Role | Source | Reads | Use |
|------|--------|-------|-----|
| **Primary** | `component_health` (the store) | latest row per `(module, component_id)`, **excluding** `module='meta'` | Each other module's latest verdict (`risk_tier`, `health_score`, `primary_cause`, `rca.cross_module_flags`, `metrics.aisle`). |

`fetch.py` ignores the Playwright session and reads `get_storage().latest_per(...)`. The window is
nominal (meta reads the store, not a time-filtered feed). Regular "Run all" automation keeps the
correlated verdicts time-aligned (all modules refresh together, then meta correlates them).

## 2. Correlation features (`features.py`)

Each component maps to its scope via the **authoritative `metrics_json.aisle`** (set by the ASRS-aisle
modules + decant diverters); components without it → the `system` scope. Per scope:

| Feature | Definition | Meaning |
|---------|------------|---------|
| `breadth` | count of **distinct modules** with a flagged (tier ≠ ok) component in the scope | ≥ 2 = a compound incident (1 = that module's own problem). |
| `worst_flagged_tier` | worst tier among flagged members | Severity of the compound incident. |
| `chain_edges` / `chain_edge_count` | a flagged member whose `cross_module_flags` names a target module that is **also flagged in the same scope** (e.g. `network→shuttle`) | **Realized causal chain** — strong evidence of a common cause. |
| `has_meta_flag` | a flagged member carries an explicit `→meta` flag (controller / network cluster) | First-class meta signal. |
| `flagged_members` | the flagged components (module, id, tier, primary_cause), worst-first | The incident's contents (drill-down). |
| *(system)* `controller_tier` / `compound_aisle_count` | controller node tier; # aisles that are themselves compound | System trigger + systemic breadth. |

## 3. How a single incident's verdict is reached (`health.py`)

`health = clamp(100 − Σ penaltyᵢ, 0, 100)`. **Compound-risk, not a re-tally** (avoids double-counting):

| Penalty | Driven by | weight · cap |
|---------|-----------|--------------|
| `breadth` | `distinct_flagged_modules − 1` | 16 · 48 |
| `severity` | worst flagged tier — **only when `breadth ≥ 2`** (amplifies a compound incident; never manufactures one from a lone module) | critical 18 / warn 8 / watch 2 |
| `chain` | `chain_edge_count` (realized causal edges) | 8 · 24 |
| `persistence` | consecutive prior meta runs this scope was compound (`breadth ≥ 2`) | 6 · 24 |
| *(system)* `controller_trigger` | controller node tier (a saturated controller is a system incident on its own) | critical 30 / warn 15 / watch 5 |
| *(system)* `aisle_breadth` | count of simultaneously-compound aisles (systemic common cause) | 10 / aisle, cap 40 |

**The key anti-double-count rule:** an aisle with a **single** flagged module stays `ok` (that module
owns it); meta escalates only when **≥ 2 modules co-occur**, and hardest when a **realized causal chain**
links them. So the meta score is genuinely new cross-module information, not a re-flag of what the
individual modules already report.

**Risk tier** from score: `ok ≥ 85`, `watch 65–85`, `warn 40–65`, `critical < 40` — incidents ranked
worst-first. **RUL/regime:** cold-start uses a coarse band by tier (compound incidents escalate fast);
trend (≥ 5 runs) fits the scope's compound-risk trajectory over accumulated meta runs.

## 4. Root-cause attribution (`rca.py`)

`primary_cause` names the compound pattern, e.g. *"Compound incident on aisle_01: 5 subsystems degraded
(bin_mech, lift, network, shuttle, tracker; worst critical); realized chain network→shuttle, shuttle→network,
tracker→shuttle, tracker→lift, bin_mech→shuttle"*, *"System compound-risk: 6 aisle(s) in compound incident;
3 area subsystems degraded"*, or the healthy state *"aisle_05 nominal — no correlated cross-module
degradation"*. The RCA carries the **chain edges**, the **flagged members** (for the incident view), and a
**cross_module_flag per involved module** so an operator can drill straight into each source module's page.

## 5. How the overall module status is reached

The **System-Wide Anomaly (Meta) PdM** tile shows the **worst incident tier** across the 7 scopes
(`critical > warn > watch > ok`), the per-tier counts, and the last-run time — i.e. the single most urgent
compound incident in the plant. The per-component table (worst-first) is the **ranked incident list**.
Identical rollup mechanism as every other module (`core/registry.py`).

## 6. Validation (this session)

- **Offline logic:** a synthetic store proved the model — a compound aisle (network critical + shuttle
  warn, realized `network↔shuttle` chain) → critical; a **lone** flagged module on an aisle stays **ok**
  (no double-count); a 3-module aisle → breadth 3; the `system` scope fires on a saturated controller +
  counts compound aisles; and persistence (compound across ≥ 4 prior runs) lowers health further.
- **Live, on the real store:** meta correlated **771 components across all 10 modules in ~0.3 s** (no
  fetch) into **7 incidents** — all 6 aisles compound (aisle_01/03/04 = **5 subsystems each** with
  realized causal chains → critical; aisle_05 = 2 subsystems, no chain → **watch**), and a **`system`**
  incident (6 compound aisles + critical GTP scanners, realized `decant_station→gtp_station` chain). The
  incident view listed the exact flagged members (e.g. `GS030-SL02` 53.3% misread) for drill-down. Run 2
  showed the persistence penalty accruing.
- **No double-count, verified:** the compound-risk score is a function of co-occurrence + chains, never a
  sum of member health; a single-module scope is left to that module.

See `/module/meta` (with its in-page Methodology section). There is no `inspect_*`/`analyze_*` script —
meta has no Grafana source; its "inspection" is the store itself.

## 7. Running it

- Dashboard: `/module/meta` → **Run meta now** (correlates the latest stored verdicts).
- API: `POST /api/run {"module":"meta"}`.
- **Best run as part of "Run all"**: meta is registered last, so a Run-all trigger refreshes every module
  and then correlates the same-trigger verdicts. Enable the `global` automation scope so the whole system
  is re-scored and correlated on a schedule — that is what makes the persistence signal + trend RUL and
  the "is this compound incident sustained?" judgement meaningful.
- Note: running meta *solo* still opens a Grafana session (the shared runner path) though it makes no
  Grafana call; it only needs the store. It correlates whatever verdicts are currently latest.

## 8. Future enrichment

- **Window-aligned correlation** — correlate only components scored within the same trigger/window (rather
  than latest-per-component) for a strict point-in-time system snapshot; the current latest-per-component
  view is the right default for "current known system state".
- **Per-area scopes** — add explicit GTP / decant / conveyor area scopes (today folded into `system`).
- **Chain scoring by direction/lag** — weight `controller→network→shuttle→bin` chains by the known causal
  order and by cross-run lead/lag once enough history accrues, turning correlation into causation ranking.
- The module set is now **complete (11/11)** — the notebook compiles Chapter 1, Chapter 2, one chapter per
  module (Lift … Meta), then the data-volume chapter.
