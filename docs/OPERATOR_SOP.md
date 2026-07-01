# Operator SOP — running & monitoring the ASRS Predictive-Maintenance system

> **Audience:** the plant operator / maintenance coordinator who runs this system day to
> day. No coding needed. This is the standard operating procedure: how to start it, what
> to look at, how often, where each thing lives in the dashboard, and what to do when
> something turns amber or red.
>
> **What the system does in one line:** every time it runs, it reads the plant's Grafana
> operational + error data, scores each physical component's health (0–100), and tells
> you *what* is degrading, *how urgent*, *how confident*, and *why* — so you fix things
> **before** they fail. See [System Overview](SYSTEM_OVERVIEW.md) for the big picture.

---

## 0. Mental model (read once)

- The system scores **components** (a lift, a shuttle, a gate, a conveyor zone, a bin
  slot, a scanner, a comms link, the controller). Each gets a **health score**, a **risk
  tier**, a **time-to-maintenance (TTM)**, a **confidence**, and a plain-English **cause**.
- **Risk tiers** (the colours you act on):
  | Tier | Score | Meaning | Your action |
  |------|-------|---------|-------------|
  | `ok` | ≥ 85 | Healthy | none |
  | `watch` | 65–85 | Early drift | keep an eye on it; note it |
  | `warn` | 40–65 | Degrading | schedule a look this shift/day |
  | `critical` | < 40 | Failing / failed | investigate now |
- A module's **tile colour = its worst component.** One critical unit makes the whole
  module tile red so the most urgent problem surfaces first.
- **Confidence** tells you how much to trust a flag: a `critical` at 0.9 confidence is
  actionable now; the same at 0.3 means "watch and let history build." Confidence rises
  automatically the more often the system runs (see §4).
- The system **gets smarter the more it runs.** Each run is a snapshot; over many runs it
  builds a history that turns a 2-day data window into long-horizon prediction. **This is
  why automation matters** — leave it on.

---

## 1. Starting & stopping the system

The system is **one program** that serves the dashboard **and** runs the automation.

| Action | How |
|--------|-----|
| **Start** | On the host PC, in the project folder: `\.venv/bin/python run.py` (see the README for first-time install). |
| **Open the dashboard** | Any device on the same LAN: `http://<host-ip>:8800`. |
| **Confirm it's alive** | Browse to `http://<host-ip>:8800/api/health` → should say `{"status":"ok", …}`. |
| **Stop** | In the terminal running it, press **Ctrl-C**. This is the **only** thing that stops automation. |

> **Important:** closing your browser does **not** stop anything. Scheduled runs,
> automation, and trigger monitoring all live in the terminal process. You can close the
> dashboard, go home, and it keeps predicting. Reopen it any time — it reconnects to the
> already-running system without interrupting a thing.

**If the dashboard won't load from another PC:** the host firewall is blocking port 8800.
Ask IT to allow inbound TCP `8800` (Windows: inbound rule; macOS: Firewall → allow
Python). Same-subnet only — there is no public/internet access by design.

---

## 2. First-time setup (one-off, with the maintenance lead)

1. Open **Automation** (top nav → *Automation*).
2. Set the **global** scope: **enable it**, pick an **interval** (recommended **60 min**
   to start), and a **window** (recommended **now-2d**). Save.
3. The page shows **"next trigger at …"** — automation is now running unattended.
4. (Optional) Enable a tighter interval for a specific module (e.g. a busy GTP line) by
   setting that module's scope separately.

That's it. From now on the system runs itself; your job is the monitoring routine below.

---

## 3. Where everything lives (dashboard map)

Top navigation bar, left → right. (Full route reference: [URL Map](URL_MAP.md).)

| Nav item | URL | What you use it for |
|----------|-----|---------------------|
| **Overview** | `/` | The home screen. One tile per module + its worst status. Start here every time. |
| **PdM Triggers** | `/triggers` | The log of every run (manual + automatic) — id, type, status, duration, counts. Check a run finished. |
| **Automation** | `/automation` | Turn scheduled runs on/off, set interval + window, see "next trigger at". |
| **Storage** | `/storage` | Store size, per-table growth, export/archive/delete old data. |
| **Logs** | `/logs` | Searchable event log — what happened and when (errors, run completions). |
| **System** | `/system` | Health + performance (run counts, average run time, failures). |
| **Plugins** | `/plugins` | The 11 modules, whether each is configured, its panel count, last run. |
| **Settings** | `/settings` | Read-only runtime config (Grafana URL, host/port). |
| **A module's detail** | `/module/<name>` | Click any tile. Per-component table + RCA + trend + "Mark maintenance done". |

---

## 4. The monitoring routine (regular vs interval tasks)

### Every shift (2–3 min) — the "walk the board" check
1. Open **Overview** (`/`).
2. Scan the tiles. **Any red (`critical`) or amber (`warn`)?**
   - **Yes** → click that tile → §5 (triage a flagged component).
   - **No** → done.
3. Glance at each tile's **last-run time**. If a tile says a module hasn't run in far
   longer than the automation interval, check **Automation** and **Logs** (§6).

### Daily (5–10 min)
1. **PdM Triggers** (`/triggers`) — confirm the automated runs are **success** (not
   `failed`/`partial`). A `failed` run usually means Grafana was unreachable or a
   dashboard changed — see §6.
2. **Overview** — note any component that moved **ok → watch** or **watch → warn** since
   yesterday. Rising tiers are your early-warning list even before anything is critical.
3. For anything at **warn/critical**, open its module page and read the **RCA** (§5) to
   decide whether to raise a work order.

### Weekly (10–15 min)
1. **System** (`/system`) — check the failure count and average run time are stable
   (a climbing average run time can mean Grafana is slow).
