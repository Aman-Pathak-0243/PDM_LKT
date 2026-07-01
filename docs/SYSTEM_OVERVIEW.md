# System Overview — what this is, what it tracks, and the value it adds

> **Audience:** anyone (management, ops, a new engineer) who wants the big picture in a
> few minutes: what the ASRS Predictive-Maintenance system is, how it's built, what it
> watches, and why it's worth running. Details live in the linked docs.

---

## 1. The problem it solves

The Lenskart fulfilment plant runs a **six-aisle ASRS** (Automated Storage & Retrieval
System) — lifts, shuttles, conveyors, gates, bins, scanners, decant stations, a comms
layer, and a controller. When a component degrades, the usual outcomes are a **surprise
breakdown** (unplanned downtime, throughput loss) or **over-servicing** (fixing things
that were fine).

Crucially, **there is no maintenance logbook** — no record of what was serviced or when.
So a classic "train a model on past failures" approach is impossible. What the plant *does*
have is rich **Grafana operational + error data**. This system turns that data into
**predictive maintenance**: it infers each component's health and warns *before* failure,
using only the operational/error signals already being collected.

---

## 2. What it does, in one sentence

**Every time it runs, it reads the plant's Grafana data, scores every physical component's
health (0–100), and tells you what is degrading, how urgent it is, how confident it is,
and why — so maintenance is scheduled proactively instead of reacting to breakdowns.**

Per component, each run produces:
- a **health score** (0–100) and a **risk tier** (`ok` / `watch` / `warn` / `critical`),
- a **predicted time-to-maintenance (TTM)**,
- a **confidence** (0–1) and a **prediction regime** (`coldstart` vs `trend`),
- a **root-cause explanation (RCA)** naming the fault + contributing signals,
- **cross-module flags** pointing at a likely common cause elsewhere.

---

## 3. How it's built (methodology)

### Condition monitoring, not failure-time regression
Because there are no failure labels, the system does **unsupervised, signal-driven
condition monitoring**. Health is a **penalty model**: each component starts at 100 and
loses **weighted, capped** points for each unhealthy signal:

```
health = clamp(100 − Σ wᵢ · penaltyᵢ , 0, 100)
```

Penalties are built from **normalised, dimensionless** signals — error/fault **rates**,
**ratios**, **robust z-scores** vs the component's own baseline and vs peers — never raw
counts (so a busy unit isn't unfairly punished for being busy). Full method:
[`methodology.md`](notebook/methodology.md).

### The store beats the 2-day data window
Most Grafana dashboards retain only ~2 days. The system overcomes this by **snapshotting
every component's metrics into a longitudinal store on every run**. Over many runs, that
store becomes a history far longer than any single fetch — which is what enables
**recurrence**, **persistence**, and **trend-based RUL** (remaining useful life). Two
regimes, always labelled:
- **coldstart** — little history → coarse, low-confidence tier bands.
- **trend** — enough history → fit the health trajectory and project when it crosses a
  maintenance threshold → sharper TTM, higher confidence.

This is why **running it regularly (automation) is what makes it predictive** — each run
is a data point that sharpens the forecast.

### Per-component → per-module → system
- **Per component:** the atomic verdict (e.g. lift `aisle_04_inbound_lift_02`).
- **Per module:** the tile status = the **worst** component's tier, so the most urgent
  problem surfaces first.
- **System-wide (Meta):** a correlation layer that reads every module's latest verdict and
  surfaces **compound incidents** — e.g. *controller saturation → network downtime →
  shuttle errors → bin blocks on one aisle* — as **one** investigation with a likely
  common cause, instead of ten unrelated flags.

### Tech stack
- **Python 3.11+**; **FastAPI + Uvicorn** web app; **APScheduler** in-process automation;
  **Playwright (Chromium)** + httpx for Grafana fetching; **numpy / pandas / scikit-learn**
  for modelling (no GPU, no heavy deps).
- **Server-rendered Jinja2** templates with vendored JS charts — fully **offline on a LAN
  PC**, no runtime CDN.
- **Storage abstraction** — CSV backend active; a MySQL backend is designed and dormant
  behind a permission gate. Switching backends changes no application code.
- **Plugin architecture** — each equipment type is a self-registering module under
  `modules/<name>/`; adding one needs no changes to the core.

---

## 4. What it tracks — the 11 modules

| # | Module | Component scored | Leading signal |
|---|--------|------------------|----------------|
| 1 | **Lift** | each ASRS lift | error rate + severity + mechanical-wear mix + recurrence + peer deviation |
| 2 | **Shuttle** | each shuttle (124) | errors per **million cycles** + severity + cycles-based RUL |
| 3 | **Conveyor** | each GTP zone (6) | congestion (queue vs limit) + **stall** (idle while peers flow) |
| 4 | **Tracker / Position-Sensor** | each grid location | bad-tracker (mislocated-tote) **clustering + cross-run recurrence** |
| 5 | **Gate / Door-Actuator** | each gate (52) | stuck-non-closed **latency** + cross-run persistence |
| 6 | **Bin / Tote-Mechanical** | each bin slot | **block-age** + chronic-slot history + cross-run recurrence |
| 7 | **GTP Station + Scanner** | 263 scanners + 63 stations | scanner **misread rate** + station **pick-discrepancy rate** |
| 8 | **Decanting Station + Scanner** | 9 scanners + 10 stations | scanner misread rate + station status/throughput persistence |
| 9 | **Network / Comms** | each shuttle comms link (124) | network **downtime %** + today-vs-window spike + aisle clustering |
| 10 | **Controller / Compute** | the controller node | CPU **utilisation %** + sustained-high + trend |
| 11 | **System-Wide Anomaly (Meta)** | 6 aisles + system | cross-module **compound-risk** (co-occurrence + causal chains + persistence) |

Per-module signal/field/formula detail: [`MODULE_METHODOLOGY.md`](MODULE_METHODOLOGY.md)
and each module's README. Source-panel mapping (and why non-health dashboards were
excluded): [`module_dashboard_mapping.md`](mapping/module_dashboard_mapping.md).

