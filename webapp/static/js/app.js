/* PdM dashboard front-end. Dependency-free. Talks to /api/*. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const PAGE = document.documentElement.dataset.page;

  // ---- helpers -----------------------------------------------------------
  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.status === 204 ? null : res.json();
  }
  const postJSON = (path, body) =>
    api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  function h(tag, attrs, children) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === "class") e.className = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    }
    (Array.isArray(children) ? children : [children]).forEach((c) => {
      if (c == null) return;
      e.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(c) : c);
    });
    return e;
  }
  const scoreTier = (s) => (s == null ? "unknown" : s >= 85 ? "ok" : s >= 65 ? "watch" : s >= 40 ? "warn" : "critical");
  const tierBadge = (t) => `<span class="tier tier-${t || "unknown"}">${t || "n/a"}</span>`;
  function healthBar(score) {
    const t = scoreTier(score);
    const c = window.Charts.tierColor(t);
    return `<div class="hbar"><span style="width:${Math.max(0, Math.min(100, score || 0))}%;background:${c}"></span></div>`;
  }
  const fmtDate = (s) => (s ? String(s).replace("T", " ").replace(/\.\d+/, "").replace(/(\+00:00|Z)$/, "") : "—");
  const fmtNum = (n) => (n == null ? "—" : n);
  function toast(msg) {
    let t = $(".toast"); if (!t) { t = h("div", { class: "toast" }); document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2600);
  }
  const win = () => ($("#global-window") ? $("#global-window").value : null);

  // ---- run + poll --------------------------------------------------------
  async function runNow(module) {
    const status = $("#run-status");
    try {
      const r = await postJSON("/api/run", { module: module || null, window: win() });
      if (status) status.textContent = "running…";
      toast(`Trigger ${module || "all"} started`);
      pollTrigger(r.trigger_id);
    } catch (e) { toast("run failed: " + e.message); }
  }
  async function pollTrigger(tid, tries) {
    tries = tries || 0;
    try {
      const d = await api("/api/triggers/" + tid);
      const st = d.trigger.status;
      const status = $("#run-status");
      if (st === "running" && tries < 120) {
        if (status) status.textContent = "running…";
        return setTimeout(() => pollTrigger(tid, tries + 1), 1500);
      }
      if (status) status.textContent = st;
      toast(`Trigger ${st}`);
      refreshPage();
    } catch (e) {
      if (tries < 5) return setTimeout(() => pollTrigger(tid, tries + 1), 1500);
    }
  }

  // ---- pages -------------------------------------------------------------
  async function initOverview() {
    const root = $("#modules"); if (!root) return;
    const mods = await api("/api/modules");
    root.innerHTML = "";
    if (!mods.length) { root.appendChild(h("div", { class: "empty" }, "no modules registered")); return; }
    mods.forEach((m) => {
      const counts = Object.entries(m.tier_counts || {})
        .map(([t, n]) => `<span class="pill"><span class="dot dot-${t}"></span>${t}: ${n}</span>`).join(" ");
      const card = h("div", { class: "card click", onclick: () => (location.href = "/module/" + m.name) }, [
        h("div", { class: "tile-head" }, [
          h("div", { class: "tile-title" }, m.title),
          h("div", { html: tierBadge(m.configured ? m.worst_tier : "unknown") }),
        ]),
        h("div", { class: "kpi" }, String(m.component_count)),
        h("div", { class: "kpi-sub" }, `${m.component_type}s monitored`),
        h("div", { class: "tier-counts", html: counts }),
        h("div", { class: "kpi-sub", html: `last run: ${fmtDate(m.last_run_at)} ${m.last_run_status ? "(" + m.last_run_status + ")" : ""}` }),
        h("div", { class: "row", style: "margin-top:10px" }, [
          h("button", { class: "btn btn-sm btn-primary", onclick: (ev) => { ev.stopPropagation(); runNow(m.name); } }, "Run now"),
          h("span", { class: "muted", html: m.configured ? `${m.dashboards.length} sources` : "not configured" }),
        ]),
      ]);
      root.appendChild(card);
    });
  }

  // ---- graphical overview (analytics tab) --------------------------------
  const TIERS = ["critical", "warn", "watch", "ok"];
  const tierRank = (t) => { const i = TIERS.indexOf(t); return i < 0 ? TIERS.length : i; };
  const shortTitle = (t) => String(t || "").replace(/\s*PdM$/, "");
  const aisleLabel = (a) => String(a || "").replace(/^aisle_0*/, "Aisle ");
  let analyticsLoaded = false, lastAnalytics = null;

  async function initAnalytics() {
    const kpiRow = $("#kpi-row"); if (!kpiRow) return;
    let a;
    try { a = await api("/api/overview/analytics?window=" + encodeURIComponent(win() || "")); }
    catch (e) { kpiRow.innerHTML = `<div class="empty">analytics unavailable: ${e.message}</div>`; return; }
    analyticsLoaded = true; lastAnalytics = a;
    renderAnalytics(a);
  }

  function renderAnalytics(a) {
    if (!a) return;
    renderKpis(a);
    const body = $("#graphs-body"), empty = $("#graphs-empty");
    if (!a.has_data) { if (body) body.hidden = true; if (empty) empty.hidden = false; return; }
    if (empty) empty.hidden = true; if (body) body.hidden = false;
    const C = window.Charts;

    // Fleet health trend (area + crosshair)
    C.area($("#ch-trend"), (a.fleet_trend || []).map((p) => ({ t: fmtDate(p.t), v: p.v, n: p.n })), { height: 210 });

    // Fleet status donut + legend
    const segs = (a.tier_distribution || []).map((d) => ({ label: d.tier, value: d.count, color: C.tierColor(d.tier) }));
    C.donut($("#ch-donut"), segs, { center: { value: a.kpis.total_components, label: "components" } });
    C.legend($("#ch-donut-lg"), segs.map((s) => ({ label: s.label, color: s.color, value: s.value })));

    // Risk breakdown by module (stacked horizontal)
    const crit = (m) => (m.tier_counts || {}).critical || 0;
    const mrows = (a.modules || []).filter((m) => m.component_count > 0)
      .sort((x, y) => tierRank(x.worst_tier) - tierRank(y.worst_tier) || crit(y) - crit(x))
      .map((m) => ({
        label: shortTitle(m.title),
        sub: `${m.component_count} ${m.component_type}s · avg ${m.avg_health == null ? "—" : m.avg_health}`,
        segments: TIERS.map((t) => ({ key: t, value: (m.tier_counts || {})[t] || 0, color: C.tierColor(t) })),
      }));
    C.stackedBarH($("#ch-modules"), mrows);
    C.legend($("#ch-modules-lg"), TIERS.map((t) => ({ label: t, color: C.tierColor(t) })));

    // Health-score distribution
    C.bars($("#ch-hist"), (a.score_histogram || []).map((b) => ({
      label: String(b.lo), tipLabel: `${b.lo}–${b.hi}`, value: b.count, color: C.tierColor(b.tier),
    })));

    // Aisle × module heatmap
    const m = a.aisle_matrix || { aisles: [], modules: [], cells: [] };
    const idx = {}; (m.cells || []).forEach((c) => (idx[c.aisle + "|" + c.module] = c));
    C.heatmap($("#ch-heat"), {
      rows: (m.aisles || []).map((x) => ({ key: x, label: aisleLabel(x) })),
      cols: (m.modules || []).map((x) => ({ key: x.name, label: shortTitle(x.title) })),
      cell: (r, c) => {
        const cd = idx[r + "|" + c]; if (!cd) return null;
        return {
          color: C.tierColor(cd.worst_tier), text: cd.count,
          tip: `${aisleLabel(r)} · ${c}: ${cd.worst_tier} · ${cd.count} comps · avg ${cd.avg_health == null ? "—" : cd.avg_health}`,
        };
      },
    });
    C.legend($("#ch-heat-lg"), [...TIERS.map((t) => ({ label: t, color: C.tierColor(t) })), { label: "no data", color: "#141a22" }]);

    // Top at-risk components (bar encodes risk = 100 − health, worst-first)
    C.barsH($("#ch-risk"), (a.top_at_risk || []).map((c) => ({
      label: c.component_id,
      value: 100 - (c.health_score == null ? 100 : c.health_score),
      valueLabel: c.health_score == null ? "—" : c.health_score,
      color: C.tierColor(c.risk_tier),
      sub: `${shortTitle(c.module_title)} · ${c.primary_cause || c.risk_tier}`,
    })), { max: 100 });

    // Time-to-maintenance buckets (sooner = worse tier colour)
    const ttmColor = { "≤24h": "critical", "1–3d": "warn", "3–7d": "watch", ">7d": "ok" };
    C.bars($("#ch-ttm"), (a.ttm_buckets || []).map((b) => ({
      label: b.label, value: b.count, color: C.tierColor(ttmColor[b.label] || "unknown"),
    })));

    const meta = $("#graphs-meta");
    if (meta) meta.textContent =
      `${a.kpis.total_components} components across ${a.kpis.modules_total} modules · ` +
      `window ${a.window || "default"} · generated ${fmtDate(a.generated_at)}`;
  }

  function renderKpis(a) {
    const k = a.kpis || {};
    const healthTier = scoreTier(k.avg_health);
    const spark = window.Charts.sparkSVG((a.fleet_trend || []).map((p) => p.v), 130, 26, window.Charts.tierColor(healthTier));
    const tile = (label, value, sub, color) =>
      `<div class="stat"><div class="stat-label">${label}</div>` +
      `<div class="stat-val"${color ? ` style="color:${color}"` : ""}>${value}</div>` +
      `<div class="stat-sub">${sub || ""}</div></div>`;
    $("#kpi-row").innerHTML = [
      tile("Fleet health", k.avg_health == null ? "—" : k.avg_health,
        spark || "avg component health", k.avg_health == null ? null : window.Charts.tierColor(healthTier)),
      tile("Components monitored", k.total_components || 0,
        `${k.modules_configured}/${k.modules_total} modules configured`),
      tile("Critical", k.critical || 0, "immediate attention", k.critical ? window.Charts.tierColor("critical") : null),
      tile("Warnings", k.warn || 0, "degrading units", k.warn ? window.Charts.tierColor("warn") : null),
      tile("Imminent", k.imminent || 0, "predicted maint. ≤24h", k.imminent ? window.Charts.tierColor("critical") : null),
      tile("Trend coverage", `${k.trend || 0}/${k.total_components || 0}`,
        `${k.coldstart || 0} still cold-start`),
    ].join("");
  }

  function activateTab(name) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $$(".tab-panel").forEach((p) => {
      const on = p.id === "tab-" + name;
      p.classList.toggle("active", on); p.hidden = !on;
    });
    if (name === "graphs" && !analyticsLoaded) initAnalytics();
  }

  async function renderMethodology(name) {
    const box = $("#methodology-body"); if (!box) return;
    try {
      const m = await api(`/api/modules/${name}/methodology`);
      const list = (arr) => `<ol>${(arr || []).map((x) => `<li>${x}</li>`).join("")}</ol>`;
      const signals = (m.signals || []).map((s) =>
        `<tr><td><strong>${s.name}</strong></td><td class="muted">${s.source}</td><td>${s.what}</td></tr>`).join("");
      const formulas = (m.formulas || []).map((f) =>
        `<span class="pill mono">${f.name} = ${f.formula}</span>`).join(" ");
      const os = m.overall_status || {};
      box.innerHTML = `
        <p>${m.summary || m.description || ""}</p>
        <h3>Signals used</h3>
        <div class="table-wrap"><table><thead><tr><th>Signal</th><th>Source</th><th>What it tells us</th></tr></thead><tbody>${signals}</tbody></table></div>
        <h3 style="margin-top:14px">How a single ${m.component_type}'s status is reached</h3>
        ${list(m.entity_verdict)}
        ${formulas ? `<div class="tier-counts">${formulas}</div>` : ""}
        <h3 style="margin-top:14px">How the overall module status is reached</h3>
        <p>${os.summary || ""}</p>${list(os.rules)}`;
    } catch (e) { box.textContent = "methodology unavailable: " + e.message; }
  }

  async function initModule() {
    const rootEl = $("#module-root"); if (!rootEl) return;
    const name = rootEl.dataset.module;
    renderMethodology(name);
    const comps = await api(`/api/modules/${name}/components`);
    const body = $("#components");
    body.innerHTML = "";
    if (!comps.length) {
      body.innerHTML = '<tr><td colspan="7" class="empty">no scored components yet — click “Run now”.</td></tr>';
      return;
    }
    comps.forEach((c) => {
      const tr = h("tr", { class: "click", onclick: () => toggleDetail(name, c, tr) }, [
        h("td", { class: "mono" }, c.component_id),
        h("td", { html: healthBar(c.health_score) + ` <span class="muted">${(c.health_score || 0).toFixed(1)}</span>` }),
        h("td", { html: tierBadge(c.risk_tier) }),
        h("td", {}, c.prediction_regime),
        h("td", {}, c.predicted_ttm_hours == null ? "—" : c.predicted_ttm_hours + " h"),
        h("td", {}, ((c.confidence || 0) * 100).toFixed(0) + "%"),
        h("td", { class: "wrap muted" }, c.primary_cause || ""),
      ]);
      body.appendChild(tr);
    });
  }
  let openDetail = null;
  async function toggleDetail(module, c, tr) {
    if (openDetail) { openDetail.remove(); const was = openDetail; openDetail = null; if (was.dataset.for === c.component_id) return; }
    const rca = c.rca_json || {};
    const contributors = (rca.contributors || []).map((x) => `<span class="pill">${x.label}: ${x.points}</span>`).join(" ");
    const mix = Object.entries(rca.error_mix || {}).map(([k, v]) => `code ${k}: ${v}`).join(", ");
    const cross = (rca.cross_module_flags || []).map((f) => `→ ${f.module}: ${f.reason}`).join("; ");
    const detail = h("tr", { "data-for": c.component_id }, [
      h("td", { colspan: "7" }, [
        h("div", { class: "row" }, [
          h("strong", {}, "RCA: "), h("span", {}, rca.summary || c.primary_cause || "—"),
        ]),
        h("div", { class: "tier-counts", html: contributors }),
        h("div", { class: "kpi-sub", style: "margin-top:8px", html: `error mix: ${mix || "—"}${cross ? " · cross-module: " + cross : ""}` }),
        h("div", { style: "margin-top:10px" }, [h("h3", {}, "Health trend"), h("div", { id: "trend-" + c.component_id })]),
        h("div", { class: "row", style: "margin-top:10px" }, [
          h("button", { class: "btn btn-sm", onclick: () => ackComponent(module, c.component_id) }, "Mark maintenance done (optional)"),
        ]),
      ]),
    ]);
    tr.after(detail); openDetail = detail;
    const hist = await api(`/api/modules/${module}/components/${encodeURIComponent(c.component_id)}/history`);
    window.Charts.line($("#trend-" + c.component_id), hist.map((r) => ({ t: fmtDate(r.created_at), v: r.health_score, tier: r.risk_tier })), { yMin: 0, yMax: 100 });
  }
  async function ackComponent(module, cid) {
    try { await postJSON("/api/ack", { module, component_id: cid, acked_by: "operator" }); toast("acknowledged — baseline will reset"); }
    catch (e) { toast("ack failed: " + e.message); }
  }

  async function initTriggers() {
    const body = $("#triggers"); if (!body) return;
    const rows = await api("/api/triggers?limit=80");
    body.innerHTML = "";
    if (!rows.length) { body.innerHTML = '<tr><td colspan="8" class="empty">no triggers yet</td></tr>'; return; }
    rows.forEach((t) => {
      const tr = h("tr", { class: "click", onclick: () => showTrigger(t.trigger_id, tr) }, [
        h("td", { class: "mono" }, t.trigger_id),
        h("td", { html: `<span class="pill">${t.trigger_type}</span>` }),
        h("td", {}, t.module || "all"),
        h("td", { html: tierBadge(t.status === "success" ? "ok" : t.status === "running" ? "watch" : "critical") }),
        h("td", {}, t.data_window),
        h("td", {}, (t.duration_ms || 0) + " ms"),
        h("td", {}, `${t.success_count || 0}/${(t.success_count || 0) + (t.failure_count || 0)}`),
        h("td", {}, fmtDate(t.created_at)),
      ]);
      body.appendChild(tr);
    });
  }
  let openTrig = null;
  async function showTrigger(tid, tr) {
    if (openTrig) { openTrig.remove(); openTrig = null; }
    const d = await api("/api/triggers/" + tid);
    const runs = (d.runs || []).map((r) => `${r.module}: ${r.status} (${r.components_scored} comps, ${r.rows_fetched} rows)`).join(" · ");
    const detail = h("tr", {}, [h("td", { colspan: "8", class: "wrap" }, [
      h("div", { html: `<strong>runs:</strong> ${runs || "—"}` }),
      h("div", { class: "kpi-sub", html: `message: ${d.trigger.message || ""}` }),
    ])]);
    tr.after(detail); openTrig = detail;
  }

  async function initAutomation() {
    const root = $("#automation-rows"); if (!root) return;
    const [statuses, mods] = await Promise.all([api("/api/automation"), api("/api/modules")]);
    const byScope = {}; statuses.forEach((s) => (byScope[s.scope] = s));
    const scopes = ["global", ...mods.map((m) => m.name)];
    root.innerHTML = "";
    scopes.forEach((scope) => {
      const s = byScope[scope] || { scope, enabled: false, interval_minutes: 60, data_window: win() };
      const id = "auto-" + scope;
      const row = h("div", { class: "card", id }, [
        h("div", { class: "tile-head" }, [
          h("div", { class: "tile-title" }, scope === "global" ? "Global (all modules)" : scope),
          h("span", { class: "pill", html: s.enabled ? "ENABLED" : "disabled" }),
        ]),
        h("div", { class: "form-grid" }, [
          labeled("Enabled", h("select", { id: id + "-en" }, [opt("true", "enabled", s.enabled), opt("false", "disabled", !s.enabled)])),
          labeled("Interval (min)", h("input", { id: id + "-int", type: "number", min: "1", value: s.interval_minutes })),
          labeled("Data window", windowSelect(id + "-win", s.data_window)),
        ]),
        h("div", { class: "row", style: "margin-top:10px" }, [
          h("button", { class: "btn btn-sm btn-primary", onclick: () => saveAuto(scope, id) }, "Save schedule"),
          h("button", { class: "btn btn-sm", onclick: () => runNow(scope === "global" ? null : scope) }, "Run now"),
          h("span", { class: "muted", html: `next: ${fmtDate(s.next_run_at)}` }),
        ]),
      ]);
      root.appendChild(row);
    });
  }
  function labeled(label, ctl) { return h("label", { class: "field" }, [label, ctl]); }
  function opt(v, t, sel) { const o = h("option", { value: v }, t); if (sel) o.selected = true; return o; }
  function windowSelect(id, sel) {
    const wins = ["now-6h", "now-24h", "now-2d", "now-7d", "now-30d", "now-90d", "now-365d"];
    return h("select", { id }, wins.map((w) => opt(w, w, w === sel)));
  }
  async function saveAuto(scope, id) {
    try {
      await postJSON("/api/automation", {
        scope, enabled: $("#" + id + "-en").value === "true",
        interval_minutes: parseInt($("#" + id + "-int").value, 10) || 60,
        data_window: $("#" + id + "-win").value,
      });
      toast("schedule saved"); initAutomation();
    } catch (e) { toast("save failed: " + e.message); }
  }

  async function initStorage() {
    const ov = await api("/api/storage");
    $("#store-backend").textContent = ov.backend;
    $("#store-total").textContent = ov.total_human;
    $("#store-rows").textContent = ov.total_rows;
    const body = $("#datasets"); body.innerHTML = "";
    ov.datasets.forEach((d) => {
      body.appendChild(h("tr", {}, [
        h("td", { class: "mono" }, d.table),
        h("td", {}, d.record_count),
        h("td", {}, d.size_human),
        h("td", {}, d.added_last_24h == null ? "—" : d.added_last_24h),
        h("td", {}, fmtDate(d.last_modified)),
        h("td", {}, [
          dlBtn(d.table, "csv"), dlBtn(d.table, "json"), dlBtn(d.table, "xlsx"),
        ]),
      ]));
    });
    // tables select for forms
    const tables = ov.datasets.map((d) => d.table);
    ["del-table", "arc-table"].forEach((sid) => {
      const sel = $("#" + sid); if (sel) { sel.innerHTML = ""; tables.forEach((t) => sel.appendChild(opt(t, t))); }
    });
    const arch = await api("/api/storage/archives");
    const ab = $("#archives"); ab.innerHTML = "";
    if (!arch.length) ab.innerHTML = '<tr><td colspan="4" class="empty">no archives</td></tr>';
    arch.forEach((a) => ab.appendChild(h("tr", {}, [
      h("td", { class: "mono" }, a.file), h("td", {}, Math.round(a.size_bytes / 1024) + " KB"),
      h("td", {}, fmtDate(a.modified)),
      h("td", {}, h("button", { class: "btn btn-sm", onclick: () => restore(a.file) }, "Restore")),
    ])));
  }
  function dlBtn(table, fmt) {
    return h("button", { class: "btn btn-sm", style: "margin-right:4px",
      onclick: () => {
        const f = $("#exp-from") && $("#exp-from").value ? `&date_from=${encodeURIComponent($("#exp-from").value)}` : "";
        const t = $("#exp-to") && $("#exp-to").value ? `&date_to=${encodeURIComponent($("#exp-to").value)}` : "";
        window.location = `/api/storage/export?table=${table}&fmt=${fmt}${f}${t}`;
      } }, fmt.toUpperCase());
  }
  async function doDelete() {
    if (!$("#del-confirm").checked) { toast("tick confirm to delete"); return; }
    try {
      const r = await postJSON("/api/storage/delete", {
        table: $("#del-table").value, date_from: $("#del-from").value || null,
        date_to: $("#del-to").value || null, confirm: true,
      });
      toast(`deleted ${r.deleted} rows`); initStorage();
    } catch (e) { toast("delete failed: " + e.message); }
  }
  async function doArchive() {
    try {
      const r = await postJSON("/api/storage/archive", { table: $("#arc-table").value, before: $("#arc-before").value });
      toast(`archived ${r.archived} rows`); initStorage();
    } catch (e) { toast("archive failed: " + e.message); }
  }
  async function restore(file) {
    try { const r = await postJSON("/api/storage/restore", { file }); toast(`restored ${r.restored} rows`); initStorage(); }
    catch (e) { toast("restore failed: " + e.message); }
  }

  async function initLogs() {
    await searchLogs();
  }
  async function searchLogs() {
    const q = $("#log-q").value, level = $("#log-level").value, mod = $("#log-mod").value, since = $("#log-since").value;
    const rows = await api(`/api/logs?q=${encodeURIComponent(q)}&level=${level}&module=${encodeURIComponent(mod)}&since_hours=${since || 0}&limit=300`);
    const body = $("#logs"); body.innerHTML = "";
    if (!rows.length) { body.innerHTML = '<tr><td colspan="5" class="empty">no events</td></tr>'; return; }
    rows.forEach((r) => body.appendChild(h("tr", {}, [
      h("td", {}, fmtDate(r.ts)),
      h("td", { html: `<span class="tier tier-${({INFO:'ok',WARNING:'warn',ERROR:'critical'})[r.level]||'unknown'}">${r.level}</span>` }),
      h("td", {}, r.source),
      h("td", {}, r.event),
      h("td", { class: "wrap mono" }, JSON.stringify(r.detail_json || {}).slice(0, 200)),
    ])));
  }

  async function initSystem() {
    const [health, perf, store, mods] = await Promise.all([
      api("/api/health"), api("/api/performance"), api("/api/storage"), api("/api/modules"),
    ]);
    setText("sys-status", health.status); setText("sys-backend", health.backend);
    setText("sys-modules", mods.length); setText("sys-runs", perf.runs_total);
    setText("sys-failed", perf.runs_failed); setText("sys-triggers", perf.triggers_total);
    setText("sys-avg", perf.avg_trigger_ms + " ms"); setText("sys-last", perf.last_trigger_ms + " ms");
    setText("sys-store", store.total_human + " · " + store.total_rows + " rows");
  }
  function setText(id, v) { const e = $("#" + id); if (e) e.textContent = v; }

  async function initPlugins() {
    const plugins = await api("/api/plugins");
    const body = $("#plugins"); body.innerHTML = "";
    plugins.forEach((p) => body.appendChild(h("tr", {}, [
      h("td", { class: "mono" }, p.name), h("td", {}, p.title), h("td", {}, p.component_type),
      h("td", { html: p.configured ? '<span class="tier tier-ok">yes</span>' : '<span class="tier tier-critical">no</span>' }),
      h("td", {}, `${p.signal_panels}/${p.panel_count}`),
      h("td", {}, fmtDate(p.last_run_at) + (p.last_run_status ? ` (${p.last_run_status})` : "")),
    ])));
    const cat = await api("/api/catalog");
    const cb = $("#catalog"); cb.innerHTML = "";
    if (!cat.length) cb.innerHTML = '<tr><td colspan="6" class="empty">no panels catalogued yet</td></tr>';
    cat.forEach((c) => cb.appendChild(h("tr", {}, [
      h("td", {}, c.module), h("td", {}, c.dashboard_name), h("td", {}, c.panel_title),
      h("td", {}, c.panel_type), h("td", { html: c.is_signal ? "✓" : "" }), h("td", {}, c.role),
    ])));
  }

  function refreshPage() {
    ({ overview: initOverview, triggers: initTriggers, automation: initAutomation,
       storage: initStorage, logs: initLogs, system: initSystem, plugins: initPlugins }[PAGE] || function(){})();
    if (PAGE === "overview" && $("#module-root")) initModule();
    if (PAGE === "overview" && analyticsLoaded) initAnalytics();  // refresh charts after a run
  }

  // ---- boot --------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const rb = $("#run-all"); if (rb) rb.addEventListener("click", () => runNow(null));
    window.PdM = { runNow, searchLogs, doDelete, doArchive };
    // Overview tabs (Module Health / Graphical Overview)
    $$(".tab").forEach((t) => t.addEventListener("click", () => activateTab(t.dataset.tab)));
    // Window control re-scopes the analytics charts when they are showing.
    const wsel = $("#global-window");
    if (wsel) wsel.addEventListener("change", () => { if (analyticsLoaded) initAnalytics(); });
    // Re-render charts on resize (redraw from cached data, no refetch).
    let rz; window.addEventListener("resize", () => {
      clearTimeout(rz);
      rz = setTimeout(() => {
        const gp = $("#tab-graphs");
        if (analyticsLoaded && lastAnalytics && gp && gp.classList.contains("active")) renderAnalytics(lastAnalytics);
      }, 200);
    });
    if ($("#module-root")) initModule();
    else refreshPage();
  });
})();