2. **Storage** (`/storage`) — check total size and 24 h growth. If the store is getting
   large, **archive** or **delete** old rows by date range (§7).
3. Review components that have been stuck at **watch** for the whole week — persistent
   drift is exactly what this system is meant to catch early; consider a proactive
   inspection.

### On-demand (any time) — "Run PdM now"
- On **Overview**, pick a **window** (top-right) and click **Run PdM (all)** to force a
  fresh run of every module; or click **Run** on a single module's tile.
- Use this after you've serviced something (to see the new reading), or when you suspect
  a problem and don't want to wait for the next scheduled run.

---

## 5. Triaging a flagged component (the core operator skill)

When a tile is amber/red:

1. **Click the tile** → the module page (`/module/<name>`). The component table is
   sorted **worst-first**.
2. **Read the top row(s):**
   - **Risk tier + health score** — how bad.
   - **Predicted TTM** — roughly how long until it needs maintenance (hours/days). A `0`
     or very small TTM means act now.
   - **Confidence** — how sure. High confidence + warn/critical = act. Low confidence =
     valid early signal, let a few more runs confirm it.
   - **Regime** — `coldstart` (few runs of history, coarse estimate) vs `trend` (enough
     history, sharper estimate). Over time flags move from coldstart to trend.
3. **Click the row** → the **RCA** (root-cause) panel + the **health trend** chart.
   - The **primary cause** is a plain sentence naming the fault (e.g. *"Lift Motor
     exceeded software limit (code 14) — 22 events"*, *"Zone idle 100% of the window
     while peers flow — possible belt/motor stall"*, *"Compound incident on aisle_01: 3
     subsystems degraded"*).
   - The **contributors** list ranks what pulled the score down.
   - **Cross-module flags** point you at a likely common cause in another subsystem
     (e.g. a comms link degrading → the Shuttle it serves; a saturated controller →
     system-wide). If you see the same aisle flagged in **Meta**, treat it as **one**
     investigation, not many.
4. **Decide:** raise a work order / inspection for the named component, or (if low
   confidence, coldstart) watch it for another run or two.
5. **After servicing:** on the component's row, click **"Mark maintenance done"**. This
   silences the current flag and resets that component's baseline so post-service
   behaviour is judged fresh. *(It is optional and never affects detection — it's just a
   convenience so a fixed unit stops nagging.)*

### What each tile's status means at a glance
- **Overview tile** shows the **worst tier**, the **count in each tier**, and the
  **last-run time**. A module reading `critical (1) / warn (2) / ok (30)` has 1 urgent + 2
  to-schedule units among 33 — open it to see which.

---

## 6. When a run fails or a module looks stale

1. **PdM Triggers** (`/triggers`) → open the failed run → read its message.
2. **Logs** (`/logs`) → search the module name or "failed" for the detailed error.
3. Common causes & fixes:
   | Symptom | Likely cause | Fix |
   |---------|--------------|-----|
   | All modules fail at once | Grafana unreachable / login failed | Check the Grafana server + LAN; verify credentials in `.env` (ask the developer). |
   | One module fails | That dashboard/panel changed or is empty | Note it and tell the developer (a panel column may have been renamed). |
   | A module tile never updates | Automation off for that scope | **Automation** → enable global (or that module). |
   | Runs succeed but a module scores 0 components | The source returned no rows in the window | Widen the **window** (e.g. now-7d) and Run now; if still empty, tell the developer. |
4. You **cannot break anything** from the dashboard — the worst case is re-running. When
   in doubt, **Run PdM now** and re-check.

---

## 7. Housekeeping (Storage page)

The store (`data/store/`) grows a little every run — it's the memory that makes
predictions sharpen over time, so **don't delete it casually**. Manage it here:

- **See size & growth:** total size, per-table rows/size, and "added last 24 h".
- **Export** (for a report or hand-off): pick a table + date range → **CSV / JSON /
  Excel**.
- **Archive** old rows: moves rows older than a date into `data/archive/` (kept, just out
  of the active store) — use this to keep the store lean without losing history.
- **Delete** by date range: permanent; requires a confirm and is logged. Only for data
  you're sure you don't need.

Rough sizing: the whole system writes ≈ **770 component rows per full run** (~1.6 KB
each). Hourly automation is ≈ **18,000 rows/day** ≈ a few MB/day — years fit on a normal
PC disk. See [Hosting Resources](HOSTING_RESOURCES.md) for the full projection.

---

## 8. Quick reference card

| I want to… | Go to | Do |
|------------|-------|----|
| See if anything needs attention | **Overview** `/` | Scan tiles for amber/red |
| Understand *why* a unit is flagged | **Module page** → click the row | Read RCA + trend |
| Force a fresh check | **Overview** | Pick window → **Run PdM (all)** |
| Turn scheduled runs on/off | **Automation** | Enable + interval + window |
| Confirm the last runs succeeded | **PdM Triggers** | Look for `success` |
| Find an error | **Logs** | Search text/level/module |
| Mark something serviced | **Module page** → row | **Mark maintenance done** |
| Free up / export data | **Storage** | Export / Archive / Delete by range |
| Check the system is up (from anywhere) | browser | `http://<host-ip>:8800/api/health` |

---

## 9. Golden rules

1. **Leave automation on.** Predictions only improve with regular runs.
2. **Act on tier + confidence together**, not the score alone.
3. **Red = investigate now; amber = schedule; rising trend = early warning.**
4. **Read the RCA before raising a work order** — it names the part and the reason.
5. **Cross-module / Meta flags mean "one common cause"** — investigate once, not per unit.
6. **Only Ctrl-C stops automation.** Closing the browser does nothing to the engine.
7. **When unsure, Run PdM now and re-read.** You cannot harm anything from the UI.