---

## 5. How it runs (operationally)

- **One process on one LAN PC** serves the dashboard **and** runs automation. Closing the
  browser never stops the engine — only stopping the process does.
- **Automation** (APScheduler) fires runs on an interval (per module or `global`); manual
  **"Run PdM now"** coexists. Every run is a **traceable trigger** (id, type, status,
  window, duration, counts).
- The **dashboard** (see [URL Map](URL_MAP.md)) provides: Overview tiles, per-module
  component tables + RCA + trend, PdM triggers, automation control, storage management
  (export/archive/delete), searchable logs, system/performance, and plugin/settings views.
- **Operating it day-to-day:** [Operator SOP](OPERATOR_SOP.md). **Hosting it:**
  [Hosting Resources](HOSTING_RESOURCES.md). **Extending it:** [Developer Guide](DEVELOPER_GUIDE.md).

---

## 6. The value it adds

- **Fewer surprise breakdowns.** Degradation is caught at `watch`/`warn` — days or hours
  of lead time — instead of at failure, cutting unplanned downtime and throughput loss.
- **Right-sized maintenance.** Work is targeted at the component the RCA names, with a TTM
  and confidence to prioritise — less over-servicing, less guesswork.
- **One investigation, not ten.** The Meta layer collapses correlated failures into a
  single compound incident with a likely common cause — faster diagnosis.
- **No new instrumentation, no logbook burden.** It uses the Grafana data the plant
  already produces; operators need only glance at tiles and, optionally, mark a service
  done (which never affects detection).
- **Gets better the longer it runs.** The store turns short-retention dashboards into a
  long-horizon predictive dataset; confidence and RUL sharpen automatically over time.
- **Built to last & to grow.** Clean plugin architecture (new equipment = a new module, no
  core changes), a storage layer ready to scale from CSV to MySQL with zero code change,
  all features persisted as JSON so future ML/analytics can build on the accumulated
  history without re-fetching. Correctness was hardened in a full audit
  ([`AUDIT_REPORT.md`](AUDIT_REPORT.md)); 31 automated tests guard the behaviour.

---

## 7. Current status

**Module set complete — 11/11 built and audited.** CSV storage active; MySQL designed and
ready behind a permission gate. The system is production-usable on a plant LAN PC today; a
move to MySQL (when the DB is provisioned) is a config switch plus a one-command data
migration ([Developer Guide §6](DEVELOPER_GUIDE.md#6-database-full--back-up--export-to-another-database)).
