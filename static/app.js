const el = (id) => document.getElementById(id);
const plotDiv = el("plot");

const AXIS = {
  pressure: { x: "x2", y: "y", y2: "y2" },
  weight: { x: "x3", y: "y3", y2: "y4" },
  depth: { x: "x4", y: "y5", y2: "y5" },
  speed: { x: "x", y: "y6", y2: "y6" },
};

function commentLineColor() {
  return isDark() ? "rgba(168,176,192,0.28)" : "rgba(92,102,120,0.22)";
}
const COMMENT_AXES = [
  { xref: "x2", yref: "y domain" },
  { xref: "x3", yref: "y3 domain" },
  { xref: "x4", yref: "y5 domain" },
  { xref: "x", yref: "y6 domain" },
];
const PANEL_YAXES = ["yaxis", "yaxis3", "yaxis5", "yaxis6"];
const OVERVIEW_RATIO = 0.85;
const LOD_DEBOUNCE_MS = 280;
const CACHE_MAX = 20;
const COMMENT_HOVER_PX = 5;

let catalog = [];
let visibility = {};
let timeRange = { t0: null, t1: null };
let fullRange = { t0: null, t1: null };
let fetching = false;
let applyingPlot = false;
let lodTimer = null;
let currentCacheKey = null;
let plotCache = new Map();
let hoverComments = [];
let lastTipKey = "";
let fetchSeq = 0;
let plotEventsBound = false;
let ignoreRelayoutUntil = 0;
let wheelTimer = null;
let busyTimer = null;
let busyShown = 0;
let busyTarget = 0;

function setStatus(msg, err = false) {
  const box = el("status");
  box.textContent = msg;
  box.classList.toggle("err", err);
}

function paintBusy() {
  const bar = el("loadOverlayBar");
  const pct = el("loadOverlayPct");
  const overlay = el("loadOverlay");
  if (!bar || overlay.hidden) return;
  if (overlay.classList.contains("indeterminate")) return;
  if (busyShown < busyTarget) {
    busyShown += Math.max(0.35, (busyTarget - busyShown) * 0.18);
    if (busyShown > busyTarget) busyShown = busyTarget;
  } else if (busyShown < 92 && busyTarget < 100) {
    busyShown += 0.07;
  }
  bar.style.width = `${busyShown}%`;
  pct.textContent = `${Math.round(busyShown)}%`;
  overlay.querySelector(".load-bar")?.setAttribute("aria-valuenow", String(Math.round(busyShown)));
}

function showBusy(title, msg, indeterminate = false) {
  const overlay = el("loadOverlay");
  overlay.hidden = false;
  overlay.classList.toggle("indeterminate", indeterminate);
  el("loadOverlayTitle").textContent = title;
  el("loadOverlayMsg").textContent = msg || "";
  busyShown = indeterminate ? 0 : 3;
  busyTarget = indeterminate ? 0 : 6;
  el("loadOverlayBar").style.width = indeterminate ? "38%" : `${busyShown}%`;
  el("loadOverlayPct").textContent = "0%";
  if (busyTimer) clearInterval(busyTimer);
  busyTimer = setInterval(paintBusy, 80);
}

function setBusyProgress(pct, msg) {
  if (msg) el("loadOverlayMsg").textContent = msg;
  const overlay = el("loadOverlay");
  overlay.classList.remove("indeterminate");
  busyTarget = Math.max(busyTarget, Math.max(0, Math.min(100, Number(pct) || 0)));
}

function hideBusy() {
  const overlay = el("loadOverlay");
  overlay.classList.remove("indeterminate");
  busyTarget = 100;
  busyShown = 100;
  paintBusy();
  if (busyTimer) {
    clearInterval(busyTimer);
    busyTimer = null;
  }
  setTimeout(() => {
    overlay.hidden = true;
  }, 180);
}

function startProgressPoll() {
  let on = true;
  const tick = async () => {
    if (!on) return;
    try {
      const res = await fetch("/api/progress", { cache: "no-store" });
      if (!res.ok) return;
      const st = await res.json();
      if (st.pct != null) setBusyProgress(st.pct, st.msg);
      if (st.msg) setStatus(st.msg);
    } catch (err) {}
  };
  tick();
  const id = setInterval(tick, 300);
  return () => {
    on = false;
    clearInterval(id);
  };
}

