/* Minimal dependency-free SVG charts (offline, LAN-safe — no CDN).
 *
 * Design follows the project's status palette: tier colours mean state
 * (ok/watch/warn/critical), never identity, and are always paired with a label
 * or legend so meaning is never colour-alone. Marks are thin, data-ends are
 * rounded, fills are separated by a 2px surface gap, grid/axes are hairlines one
 * shade off the surface, and every mark carries a hover tooltip. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const INK = "#e6edf3", MUTED = "#8b99a8", GRID = "#2a3340", TRACK = "#232c38";
  const ACCENT = "#4f9cf9";

  function tierColor(t) {
    return ({ ok: "#4ade80", watch: "#fbbf24", warn: "#fb923c", critical: "#ff6b6f" })[t] || "#5a6878";
  }

  // ---- tiny SVG builders -------------------------------------------------- //
  function el(name, attrs, children) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs || {}) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    (children || []).forEach((c) => e.appendChild(c));
    return e;
  }
  function tip(node, text) {
    const t = document.createElementNS(NS, "title");
    t.textContent = text;
    node.appendChild(t);
    return node;
  }
  function txt(x, y, s, attrs) {
    const t = el("text", Object.assign({ x, y, fill: MUTED, "font-size": 10 }, attrs || {}));
    t.textContent = s;
    return t;
  }
  const cw = (c, fb) => c.clientWidth || fb || 600;

  // ---- line (used by per-component trend on module pages) ----------------- //
  function line(container, points, opts) {
    opts = opts || {};
    const w = opts.width || cw(container, 600);
    const h = opts.height || 160;
    const pad = { l: 34, r: 10, t: 12, b: 20 };
    container.innerHTML = "";
    if (!points || points.length === 0) {
      container.innerHTML = '<div class="empty">no history yet — runs accumulate trend over time</div>';
      return;
    }
    const ys = points.map((p) => p.v);
    const yMin = opts.yMin != null ? opts.yMin : Math.min(...ys, 0);
    const yMax = opts.yMax != null ? opts.yMax : Math.max(...ys, 100);
    const X = (i) => pad.l + (points.length === 1 ? 0 : (i / (points.length - 1)) * (w - pad.l - pad.r));
    const Y = (v) => pad.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (h - pad.t - pad.b);
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%", height: h });
    [yMin, (yMin + yMax) / 2, yMax].forEach((val) => {
      const y = Y(val);
      svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: y, y2: y, stroke: GRID, "stroke-width": 1 }));
      svg.appendChild(txt(4, y + 3, Math.round(val), { "font-size": 9 }));
    });
    const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${X(i)},${Y(p.v)}`).join(" ");
    svg.appendChild(el("path", { d, fill: "none", stroke: opts.color || ACCENT, "stroke-width": 2, "stroke-linejoin": "round" }));
    points.forEach((p, i) => {
      const c = el("circle", { cx: X(i), cy: Y(p.v), r: 2.6, fill: p.tier ? tierColor(p.tier) : (opts.color || ACCENT) });
      tip(c, `${p.t || i}: ${p.v}`);
      svg.appendChild(c);
    });
    container.appendChild(svg);
  }

  function sparkSVG(values, width, height, color) {
    width = width || 90; height = height || 22;
    if (!values || !values.length) return "";
    const min = Math.min(...values), max = Math.max(...values);
    const X = (i) => (values.length === 1 ? 0 : (i / (values.length - 1)) * width);
    const Y = (v) => height - ((v - min) / (max - min || 1)) * height;
    const d = values.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><path d="${d}" fill="none" stroke="${color || ACCENT}" stroke-width="1.5"/></svg>`;
  }

  // ---- area (fleet trend): line + gradient fill + crosshair tooltip ------- //
  let _gid = 0;
  function area(container, points, opts) {
    opts = opts || {};
    const w = cw(container, 640);
    const h = opts.height || 200;
    const pad = { l: 36, r: 14, t: 14, b: 26 };
    container.innerHTML = "";
    container.style.position = "relative";
    if (!points || !points.length) {
      container.innerHTML = '<div class="empty">no history yet — each PdM run adds a point; the fleet trend builds over time</div>';
      return;
    }
    const color = opts.color || ACCENT;
    const n = points.length;
    // Auto-scale the y-domain to the data (padded, snapped to 5s, clamped 0–100)
    // so small movements in a high, tight range still read as a real trend rather
    // than a flat line pinned to the top of a fixed 0–100 axis.
    const vals = points.map((p) => p.v);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (!isFinite(lo)) { lo = 0; hi = 100; }
    const padv = Math.max(4, (hi - lo) * 0.5);
    let yMin = opts.yMin != null ? opts.yMin : Math.max(0, Math.floor((lo - padv) / 5) * 5);
    let yMax = opts.yMax != null ? opts.yMax : Math.min(100, Math.ceil((hi + padv) / 5) * 5);
    if (yMax - yMin < 5) { yMin = Math.max(0, yMin - 5); yMax = Math.min(100, yMax + 5); }
    const X = (i) => pad.l + (n === 1 ? (w - pad.l - pad.r) / 2 : (i / (n - 1)) * (w - pad.l - pad.r));
    const Y = (v) => pad.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (h - pad.t - pad.b);
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%", height: h });
    const gid = "grad" + _gid++;
    const defs = el("defs", {}, [
      el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, [
        el("stop", { offset: "0%", "stop-color": color, "stop-opacity": 0.35 }),
        el("stop", { offset: "100%", "stop-color": color, "stop-opacity": 0.02 }),
      ]),
    ]);
    svg.appendChild(defs);
    // evenly-spaced gridlines across the scaled domain
    [yMin, (yMin + yMax) / 2, yMax].forEach((v) => {
      const y = Y(v);
      svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: y, y2: y, stroke: GRID, "stroke-width": 1 }));
      svg.appendChild(txt(4, y + 3, Math.round(v), { "font-size": 9 }));
    });
    // tier threshold markers, only where they fall inside the visible domain
    [{ v: 85, t: "ok" }, { v: 65, t: "watch" }, { v: 40, t: "warn" }].forEach((b) => {
      if (b.v <= yMin + 0.5 || b.v >= yMax - 0.5) return;
      const y = Y(b.v);
      svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: y, y2: y, stroke: tierColor(b.t), "stroke-width": 1, "stroke-opacity": 0.28 }));
      svg.appendChild(txt(w - pad.r - 2, y - 3, b.t, { "text-anchor": "end", "font-size": 8, fill: tierColor(b.t), "fill-opacity": 0.8 }));
    });
    const lineD = points.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ");
    const areaD = `${lineD} L${X(n - 1).toFixed(1)},${Y(yMin)} L${X(0).toFixed(1)},${Y(yMin)} Z`;
    svg.appendChild(el("path", { d: areaD, fill: `url(#${gid})`, stroke: "none" }));
    svg.appendChild(el("path", { d: lineD, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    if (n === 1) svg.appendChild(el("circle", { cx: X(0), cy: Y(points[0].v), r: 3.4, fill: color }));
    // crosshair + focus dot + HTML tooltip
    const cross = el("line", { x1: 0, x2: 0, y1: pad.t, y2: h - pad.b, stroke: color, "stroke-width": 1, "stroke-opacity": 0.5, visibility: "hidden" });
    const dot = el("circle", { r: 4, fill: color, stroke: "#0f1419", "stroke-width": 2, visibility: "hidden" });
    svg.appendChild(cross); svg.appendChild(dot);
    const tt = document.createElement("div");
    tt.className = "chart-tip"; tt.style.display = "none";
    container.appendChild(svg); container.appendChild(tt);
    const hit = el("rect", { x: pad.l, y: pad.t, width: w - pad.l - pad.r, height: h - pad.t - pad.b, fill: "transparent" });
    svg.appendChild(hit);
    function move(ev) {
      const box = svg.getBoundingClientRect();
      const px = ((ev.clientX - box.left) / box.width) * w;
      let idx = 0, best = Infinity;
      points.forEach((p, i) => { const dx = Math.abs(X(i) - px); if (dx < best) { best = dx; idx = i; } });
      const p = points[idx];
      cross.setAttribute("x1", X(idx)); cross.setAttribute("x2", X(idx)); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", X(idx)); dot.setAttribute("cy", Y(p.v)); dot.setAttribute("visibility", "visible");
      tt.style.display = "block";
      tt.innerHTML = `<strong>${p.v}</strong> avg health<br><span class="muted">${p.t}${p.n ? " · " + p.n + " comps" : ""}</span>`;
      const left = Math.min(Math.max((X(idx) / w) * box.width + 12, 8), box.width - 130);
      tt.style.left = left + "px"; tt.style.top = "8px";
    }
    hit.addEventListener("mousemove", move);
    hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tt.style.display = "none"; });
    container.appendChild(svg);
  }

  // ---- donut (part-to-whole, ≤6 segments) + center KPI -------------------- //
  function donut(container, segments, opts) {
    opts = opts || {};
    const size = opts.size || Math.min(cw(container, 220), 240);
    const sw = opts.stroke || 24;
    const cx = size / 2, cy = size / 2, r = size / 2 - sw / 2 - 2;
    const C = 2 * Math.PI * r;
    const total = segments.reduce((a, s) => a + (s.value || 0), 0);
    container.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, class: "donut-svg" });
    svg.appendChild(el("circle", { cx, cy, r, fill: "none", stroke: TRACK, "stroke-width": sw }));
    if (total > 0) {
      let acc = 0;
      const gap = C * 0.008;
      segments.forEach((s) => {
        if (!s.value) return;
        const segLen = (s.value / total) * C;
        const draw = Math.max(0.5, segLen - gap);
        const c = el("circle", {
          cx, cy, r, fill: "none", stroke: s.color, "stroke-width": sw,
          "stroke-dasharray": `${draw} ${C - draw}`, "stroke-dashoffset": -acc,
          transform: `rotate(-90 ${cx} ${cy})`,
        });
        tip(c, `${s.label}: ${s.value} (${Math.round((s.value / total) * 100)}%)`);
        svg.appendChild(c);
        acc += segLen;
      });
    }
    const ctr = opts.center || {};
    svg.appendChild(txt(cx, cy - 2, ctr.value != null ? ctr.value : total, { fill: INK, "font-size": Math.round(size / 6.5), "font-weight": 700, "text-anchor": "middle" }));
    if (ctr.label) svg.appendChild(txt(cx, cy + Math.round(size / 9), ctr.label, { "text-anchor": "middle", "font-size": 10 }));
    container.appendChild(svg);
  }

  // ---- vertical bars (histogram / TTM buckets) --------------------------- //
  function bars(container, items, opts) {
    opts = opts || {};
    const w = cw(container, 480);
    const h = opts.height || 180;
    const pad = { l: 30, r: 10, t: 12, b: 30 };
    container.innerHTML = "";
    const max = Math.max(1, ...items.map((d) => d.value || 0));
    const bw = (w - pad.l - pad.r) / items.length;
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%", height: h });
    const plotH = h - pad.t - pad.b;
    [0, max / 2, max].forEach((val) => {
      const y = pad.t + (1 - val / max) * plotH;
      svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: y, y2: y, stroke: GRID, "stroke-width": 1 }));
      svg.appendChild(txt(4, y + 3, Math.round(val), { "font-size": 9 }));
    });
    items.forEach((d, i) => {
      const val = d.value || 0;
      const bh = (val / max) * plotH;
      const x = pad.l + i * bw + 3;
      const y = pad.t + plotH - bh;
      const bar = el("rect", { x, y, width: Math.max(1, bw - 6), height: Math.max(val > 0 ? 2 : 0, bh), rx: 3, fill: d.color || ACCENT });
      tip(bar, `${d.tipLabel || d.label}: ${val}`);
      svg.appendChild(bar);
      if (val > 0) svg.appendChild(txt(x + (bw - 6) / 2, y - 4, val, { "text-anchor": "middle", fill: INK, "font-size": 10 }));
      svg.appendChild(txt(x + (bw - 6) / 2, h - pad.b + 13, d.label, { "text-anchor": "middle", "font-size": 9 }));
    });
    container.appendChild(svg);
  }

  // ---- horizontal ranked bars (top at-risk) ------------------------------ //
  function barsH(container, items, opts) {
    opts = opts || {};
    container.innerHTML = "";
    if (!items.length) { container.innerHTML = '<div class="empty">no flagged components — fleet is healthy</div>'; return; }
    const w = cw(container, 520);
    const rowH = opts.rowH || 26;
    const h = items.length * rowH + 8;
    const labelW = opts.labelW || Math.min(210, w * 0.42);
    const pad = { l: labelW, r: 44, t: 4 };
    const max = opts.max != null ? opts.max : Math.max(1, ...items.map((d) => d.value || 0));
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%", height: h });
    const trackW = w - pad.l - pad.r;
    items.forEach((d, i) => {
      const y = pad.t + i * rowH;
      const val = d.value || 0;
      const bw = Math.max(2, (val / max) * trackW);
      svg.appendChild(el("rect", { x: pad.l, y: y + 4, width: trackW, height: rowH - 12, rx: 4, fill: TRACK }));
      const bar = el("rect", { x: pad.l, y: y + 4, width: bw, height: rowH - 12, rx: 4, fill: d.color || ACCENT });
      tip(bar, `${d.label}: ${val}${d.sub ? " · " + d.sub : ""}`);
      svg.appendChild(bar);
      const lbl = txt(pad.l - 8, y + rowH / 2 + 3, d.label, { "text-anchor": "end", fill: INK, "font-size": 11 });
      tip(lbl, d.label);
      svg.appendChild(lbl);
      svg.appendChild(txt(pad.l + bw + 6, y + rowH / 2 + 3, d.valueLabel != null ? d.valueLabel : val, { fill: MUTED, "font-size": 10 }));
    });
    container.appendChild(svg);
  }

  // ---- horizontal stacked bars (per-module tier breakdown) --------------- //
  function stackedBarH(container, rows, opts) {
    opts = opts || {};
    container.innerHTML = "";
    if (!rows.length) { container.innerHTML = '<div class="empty">no modules scored yet</div>'; return; }
    const w = cw(container, 520);
    const rowH = opts.rowH || 30;
    const h = rows.length * rowH + 6;
    const labelW = opts.labelW || Math.min(150, w * 0.3);
    const pad = { l: labelW, r: 40, t: 3 };
    const max = Math.max(1, ...rows.map((r) => r.segments.reduce((a, s) => a + (s.value || 0), 0)));
    const trackW = w - pad.l - pad.r;
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%", height: h });
    rows.forEach((r, i) => {
      const y = pad.t + i * rowH;
      const total = r.segments.reduce((a, s) => a + (s.value || 0), 0);
      svg.appendChild(el("rect", { x: pad.l, y: y + 5, width: trackW, height: rowH - 14, rx: 4, fill: TRACK }));
      let x = pad.l;
      const gap = 1.5;
      r.segments.forEach((s) => {
        if (!s.value) return;
        const sw = (s.value / max) * trackW;
        const seg = el("rect", { x, y: y + 5, width: Math.max(1, sw - gap), height: rowH - 14, rx: 2, fill: s.color });
        tip(seg, `${r.label} · ${s.key}: ${s.value}`);
        svg.appendChild(seg);
        x += sw;
      });
      const lbl = txt(pad.l - 8, y + rowH / 2 + 3, r.label, { "text-anchor": "end", fill: INK, "font-size": 11 });
      tip(lbl, r.sub || r.label);
      svg.appendChild(lbl);
      svg.appendChild(txt(pad.l + (total / max) * trackW + 6, y + rowH / 2 + 3, total, { fill: MUTED, "font-size": 10 }));
    });
    container.appendChild(svg);
  }

  // ---- heatmap (aisle × module risk grid) -------------------------------- //
  function heatmap(container, model, opts) {
    opts = opts || {};
    container.innerHTML = "";
    const { rows, cols, cell } = model; // rows: [{key,label}], cols: [{key,label}], cell(rowKey,colKey)->{color,tip}|null
    if (!rows.length || !cols.length) { container.innerHTML = '<div class="empty">no aisle-mapped components yet</div>'; return; }
    const w = cw(container, 560);
    const labelW = opts.labelW || 92;
    const headH = opts.headH || 58;
    const gap = 4;
    const cellW = (w - labelW) / cols.length;
    const cellH = opts.cellH || 30;
    const h = headH + rows.length * (cellH + gap);
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%", height: h });
    cols.forEach((c, j) => {
      const x = labelW + j * cellW + cellW / 2;
      const t = txt(x, headH - 8, c.label, { "text-anchor": "end", "font-size": 10, transform: `rotate(-40 ${x} ${headH - 8})` });
      svg.appendChild(t);
    });
    rows.forEach((r, i) => {
      const y = headH + i * (cellH + gap);
      svg.appendChild(txt(labelW - 8, y + cellH / 2 + 3, r.label, { "text-anchor": "end", fill: INK, "font-size": 11 }));
      cols.forEach((c, j) => {
        const x = labelW + j * cellW + 2;
        const cd = cell(r.key, c.key);
        const rect = el("rect", { x, y, width: cellW - 4, height: cellH, rx: 4, fill: cd ? cd.color : "#141a22", stroke: cd ? "none" : GRID, "stroke-width": cd ? 0 : 1 });
        tip(rect, cd ? cd.tip : `${r.label} · ${c.label}: no data`);
        svg.appendChild(rect);
        if (cd && cd.text) svg.appendChild(txt(x + (cellW - 4) / 2, y + cellH / 2 + 3, cd.text, { "text-anchor": "middle", fill: "#0f1419", "font-size": 10, "font-weight": 700 }));
      });
    });
    container.appendChild(svg);
  }

  // ---- legend helper (HTML) ---------------------------------------------- //
  function legend(container, items) {
    container.innerHTML = items
      .map((i) => `<span class="lg"><span class="lg-sw" style="background:${i.color}"></span>${i.label}${i.value != null ? ` <b>${i.value}</b>` : ""}</span>`)
      .join("");
  }

  window.Charts = { line, sparkSVG, area, donut, bars, barsH, stackedBarH, heatmap, legend, tierColor };
})();
