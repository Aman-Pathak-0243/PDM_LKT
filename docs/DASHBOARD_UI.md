# Dashboard UI & Graphical Overview

> **Audience:** operators reading the dashboard and developers extending it. Describes the
> **Overview** page's two tabs — **Module Health** (tiles) and the **Graphical Overview**
> (fleet analytics) — every chart on it, the data behind each, and the design rules the
> charts follow. Source: [`webapp/templates/index.html`](../webapp/templates/index.html),
> [`webapp/static/js/app.js`](../webapp/static/js/app.js),
> [`webapp/static/js/charts.js`](../webapp/static/js/charts.js),
> [`webapp/static/css/app.css`](../webapp/static/css/app.css), and
> [`webapp/services.py`](../webapp/services.py) (`overview_analytics`).

---

## 1. The Overview page has two tabs

The home screen (`GET /`) opens a **tab bar** with:

1. **Module Health** *(default)* — the original grid of one **tile per registered module**:
   worst-component tier, per-tier counts, last-run time, a **Run now** button. Click a tile
   → the per-module page. Unchanged behaviour; it is now the first tab.
2. **Graphical Overview** — a **fleet-wide analytics** view: a KPI stat row plus seven
   modern charts that read across **all** modules at once. Loaded **lazily** the first time
   the tab is opened (charts need a visible width to size their SVGs), then re-rendered when
   the **window** control changes, after a **Run PdM** completes, and on window resize.

Both tabs share the top-bar **window** control and **Run PdM (all)** button.

---

## 2. Where the data comes from

Every chart is fed by **one** aggregation endpoint:

```
GET /api/overview/analytics?window=<now-Nd|now-Nh|…>
```

backed by `webapp.services.overview_analytics(window)`. It reads the accumulated
**`component_health`** store (the longitudinal snapshot every PdM run writes) plus
`pdm_run` / `trigger_log` counts, and returns fleet rollups. It **degrades to
empty-but-valid shapes** when no run has happened yet, so the page never errors on a cold
store — the KPI row renders zeros and an empty-state note replaces the charts.

Key fields in the response:

| Field | Feeds | Notes |
|-------|-------|-------|
| `kpis` | the KPI stat row | totals, per-tier counts, avg health, imminent (TTM ≤ 24h), regime split, last run |
| `tier_distribution` | Fleet status donut | `critical / warn / watch / ok` counts (fixed order) |
| `fleet_trend` | Fleet health trend | avg health across all components, adaptively time-bucketed within the window |
| `modules` | Risk breakdown by module | per-module component count, tier counts, worst tier, avg health |
| `score_histogram` | Health-score distribution | 10-point bands, coloured by the band's tier |
| `aisle_matrix` | Aisle × module risk map | `{aisles, modules, cells}` — worst tier + count + avg health per (aisle, module) |
| `top_at_risk` | Top at-risk components | up to 12 lowest-health flagged components, worst-first |
| `ttm_buckets` | Time-to-maintenance | flagged components grouped by predicted TTM (`≤24h / 1–3d / 3–7d / >7d`) |

**Aisle resolution (heatmap).** A component's aisle is taken from the module-computed
`metrics_json.aisle` first (authoritative — ids like `QD_Shuttle_03_06` or the bin location
`002-04-1-221-1-02` carry no literal `aisle` token), and only falls back to parsing an
`aisle_NN` token out of the component id. Components with no aisle (e.g. conveyor `zone_*`,
the single `db_controller`, GTP/decant station names, the meta `system` scope) are simply
absent from the heatmap; they still appear in every other chart.

**Window.** The window control re-scopes the **trend** time span (it filters the store by
`created_at`). The at-a-glance rollups (donut, heatmap, module breakdown, at-risk, TTM) use
each component's **latest** snapshot, i.e. the current fleet state.

---

## 3. The charts

| Chart | Form | Reads | What it answers |
|-------|------|-------|-----------------|
| **KPI stat row** | 6 stat tiles (one with a sparkline) | `kpis`, `fleet_trend` | Fleet health, components monitored, critical, warnings, imminent (≤24h), trend coverage |
| **Fleet health trend** | gradient area + crosshair tooltip | `fleet_trend` | Is the fleet's average health rising or falling over the window? |
| **Fleet status mix** | donut + legend + centre total | `tier_distribution` | What share of components sit in each risk tier? |
| **Risk breakdown by module** | horizontal stacked bars | `modules` | Which modules carry the most critical/warn components? (worst-first) |
| **Health-score distribution** | vertical bars (tier-coloured) | `score_histogram` | How is fleet health distributed across 0–100? |
| **Aisle × module risk map** | heatmap (6 aisles × equipment types) | `aisle_matrix` | Which **aisle** and **equipment type** is worst — the six-aisle ASRS layout at a glance |
| **Top at-risk components** | horizontal ranked bars | `top_at_risk` | The specific units needing attention first (bar = risk = 100 − health; label = health) |
| **Time-to-maintenance** | vertical bars (urgency-coloured) | `ttm_buckets` | How soon is flagged work due? |

---

## 4. Design & implementation rules

- **Dependency-free, offline, LAN-safe.** All charts are hand-built **inline SVG** in
  [`charts.js`](../webapp/static/js/charts.js) (`area`, `donut`, `bars`, `barsH`,
  `stackedBarH`, `heatmap`, `legend`, plus the existing `line` / `sparkSVG`). **No CDN, no
  chart library, no runtime network calls** — consistent with the offline-on-a-LAN-PC rule
  (CLAUDE.md §1.4, §2).
- **Status palette, never colour-alone.** Tier colours mean **state**
  (`ok`/`watch`/`warn`/`critical`), reused from the tiles/badges, and are always paired with
  a legend, a label, or a hover tooltip — so meaning is never conveyed by colour alone. The
  set passes colourblind-separation (adjacent ΔE ≈ 16) and ≥ 3:1 contrast on the dark
  surface.
- **Marks & chrome.** Thin marks, rounded (4px) data-ends anchored to the baseline, a small
  surface gap between stacked segments and adjacent bars, hairline grid one shade off the
  surface, and **selective** direct labels (value at a bar end, not on every mark).
- **Interaction.** Per-mark hover tooltips on bars / donut segments / heatmap cells; a
  **crosshair + focus-dot + tooltip** on the trend area. The trend area **auto-scales** its
  y-domain to the data (padded, clamped 0–100) so a small movement in a high, tight range
  still reads as a real trend instead of a flat line pinned to a fixed 0–100 axis.
- **Responsive.** The KPI row collapses 6 → 3 → 2 columns and the chart grid reflows to one
  column on narrow viewports; charts redraw from cached data on resize (no refetch).

---

## 5. Extending it

- **Add a metric to the KPI row / an existing chart** — extend the dict returned by
  `overview_analytics` in [`webapp/services.py`](../webapp/services.py); no schema change is
  needed (it reads the existing `component_health` columns and JSON metrics).
- **Add a new chart type** — add a pure-SVG renderer to
  [`charts.js`](../webapp/static/js/charts.js) (follow the existing signature
  `fn(container, data, opts)` and the mark/colour rules above), a container in the
  `#tab-graphs` panel of [`index.html`](../webapp/templates/index.html), and a render call
  in `renderAnalytics()` in [`app.js`](../webapp/static/js/app.js).
- **New modules appear automatically** — the analytics aggregation iterates the module
  registry, so a newly-registered module shows up in the donut, module breakdown, histogram,
  at-risk list, and (if its components carry an aisle) the heatmap, with no changes here.