function fmtSize(n) {
  if (n > 1e9) return (n / 1e9).toFixed(1) + " GB";
  if (n > 1e6) return (n / 1e6).toFixed(1) + " MB";
  if (n > 1e3) return (n / 1e3).toFixed(0) + " KB";
  return n + " B";
}

function fmtN(n) {
  return Number(n || 0).toLocaleString();
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function checkedPaths(containerId) {
  return [...document.querySelectorAll(`#${containerId} input[type=checkbox]:checked`)].map(
    (n) => n.value
  );
}

function renderFileList(nodeId, files, emptyText) {
  const node = el(nodeId);
  if (!files.length) {
    node.classList.add("muted");
    node.textContent = emptyText;
    return;
  }
  node.classList.remove("muted");
  node.innerHTML = files
    .map(
      (f) => `<label>
        <input type="checkbox" value="${f.path.replace(/"/g, "&quot;")}" checked />
        <span>${f.rel}<br /><small>${fmtSize(f.size)}</small></span>
      </label>`
    )
    .join("");
}

function renderSeries() {
  const node = el("seriesList");
  if (!catalog.length) {
    node.classList.add("muted");
    node.textContent = "Load data to choose traces";
    return;
  }
  node.classList.remove("muted");
  const groups = {};
  for (const s of catalog) {
    (groups[s.panel] ||= []).push(s);
    if (visibility[s.id] === undefined) visibility[s.id] = s.default_on !== false;
  }
  const titles = {
    pressure: "Pressure & flow",
    weight: "Weight & tension",
    depth: "Depth",
    speed: "Speed",
  };
  node.innerHTML = Object.keys(titles)
    .filter((p) => groups[p])
    .map((p) => {
      const rows = groups[p]
        .map(
          (s) => `<label>
            <span class="dot" style="background:${s.color}"></span>
            <input type="checkbox" data-sid="${s.id}" ${visibility[s.id] ? "checked" : ""} />
            <span>${s.label} <small>${fmtN(s.n)} pts</small></span>
          </label>`
        )
        .join("");
      return `<div class="panel-head">${titles[p]}</div>${rows}`;
    })
    .join("");
  node.querySelectorAll("input[data-sid]").forEach((input) => {
    input.addEventListener("change", () => {
      visibility[input.dataset.sid] = input.checked;
      const data = currentCacheKey ? plotCache.get(currentCacheKey) : null;
      if (data && tracesCoverCatalog(data)) drawPlot(data);
      else {
        clearPlotCache();
        showLod(timeRange, true);
      }
    });
  });
}

function isDark() {
  return !document.documentElement.classList.contains("light");
}

function theme() {
  return isDark()
    ? {
        bg: "#11151c",
        paper: "#0b0d12",
        grid: "#2a3140",
        text: "#e6e8ee",
        muted: "#9aa3b5",
        ticks: "#c5c9d4",
      }
    : {
        bg: "#ffffff",
        paper: "#f3f4f6",
        grid: "#8b929e",
        text: "#1c212b",
        muted: "#3e4654",
        ticks: "#2a3038",
      };
}

function axisLayout(t) {
  const spike = {
    showspikes: true,
    spikemode: "across+toaxis",
    spikethickness: 1,
    spikecolor: t.muted,
    spikedash: "solid",
    type: "date",
    gridcolor: t.grid,
    color: t.ticks,
    tickcolor: t.ticks,
    tickfont: { color: t.ticks },
    zeroline: false,
    uirevision: "keep-x",
  };
  return {
    xaxis: { ...spike, domain: [0.0, 1], anchor: "y6", title: "Time" },
    xaxis2: { ...spike, domain: [0.0, 1], anchor: "y", matches: "x", showticklabels: false, title: "" },
    xaxis3: { ...spike, domain: [0.0, 1], anchor: "y3", matches: "x", showticklabels: false, title: "" },
    xaxis4: { ...spike, domain: [0.0, 1], anchor: "y5", matches: "x", showticklabels: false, title: "" },
    yaxis: { domain: [0.785, 1.0], title: "psi", gridcolor: t.grid, color: t.ticks, tickcolor: t.ticks, tickfont: { color: t.ticks }, zeroline: false, side: "left" },
    yaxis2: {
      domain: [0.785, 1.0],
      title: "bpm",
      overlaying: "y",
      side: "right",
      gridcolor: t.grid,
      color: t.ticks,
      tickcolor: t.ticks,
      tickfont: { color: t.ticks },
      zeroline: false,
      showgrid: false,
    },
    yaxis3: { domain: [0.53, 0.745], title: "lbf", gridcolor: t.grid, color: t.ticks, tickcolor: t.ticks, tickfont: { color: t.ticks }, zeroline: false },
    yaxis4: {
      domain: [0.53, 0.745],
      title: "tension lbf",
      overlaying: "y3",
      side: "right",
      showgrid: false,
      color: t.ticks,
      tickcolor: t.ticks,
      tickfont: { color: t.ticks },
      zeroline: false,
    },
    yaxis5: { domain: [0.275, 0.49], title: "ft", gridcolor: t.grid, color: t.ticks, tickcolor: t.ticks, tickfont: { color: t.ticks }, zeroline: false, autorange: "reversed" },
    yaxis6: { domain: [0.0, 0.235], title: "ft/min", gridcolor: t.grid, color: t.ticks, tickcolor: t.ticks, tickfont: { color: t.ticks }, zeroline: false },
    annotations: [
      { text: "Pressure & Flow", x: 0, y: 1.0, xref: "paper", yref: "paper", xanchor: "left", yanchor: "bottom", showarrow: false, font: { color: t.text, size: 13 } },
      { text: "Weight & Tension", x: 0, y: 0.745, xref: "paper", yref: "paper", xanchor: "left", yanchor: "bottom", showarrow: false, font: { color: t.text, size: 13 } },
      { text: "Depth", x: 0, y: 0.49, xref: "paper", yref: "paper", xanchor: "left", yanchor: "bottom", showarrow: false, font: { color: t.text, size: 13 } },
      { text: "Speed", x: 0, y: 0.235, xref: "paper", yref: "paper", xanchor: "left", yanchor: "bottom", showarrow: false, font: { color: t.text, size: 13 } },
    ],
  };
}

function tracesCoverCatalog(data) {
  const have = new Set((data.traces || []).map((t) => t.id));
  return catalog.length > 0 && catalog.every((s) => have.has(s.id));
}

function nPoints() {
  return Number(el("nPoints").value);
}

function cacheIdentity() {
  return `${nPoints()}|${el("showEvents").checked}`;
}

function overviewKey() {
  return `overview|${cacheIdentity()}`;
}

function clearPlotCache() {
  plotCache = new Map();
  currentCacheKey = null;
}

function cacheGet(key) {
  if (!plotCache.has(key)) return null;
  const val = plotCache.get(key);
  plotCache.delete(key);
  plotCache.set(key, val);
  return val;
}

function cachePut(key, data) {
  if (plotCache.has(key)) plotCache.delete(key);
  plotCache.set(key, data);
  const keep = overviewKey();
  while (plotCache.size > CACHE_MAX) {
    let dropped = false;
    for (const k of plotCache.keys()) {
      if (k !== keep && k !== key) {
        plotCache.delete(k);
        dropped = true;
        break;
      }
    }
    if (!dropped) break;
  }
}

function lodRequest(t0, t1) {
  const id = cacheIdentity();
  if (!Number.isFinite(t0) || !Number.isFinite(t1) || fullRange.t0 == null || fullRange.t1 == null) {
    return { t0: null, t1: null, key: `overview|${id}`, overview: true, level: 0 };
  }
  const vis = Math.max(t1 - t0, 1);
  const fs = Math.max(fullRange.t1 - fullRange.t0, 1);
  if (vis / fs >= OVERVIEW_RATIO) {
    return { t0: null, t1: null, key: `overview|${id}`, overview: true, level: 0 };
  }
  const level = Math.max(1, Math.min(10, Math.round(Math.log2(fs / vis))));
  const cell = fs / 2 ** level;
  const q0 = Math.max(fullRange.t0, Math.floor(t0 / cell) * cell);
  const q1 = Math.min(fullRange.t1, Math.ceil(t1 / cell) * cell);
  return { t0: q0, t1: q1, key: `L${level}|${q0}|${q1}|${id}`, overview: false, level };
}

function commentLabel(c) {
  const src = c.source === "daq" ? "DAQ" : c.source === "redhawk" ? "RedHawk" : "DAQ event";
  return { src, text: c.text };
}

function hideCommentTip() {
  const tip = el("commentTip");
  tip.hidden = true;
  lastTipKey = "";
}

function showCommentTip(items, clientX, clientY) {
  const tip = el("commentTip");
  const key = items.map((c) => `${c.t}|${c.text}`).join("||");
  if (key !== lastTipKey) {
    lastTipKey = key;
    tip.innerHTML = items
      .map((c) => {
        const { src, text } = commentLabel(c);
        return `<div class="item"><div class="src">${escapeHtml(src)}</div><div>${escapeHtml(text)}</div></div>`;
      })
      .join("");
  }
  tip.hidden = false;
  const pad = 14;
  let x = clientX + pad;
  let y = clientY + pad;
  const w = tip.offsetWidth || 280;
  const h = tip.offsetHeight || 60;
  if (x + w > window.innerWidth - 8) x = clientX - w - pad;
  if (y + h > window.innerHeight - 8) y = clientY - h - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}

function xMsFromPointer(evt) {
  const layout = plotDiv._fullLayout;
  if (!layout) return null;
  const xa = layout.xaxis || layout.xaxis2;
  if (!xa || xa._offset == null) return null;
  const bb = plotDiv.getBoundingClientRect();
  const px = evt.clientX - bb.left - xa._offset;
  if (px < -COMMENT_HOVER_PX || px > xa._length + COMMENT_HOVER_PX) return null;
  const py = evt.clientY - bb.top;
  const inPanel = PANEL_YAXES.some((name) => {
    const ya = layout[name];
    return ya && py >= ya._offset && py <= ya._offset + ya._length;
  });
  if (!inPanel) return null;
  const d = xa.p2d(Math.max(0, Math.min(xa._length, px)));
  let ms;
  if (typeof d === "number") ms = d < 1e12 ? d * 1000 : d;
  else if (d instanceof Date) ms = d.getTime();
  else ms = Date.parse(d);
  return Number.isFinite(ms) ? { ms, xaxis: xa } : null;
}

function commentsNearPointer(evt) {
  if (!el("showComments").checked || !hoverComments.length) return [];
  const hit = xMsFromPointer(evt);
  if (!hit) return [];
  const xa = hit.xaxis;
  const vis0 = timeRange.t0 != null ? timeRange.t0 : fullRange.t0;
  const vis1 = timeRange.t1 != null ? timeRange.t1 : fullRange.t1;
  const span = Math.max((vis1 || 1) - (vis0 || 0), 1);
  const thresh = (span / Math.max(xa._length, 1)) * COMMENT_HOVER_PX;
  return hoverComments.filter((c) => Math.abs(c.t - hit.ms) <= thresh).slice(0, 4);
}

function onPlotPointer(evt) {
  const nearby = commentsNearPointer(evt);
  if (!nearby.length) {
    hideCommentTip();
    return;
  }
  showCommentTip(nearby, evt.clientX, evt.clientY);
}

async function fetchPlotPayload(t0, t1) {
  const res = await fetch("/api/plot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      t0,
      t1,
      n_points: nPoints(),
      series_ids: catalog.map((s) => s.id),
      include_events: el("showEvents").checked,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function showLod(range, immediate) {
  if (!catalog.length) return;
  const lod = lodRequest(range.t0, range.t1);
  if (lod.key === currentCacheKey && plotCache.has(lod.key)) return;
  const cached = cacheGet(lod.key);
  if (cached) {
    currentCacheKey = lod.key;
    drawPlot(cached);
    return;
  }
  if (lod.overview) {
    const ov = cacheGet(overviewKey());
    if (ov) {
      currentCacheKey = overviewKey();
      drawPlot(ov);
      return;
    }
  }
  const run = async () => {
    if (plotCache.has(lod.key)) {
      currentCacheKey = lod.key;
      drawPlot(cacheGet(lod.key));
      return;
    }
    const seq = ++fetchSeq;
    fetching = true;
    try {
      const data = await fetchPlotPayload(lod.t0, lod.t1);
      cachePut(lod.key, data);
      if (lod.overview) hoverComments = data.comments.slice();
      else {
        const seen = new Set(hoverComments.map((c) => `${c.t}|${c.source}|${c.text}`));
        for (const c of data.comments) {
          const k = `${c.t}|${c.source}|${c.text}`;
          if (!seen.has(k)) hoverComments.push(c);
        }
      }
      if (seq !== fetchSeq) return;
      currentCacheKey = lod.key;
      drawPlot(data);
      setStatus(lod.overview ? "overview cached" : `LOD ${lod.level} cached`);
    } catch (err) {
      if (seq === fetchSeq) setStatus(String(err), true);
    } finally {
      if (seq === fetchSeq) fetching = false;
    }
  };
  if (immediate || lod.overview) {
    clearTimeout(lodTimer);
    await run();
  } else {
    clearTimeout(lodTimer);
    lodTimer = setTimeout(run, LOD_DEBOUNCE_MS);
  }
}

function drawPlot(data) {
  const t = theme();
  const traces = data.traces.map((tr) => {
    const ax = AXIS[tr.panel];
    const yaxis = tr.axis === "y2" ? ax.y2 : ax.y;
    const on = visibility[tr.id] !== false;
    return {
      type: "scattergl",
      mode: "lines",
      x: tr.x,
      y: tr.y,
      name: tr.label,
      uid: tr.id,
      visible: on,
      showlegend: on,
      line: { color: tr.color, width: 1.15 },
      xaxis: ax.x,
      yaxis,
      hovertemplate: `%{x}<br>%{y:.2f} ${tr.unit}<extra>${tr.label}</extra>`,
    };
  });

  const shapes = [];
  if (el("showComments").checked) {
    const color = commentLineColor();
    for (const c of data.comments) {
      for (const ax of COMMENT_AXES) {
        shapes.push({
          type: "line",
          xref: ax.xref,
          yref: ax.yref,
          x0: c.t,
          x1: c.t,
          y0: 0,
          y1: 1,
          layer: "below",
          line: { color, width: Number(el("commentWidth").value) },
        });
      }
    }
  }

  const axes = axisLayout(t);
  if (timeRange.t0 != null && timeRange.t1 != null) {
    const r = [timeRange.t0, timeRange.t1];
    for (const name of ["xaxis", "xaxis2", "xaxis3", "xaxis4"]) {
      axes[name].range = r;
      axes[name].autorange = false;
    }
  }

  const layout = {
    ...axes,
    paper_bgcolor: t.paper,
    plot_bgcolor: t.bg,
    font: { color: t.text, family: "Segoe UI, Arial, sans-serif", size: 12 },
    margin: { l: 64, r: 64, t: 72, b: 48 },
    legend: { orientation: "h", y: 1.12, x: 0, font: { size: 11 }, bgcolor: "rgba(0,0,0,0)" },
    autosize: true,
    hovermode: "closest",
    hoverdistance: 20,
    spikedistance: 24,
    shapes,
    uirevision: `traces:${catalog.map((s) => `${s.id}:${visibility[s.id] !== false}`).join("|")}`,
  };

  applyingPlot = true;
  ignoreRelayoutUntil = performance.now() + 120;
  const plotted = Plotly.react(plotDiv, traces, layout, {
    responsive: true,
    displaylogo: false,
    scrollZoom: true,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  });
  ensurePlotEvents();
  Promise.resolve(plotted).then(() => {
    applyingPlot = false;
    ensurePlotEvents();
  }).catch(() => {
    applyingPlot = false;
  });
}

function asMs(v) {
  if (v == null || v === false) return null;
  if (typeof v === "number" && Number.isFinite(v)) return v < 1e11 ? v * 1000 : v;
  if (v instanceof Date) {
    const t = v.getTime();
    return Number.isFinite(t) ? t : null;
  }
  if (typeof v === "string") {
    const parsed = Date.parse(v);
    if (Number.isFinite(parsed)) return parsed;
    const n = Number(v);
    if (Number.isFinite(n)) return n < 1e11 ? n * 1000 : n;
  }
  return null;
}

function readVisibleRange() {
  const layout = plotDiv._fullLayout;
  if (!layout) return null;
  const xa = layout.xaxis2 || layout.xaxis || layout.xaxis3 || layout.xaxis4;
  if (!xa) return null;
  if (xa.autorange) return { t0: null, t1: null };
  const r = xa.range;
  if (!r || r.length < 2) return null;
  const t0 = asMs(r[0]);
  const t1 = asMs(r[1]);
  if (t0 == null || t1 == null || !(t1 > t0)) return null;
  return { t0, t1 };
}

function rangeFromRelayout(ev) {
  if (ev && (ev["xaxis.autorange"] === true || ev["xaxis2.autorange"] === true || ev["xaxis3.autorange"] === true || ev["xaxis4.autorange"] === true)) {
    return { t0: null, t1: null };
  }
  let a = ev && (ev["xaxis.range[0]"] ?? ev["xaxis2.range[0]"] ?? ev["xaxis3.range[0]"] ?? ev["xaxis4.range[0]"]);
  let b = ev && (ev["xaxis.range[1]"] ?? ev["xaxis2.range[1]"] ?? ev["xaxis3.range[1]"] ?? ev["xaxis4.range[1]"]);
  if (a == null || b == null) {
    const rng = ev && (ev["xaxis.range"] || ev["xaxis2.range"] || ev["xaxis3.range"] || ev["xaxis4.range"]);
    if (Array.isArray(rng) && rng.length === 2) {
      a = rng[0];
      b = rng[1];
    }
  }
  const t0 = asMs(a);
  const t1 = asMs(b);
  if (t0 != null && t1 != null && t1 > t0) return { t0, t1 };
  return readVisibleRange();
}

function onZoomChange(ev) {
  if (applyingPlot) return;
  if (performance.now() < ignoreRelayoutUntil) return;
  const next = rangeFromRelayout(ev);
  if (!next) return;
  if (
    timeRange.t0 != null &&
    next.t0 != null &&
    Math.abs(next.t0 - timeRange.t0) < 2 &&
    Math.abs(next.t1 - timeRange.t1) < 2
  ) {
    return;
  }
  timeRange = next;
  showLod(next, next.t0 == null);
}

function ensurePlotEvents() {
  if (plotEventsBound || typeof plotDiv.on !== "function") return;
  plotEventsBound = true;
  plotDiv.on("plotly_relayout", onZoomChange);
}

plotDiv.addEventListener("mousemove", onPlotPointer);
plotDiv.addEventListener("mouseleave", hideCommentTip);
plotDiv.addEventListener(
  "wheel",
  () => {
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(() => {
      const next = readVisibleRange();
      if (next) onZoomChange({ "xaxis.range": [next.t0, next.t1] });
    }, 180);
  },
  { passive: true }
);

el("nPoints").addEventListener("input", () => {
  el("nPointsVal").textContent = el("nPoints").value;
});
el("nPoints").addEventListener("change", () => {
  clearPlotCache();
  showLod(timeRange, true);
});
el("showEvents").addEventListener("change", () => {
  clearPlotCache();
  hoverComments = [];
  showLod(timeRange, true);
});
el("showComments").addEventListener("change", () => {
  hideCommentTip();
  const data = currentCacheKey ? plotCache.get(currentCacheKey) : null;
  if (data) drawPlot(data);
});
el("commentWidth").addEventListener("input", () => {
  el("commentWidthVal").textContent = Number(el("commentWidth").value).toFixed(2);
  const data = currentCacheKey ? plotCache.get(currentCacheKey) : null;
  if (data) drawPlot(data);
});

function applyTheme(light) {
  document.documentElement.classList.toggle("light", light);
  localStorage.setItem("ctTheme", light ? "light" : "dark");
  const btn = el("themeToggle");
  if (btn) btn.title = light ? "Switch to dark mode" : "Switch to light mode";
  const data = currentCacheKey ? plotCache.get(currentCacheKey) : null;
  if (data) drawPlot(data);
}

el("themeToggle").addEventListener("click", () => {
  applyTheme(isDark());
});

function applyScanResult(data) {
  el("folder").value = data.folder;
  try {
    localStorage.setItem("ctFolder", data.folder);
  } catch (err) {}
  renderFileList("daqList", data.files.daq, "No .db files found");
  renderFileList("dcList", data.files.datacan, "No Intelli-Log files found");
  const rh = [...data.files.redhawk_field, ...data.files.redhawk_job];
  renderFileList("rhList", rh, "No FieldLog / JobLog CSV found");
  setStatus(
    `Found ${data.counts.daq} DAQ, ${data.counts.datacan} Intelli-Log, ${data.counts.redhawk_field} FieldLog, ${data.counts.redhawk_job} JobLog`
  );
}

async function scanFolder(showOverlay = false) {
  const folder = el("folder").value.trim();
  if (!folder) {
    setStatus("Enter a job folder path first.", true);
    return false;
  }
  if (showOverlay) showBusy("Scanning folder", "Looking for DAQ, RedHawk, and Intelli-Log files…", true);
  setStatus("Scanning…");
  try {
    const res = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder }),
    });
    if (!res.ok) {
      setStatus(await res.text(), true);
      return false;
    }
    applyScanResult(await res.json());
    return true;
  } catch (err) {
    setStatus(String(err), true);
    return false;
  } finally {
    if (showOverlay) hideBusy();
  }
}

