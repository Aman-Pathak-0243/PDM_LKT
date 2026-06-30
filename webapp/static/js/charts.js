/* Minimal dependency-free SVG charts (offline, LAN-safe — no CDN). */
(function () {
  const NS = "http://www.w3.org/2000/svg";

  function tierColor(t) {
    return ({ ok: "#4ade80", watch: "#fbbf24", warn: "#fb923c", critical: "#ff6b6f" })[t] || "#5a6878";
  }

  // points: [{t: ISOstring, v: number, tier?:string}]
  function line(container, points, opts) {
    opts = opts || {};
    const w = opts.width || container.clientWidth || 600;
    const h = opts.height || 160;
    const pad = { l: 34, r: 10, t: 12, b: 20 };
    container.innerHTML = "";
    if (!points || points.length === 0) {
      container.innerHTML = '<div class="empty">no history yet — runs accumulate trend over time</div>';
      return;
    }
    const xs = points.map((p, i) => i);
    const ys = points.map((p) => p.v);
    const yMin = opts.yMin != null ? opts.yMin : Math.min(...ys, 0);
    const yMax = opts.yMax != null ? opts.yMax : Math.max(...ys, 100);
    const X = (i) => pad.l + (xs.length === 1 ? 0 : (i / (xs.length - 1)) * (w - pad.l - pad.r));
    const Y = (v) => pad.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (h - pad.t - pad.b);

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", h);

    // gridlines + y labels
    [yMin, (yMin + yMax) / 2, yMax].forEach((val) => {
      const y = Y(val);
      const ln = document.createElementNS(NS, "line");
      ln.setAttribute("x1", pad.l); ln.setAttribute("x2", w - pad.r);
      ln.setAttribute("y1", y); ln.setAttribute("y2", y);
      ln.setAttribute("stroke", "#2a3340"); ln.setAttribute("stroke-width", "1");
      svg.appendChild(ln);
      const tx = document.createElementNS(NS, "text");
      tx.setAttribute("x", 4); tx.setAttribute("y", y + 3);
      tx.setAttribute("fill", "#8b99a8"); tx.setAttribute("font-size", "9");
      tx.textContent = Math.round(val);
      svg.appendChild(tx);
    });

    const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${X(i)},${Y(p.v)}`).join(" ");
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", opts.color || "#4f9cf9");
    path.setAttribute("stroke-width", "2");
    svg.appendChild(path);

    points.forEach((p, i) => {
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", X(i)); c.setAttribute("cy", Y(p.v)); c.setAttribute("r", "2.6");
      c.setAttribute("fill", p.tier ? tierColor(p.tier) : (opts.color || "#4f9cf9"));
      const title = document.createElementNS(NS, "title");
      title.textContent = `${p.t || i}: ${p.v}`;
      c.appendChild(title);
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
    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><path d="${d}" fill="none" stroke="${color || "#4f9cf9"}" stroke-width="1.5"/></svg>`;
  }

  window.Charts = { line, sparkSVG, tierColor };
})();
