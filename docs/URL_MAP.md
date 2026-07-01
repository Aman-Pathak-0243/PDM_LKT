# URL / Route Map — every endpoint, where it goes, what it does

> **Audience:** operators navigating the dashboard and developers/integrators calling the
> API. Enumerated from [`webapp/main.py`](../webapp/main.py) (HTML pages) and
> [`webapp/api.py`](../webapp/api.py) (JSON API). Everything binds `APP_HOST:APP_PORT`
> (default `0.0.0.0:8800`) and is **LAN-only**. Base URL: `http://<host-ip>:8800`.

Two layers share the same read-side services ([`webapp/services.py`](../webapp/services.py)),
so the HTML pages and the JSON API always agree:
- **HTML pages** — server-rendered Jinja2 templates (the dashboard humans use).
- **JSON API** (prefix **`/api`**) — backs the pages and any external tooling; write
  endpoints are audited to the `event_log`.

---

## 1. HTML pages (the dashboard)

Top-nav order. Each page loads data from the `/api/*` endpoints noted in "Backed by".

| Route | Page | What you see / do | Backed by |
|-------|------|-------------------|-----------|
| `GET /` | **Overview** | One **tile per module**: worst-component tier, per-tier counts, last-run time. Pick a **window** (top-right) and **Run PdM (all)**, or run a single module from its tile. The home screen. | `/api/modules`, `/api/run` |
| `GET /module/{name}` | **Module detail** | Per-component table (worst-first): score, tier, TTM, confidence, regime. Click a row → **RCA** + **health trend**. In-page **Methodology** section. Optional **Mark maintenance done**. `{name}` ∈ lift, shuttle, conveyor, tracker, gate, bin_mech, gtp_station, decant_station, network, controller, meta. | `/api/modules/{name}/components`, `.../methodology`, `.../components/{cid}/history`, `/api/ack` |
| `GET /triggers` | **PdM Triggers** | Every manual + automated run — id, type, status, window, duration, counts. Click one for its per-module run breakdown. | `/api/triggers`, `/api/triggers/{id}` |
| `GET /automation` | **Automation** | Enable/disable automation per **scope** (`global` or a module), set **interval** + **window**; shows **"next trigger at …"**. Runs in the terminal process, independent of the browser. | `/api/automation`, `/api/automation/run` |
| `GET /storage` | **Storage** | Total + per-dataset size/record-count/24h growth; **export** (CSV/JSON/Excel) by range; **delete** by range (confirmed + logged); **archive** + **restore**. | `/api/storage`, `/api/storage/*` |
| `GET /logs` | **Logs** | Searchable structured event log (filter by text, level, module, time). | `/api/logs` |
| `GET /system` | **System** | Health + performance metrics (run counts, avg/max/last run time, failures). | `/api/health`, `/api/performance` |
| `GET /plugins` | **Plugins** | The 11 registered modules: configured?, dashboards, panel count, signal-panel count, last run. | `/api/plugins`, `/api/catalog` |
| `GET /settings` | **Settings** | Read-only runtime config: Grafana base URL, app host/port, active storage backend. | (server-rendered from `Config`) |
| `GET /static/*` | static assets | Vendored CSS/JS + charts (offline, no CDN). | — |

---

## 2. JSON API (`/api`)

### Health & system
| Method + path | Purpose | Key params / body |
|---------------|---------|-------------------|
| `GET /api/health` | Liveness + backend + module list + time. Use for monitoring/Docker healthcheck. | — |
| `GET /api/performance` | Trigger/run totals, failures, avg/max/last trigger duration (ms). | — |

### Modules & components
| Method + path | Purpose | Key params |
|---------------|---------|------------|
| `GET /api/modules` | Summary per module: tier rollup, counts, configured?, last run. Backs the Overview tiles. | — |
| `GET /api/modules/{name}/methodology` | The module's methodology dict (signals, entity-verdict steps, formulas) merged with the shared overall-status rollup. Rendered in-page. | — |
| `GET /api/modules/{name}/components` | Latest health row per component (worst-first). | — |
| `GET /api/modules/{name}/components/{cid}/history` | Longitudinal history for one component (for the trend chart). | `limit` (default 300) |

### Runs & triggers
| Method + path | Purpose | Body / params |
|---------------|---------|---------------|
| `POST /api/run` | Kick off a manual run; returns a `trigger_id` immediately (runs on a worker thread). `module` omitted/`"all"` → every configured module. | `{ module?, window? }` |
| `GET /api/triggers` | Recent triggers (newest first), optionally filtered. | `limit` (50), `type`, `status` |
| `GET /api/triggers/{trigger_id}` | One trigger + its per-module `pdm_run` rows. | — |

### Automation
| Method + path | Purpose | Body |
|---------------|---------|------|
| `GET /api/automation` | Status of every scope (enabled, interval, window, **next_run_at**). | — |
| `POST /api/automation` | Create/update a scope's schedule (persisted; (re)schedules or removes the job). | `{ scope, enabled, interval_minutes, data_window? }` |
| `POST /api/automation/run` | Fire a scope now (as an `auto`-type trigger). | `{ scope, data_window? }` |

### Logs
| Method + path | Purpose | Params |
|---------------|---------|--------|
| `GET /api/logs` | Search the structured `event_log`. | `q`, `level`, `module`, `since_hours`, `limit` (200) |

### Storage management
| Method + path | Purpose | Params / body |
|---------------|---------|---------------|
| `GET /api/storage` | Store overview: backend, total size/rows, per-dataset size/rows/last-modified/24h-growth. | — |
| `GET /api/storage/archives` | List archive files under `data/archive/`. | — |
| `GET /api/storage/export` | Download a table (filtered) as CSV / JSON / Excel. Returns a file attachment. | `table` (req), `fmt` (csv\|json\|xlsx), `date_from`, `date_to`, `trigger_id`, `module` |
| `POST /api/storage/delete` | Delete matching rows (requires `confirm:true`); audited. | `{ table, date_from?, date_to?, trigger_id?, module?, confirm }` |
| `POST /api/storage/archive` | Move rows older than `before` to an archive CSV + delete from the active store; audited. | `{ table, before }` |
| `POST /api/storage/restore` | Re-insert rows from an archive file back into its table. | `{ file }` |

### Plugins / catalog / acknowledgements
| Method + path | Purpose | Params / body |
|---------------|---------|---------------|
| `GET /api/plugins` | Registered modules with config/panel/last-run info. | — |
| `GET /api/catalog` | The panel catalog (dashboards/panels/fields/SQL/is_signal), optionally per module. | `module?` |
| `POST /api/ack` | Record an optional operator "maintenance done" acknowledgement (annotates/silences a flag; never drives detection). | `{ module, component_id, acked_by?, note? }` |

---

## 3. Notes for integrators

- **Windows** use Grafana relative syntax (`now-6h`, `now-24h`, `now-2d`, `now-7d`,
  `now-30d`, `now-90d`, `now-365d`); the UI exposes these in the duration control.
- **Manual runs are asynchronous:** `POST /api/run` returns a `trigger_id` right away;
  poll `GET /api/triggers/{trigger_id}` for progress/status.
- **Errors:** invalid requests return `400` with a message (e.g. bad table/format, delete
  without `confirm`); unknown module/trigger returns `404`.
- **Auth:** none — access is confined to the trusted plant LAN by design (see
  [Hosting Resources §4](HOSTING_RESOURCES.md#4-network--firewall)).
- **Healthcheck for monitoring/Docker:** `GET /api/health`.