el("scanBtn").addEventListener("click", () => scanFolder(true));

el("browseBtn").addEventListener("click", async () => {
  el("browseBtn").disabled = true;
  setStatus("Choose a job folder…");
  try {
    const res = await fetch("/api/browse-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder: el("folder").value }),
    });
    if (!res.ok) {
      if (res.status === 404) {
        setStatus("Browse needs this CTDF copy. Close the other window on port 8765, then start this app again.", true);
        return;
      }
      setStatus(await res.text(), true);
      return;
    }
    const data = await res.json();
    if (data.cancelled) {
      setStatus("Folder browse cancelled");
      return;
    }
    el("folder").value = data.folder;
    await scanFolder(true);
  } catch (err) {
    setStatus(String(err), true);
  } finally {
    el("browseBtn").disabled = false;
  }
});

el("selectAll").addEventListener("click", () => {
  document.querySelectorAll(".file-list input[type=checkbox]").forEach((n) => {
    n.checked = true;
  });
});

el("loadBtn").addEventListener("click", async () => {
  const daq = checkedPaths("daqList");
  const datacan = checkedPaths("dcList");
  const rhBoxes = [...document.querySelectorAll("#rhList input[type=checkbox]:checked")].map((n) => n.value);
  const redhawk_field = rhBoxes.filter((p) => /fieldlog/i.test(p));
  const redhawk_job = rhBoxes.filter((p) => /joblog/i.test(p));
  if (!daq.length && !datacan.length && !redhawk_field.length) {
    setStatus("Select at least one DAQ, Intelli-Log, or FieldLog file.", true);
    return;
  }
  el("loadBtn").disabled = true;
  showBusy("Loading data", "Intelli-Log files can take a few minutes on OneDrive.");
  setStatus("Loading… Intelli-Log files can take a few minutes on OneDrive.");
  const stopPoll = startProgressPoll();
  try {
    const res = await fetch("/api/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        daq,
        datacan,
        redhawk_field,
        redhawk_job,
        tz: el("tzChicago").checked ? "America/Chicago" : "UTC",
      }),
    });
    const text = await res.text();
    if (!res.ok) {
      setStatus(text, true);
      return;
    }
    const payload = JSON.parse(text);
    if (!payload.catalog) throw new Error("Load finished without data");
    catalog = payload.catalog;
    visibility = {};
    timeRange = { t0: null, t1: null };
    fullRange = { t0: payload.t0, t1: payload.t1 };
    clearPlotCache();
    hoverComments = [];
    hideCommentTip();
    renderSeries();
    el("jobTitle").textContent = "CTDF — Boling Test";
    el("jobMeta").textContent = `${fmtN(payload.n_points)} raw points · ${payload.catalog.length} traces · ${fmtN(payload.n_comments)} comments`;
    setStatus(payload.log.slice(-3).join("\n"));
    setBusyProgress(96, "Building plot…");
    await showLod({ t0: null, t1: null }, true);
    setBusyProgress(100, "Ready");
  } catch (err) {
    setStatus(String(err), true);
  } finally {
    stopPoll();
    hideBusy();
    el("loadBtn").disabled = false;
  }
});

el("exportHtml").addEventListener("click", async () => {
  if (!catalog.length) return;
  setStatus("Building HTML…");
  const res = await fetch("/api/export-html", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      t0: timeRange.t0,
      t1: timeRange.t1,
      n_points: Number(el("nPoints").value),
      series_ids: catalog.filter((s) => visibility[s.id] !== false).map((s) => s.id),
      include_events: el("showEvents").checked,
      title: "CTDF — Boling Test",
      dark: isDark(),
      comment_width: Number(el("commentWidth").value),
    }),
  });
  if (!res.ok) {
    setStatus(await res.text(), true);
    return;
  }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "ctdf-overlay.html";
  a.click();
  URL.revokeObjectURL(a.href);
  setStatus(`Exported HTML (${fmtSize(blob.size)}). Anyone can open it in a browser.`);
});

el("exportPng").addEventListener("click", async () => {
  if (!plotDiv.data) return;
  const url = await Plotly.toImage(plotDiv, { format: "png", width: 1600, height: 1100, scale: 1 });
  const a = document.createElement("a");
  a.href = url;
  a.download = "ctdf-overlay.png";
  a.click();
});

window.addEventListener("resize", () => {
  if (plotDiv.data) Plotly.Plots.resize(plotDiv);
});

function resizePlotSoon() {
  if (plotDiv.data) Plotly.Plots.resize(plotDiv);
}

function initSidebar() {
  const minW = 220;
  const maxW = 720;
  const stored = Number(localStorage.getItem("ctSidebarWidth"));
  let width = Number.isFinite(stored) && stored > 0 ? stored : 340;
  width = Math.min(maxW, Math.max(minW, width));
  document.body.style.setProperty("--sidebar-width", `${width}px`);
  if (localStorage.getItem("ctSidebarCollapsed") === "1") {
    document.body.classList.add("sidebar-collapsed");
  }

  const persist = () => {
    localStorage.setItem("ctSidebarWidth", String(width));
    localStorage.setItem(
      "ctSidebarCollapsed",
      document.body.classList.contains("sidebar-collapsed") ? "1" : "0"
    );
  };

  el("sidebarCollapse").addEventListener("click", () => {
    document.body.classList.add("sidebar-collapsed");
    persist();
    resizePlotSoon();
  });
  el("sidebarExpand").addEventListener("click", () => {
    document.body.classList.remove("sidebar-collapsed");
    persist();
    resizePlotSoon();
  });

  let dragging = false;
  el("sidebarResizer").addEventListener("mousedown", (evt) => {
    if (document.body.classList.contains("sidebar-collapsed")) return;
    dragging = true;
    document.body.classList.add("is-resizing");
    evt.preventDefault();
  });
  window.addEventListener("mousemove", (evt) => {
    if (!dragging) return;
    const cap = Math.min(maxW, Math.floor(window.innerWidth * 0.7));
    width = Math.min(cap, Math.max(minW, evt.clientX));
    document.body.style.setProperty("--sidebar-width", `${width}px`);
    resizePlotSoon();
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("is-resizing");
    persist();
    resizePlotSoon();
  });
}

async function boot() {
  initSidebar();
  const btn = el("themeToggle");
  if (btn) btn.title = isDark() ? "Switch to light mode" : "Switch to dark mode";
  const res = await fetch("/api/defaults");
  const data = await res.json();
  let folder = data.folder;
  try {
    const saved = localStorage.getItem("ctFolder");
    if (saved && saved.trim()) folder = saved.trim();
  } catch (err) {}
  el("folder").value = folder || "";
  if (el("folder").value.trim()) await scanFolder(true);
}

boot();
