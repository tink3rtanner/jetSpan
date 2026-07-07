/* ============================================================================
 * jetSpan perf-lab probe — instrument.js
 * Inject into isochrone.html AFTER load (console paste or playwright evaluate).
 * Idempotent: re-injection is a no-op. Exposes:
 *   window.__perf.report()          -> clean JSON of everything collected
 *   window.__perf.runStress(name)   -> drives a scenario, returns its result
 *     names: worldView | zoomLadder | colorscaleSpam | paletteThrash |
 *            lineStyleThrash | cameraTour | globeSpin | hoverStorm |
 *            themeCycle | all   ('all' = everything except themeCycle)
 * Design notes:
 *  - Heavy per-cell functions (getTimeBandColor, parseCellData, ...) get
 *    COUNTER-only wraps: a performance.now() pair on 110k calls would distort
 *    the very numbers we're measuring. Their cost shows up in their callers.
 *  - Function declarations in the app are global bindings, so reassigning
 *    window.<fn> re-routes all internal call sites.
 *  - All observers use buffered:true, so paint/LCP/nav entries from BEFORE
 *    injection are still captured.
 * ========================================================================== */
(() => {
  'use strict';
  if (window.__perf && window.__perf.__installed) {
    console.log('[__perf] already installed', window.__perf.installedAt);
    return;
  }

  const now = () => performance.now();
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const P = {
    __installed: true,
    installedAt: new Date().toISOString(),
    injectClockMs: +now().toFixed(0), // page-relative time of injection
    ops: {},        // wrapped-function timings
    counters: {},   // cheap call counters
    paint: {},      // FP / FCP / LCP (buffered)
    longtasks: [],  // main-thread blocks > 50ms
    network: {},    // bucketed resource timing
    camera: [],     // jumpTo/flyTo/easeTo -> moveend -> idle records
    fpsRuns: [],    // labelled FPS samples
    stress: {},     // runStress results
    marks: {},      // misc one-off marks (inject-to-idle etc)
    errors: [],
  };
  window.__perf = P;

  /* ------------------------------------------------------------------ *
   * 1. function wrappers
   * ------------------------------------------------------------------ */
  const opRec = (name) =>
    P.ops[name] || (P.ops[name] = { count: 0, totalMs: 0, maxMs: 0, recent: [] });

  function record(name, dt) {
    const r = opRec(name);
    r.count++;
    r.totalMs += dt;
    if (dt > r.maxMs) r.maxMs = dt;
    r.recent.push(+dt.toFixed(2));
    if (r.recent.length > 300) r.recent.shift();
  }

  function wrapTimed(name) {
    const orig = window[name];
    if (typeof orig !== 'function') { P.errors.push('missing fn: ' + name); return; }
    if (orig.__perfWrapped) return;
    const w = function (...args) {
      const t0 = now();
      let out;
      try { out = orig.apply(this, args); }
      catch (e) { record(name, now() - t0); throw e; }
      // async fns (updateGrid, loadChunksForViewport): time to settle, not to first await
      if (out && typeof out.then === 'function') {
        return out.finally(() => record(name, now() - t0));
      }
      record(name, now() - t0);
      return out;
    };
    w.__perfWrapped = true;
    w.__perfOrig = orig;
    window[name] = w;
  }

  function wrapCounted(name) {
    const orig = window[name];
    if (typeof orig !== 'function') { P.errors.push('missing fn: ' + name); return; }
    if (orig.__perfWrapped) return;
    P.counters[name] = 0;
    const w = function (...args) { P.counters[name]++; return orig.apply(this, args); };
    w.__perfWrapped = true;
    w.__perfOrig = orig;
    window[name] = w;
  }

  // timed: the ops named in benchmark.md sections 2/5 (line refs there)
  [
    'generateHexGridDirect', // grid build            isochrone.html:1085
    'smoothGridTimes',       // 3-pass h3 blur        :1940
    'buildContourGeoJSON',   // cumulative dissolve   :1997
    'buildCentroidGeoJSON',  // field points          :2039
    'refreshGridDerived',    // derived push          :2090
    'recolorGrid',           // recolor + setData     :1873
    'updateLegend',          //                       :1888
    'applyThemeChrome',      // chrome/bands/legend   :1719
    'applyTheme',            // full theme switch     :1777
    'setVintagePalette',     // palette switch        :1639
    'setLineStyle',          // line-style switch     :1654
    'applyLineStylePaint',   // paint-only pass       :1666
    'updateGrid',            // whole pipeline, async :2696
    'loadChunksForViewport', // r5/r6 fetch, async    :912
    'showTooltip',           // hover DOM build       :3458
    'buildRouteGeoJSON',     // hover route line      :3551
  ].forEach(wrapTimed);

  // counted only: per-cell hot path (110k+ calls per recolor)
  ['getTimeBandColor', 'getBandIndex', 'parseCellData', 'displayMinutes', 'hexLerp']
    .forEach(wrapCounted);

  /* ------------------------------------------------------------------ *
   * 2. PerformanceObservers (buffered -> pre-injection entries included)
   * ------------------------------------------------------------------ */
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) P.paint[e.name] = +e.startTime.toFixed(1);
    }).observe({ type: 'paint', buffered: true });
  } catch (e) { P.errors.push('paint observer: ' + e.message); }

  try {
    new PerformanceObserver((l) => {
      const es = l.getEntries();
      if (es.length) P.paint['largest-contentful-paint'] = +es[es.length - 1].startTime.toFixed(1);
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (e) { P.errors.push('lcp observer: ' + e.message); }

  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        P.longtasks.push({ start: +e.startTime.toFixed(0), dur: +e.duration.toFixed(0) });
        if (P.longtasks.length > 1000) P.longtasks.shift();
      }
    }).observe({ type: 'longtask', buffered: true });
  } catch (e) { P.errors.push('longtask observer: ' + e.message); }

  // resource timing, bucketed by what the app talks to
  function bucketOf(url) {
    if (url.includes('openfreemap.org')) return 'basemap-tiles';
    if (url.includes('project-osrm')) return 'osrm'; // future-proof; unused today
    if (url.includes('/data/isochrones/') && url.includes('.json.gz')) return 'hex-chunks';
    if (url.includes('/data/')) return 'core-data';
    if (url.includes('unpkg.com')) return 'cdn-libs';
    return 'other';
  }
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        const b = bucketOf(e.name);
        const r = P.network[b] || (P.network[b] = { count: 0, totalMs: 0, maxMs: 0, bytes: 0 });
        r.count++;
        r.totalMs += e.duration;
        if (e.duration > r.maxMs) r.maxMs = +e.duration.toFixed(0);
        r.bytes += e.transferSize || 0;
      }
    }).observe({ type: 'resource', buffered: true });
  } catch (e) { P.errors.push('resource observer: ' + e.message); }

  /* ------------------------------------------------------------------ *
   * 3. camera instrumentation + map helpers
   * ------------------------------------------------------------------ */
  function wrapCamera() {
    const m = window.map;
    if (!m || m.__perfCam) return !!(m && m.__perfCam);
    m.__perfCam = true;
    ['jumpTo', 'flyTo', 'easeTo'].forEach((fn) => {
      const orig = m[fn].bind(m);
      m[fn] = (...a) => { P._camStart = { fn, t: now() }; return orig(...a); };
    });
    m.on('moveend', () => {
      if (!P._camStart) return;
      const rec = { fn: P._camStart.fn, moveMs: +(now() - P._camStart.t).toFixed(0) };
      P._camStart = null;
      const t1 = now();
      m.once('idle', () => { rec.settleToIdleMs = +(now() - t1).toFixed(0); });
      P.camera.push(rec);
      if (P.camera.length > 200) P.camera.shift();
    });
    // inject-to-first-idle: the closest post-hoc proxy for "map interactive"
    const t0 = now();
    m.once('idle', () => { P.marks.injectToFirstIdleMs = +(now() - t0).toFixed(0); });
    return true;
  }
  if (!wrapCamera()) {
    let tries = 0;
    const iv = setInterval(() => { if (wrapCamera() || ++tries > 60) clearInterval(iv); }, 500);
  }

  // resolves ms-to-idle, or -timeout if it never idled
  function waitIdle(timeout = 30000) {
    return new Promise((res) => {
      const m = window.map;
      if (!m) return res(-1);
      let done = false;
      const t0 = now();
      const h = () => { if (!done) { done = true; clearTimeout(to); res(+(now() - t0).toFixed(0)); } };
      const to = setTimeout(() => { if (!done) { done = true; m.off('idle', h); res(-timeout); } }, timeout);
      m.once('idle', h);
    });
  }

  /* ------------------------------------------------------------------ *
   * 4. FPS meter
   * ------------------------------------------------------------------ */
  // one-shot: sample rAF deltas for durationMs while caller drives the work
  function startFPS(label) {
    const frames = [];
    let last = null, stop = false;
    const tick = (t) => {
      if (last !== null) frames.push(t - last);
      last = t;
      if (!stop) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return {
      stop() {
        stop = true;
        const s = frames.slice().sort((a, b) => a - b);
        const sum = s.reduce((a, b) => a + b, 0);
        const out = {
          label,
          frames: s.length,
          avgFps: s.length ? +(1000 / (sum / s.length)).toFixed(1) : 0,
          p95FrameMs: +(s[Math.floor(s.length * 0.95)] || 0).toFixed(1),
          worstFrameMs: +(s[s.length - 1] || 0).toFixed(1),
          framesOver50ms: s.filter((f) => f > 50).length,
        };
        P.fpsRuns.push(out);
        if (P.fpsRuns.length > 60) P.fpsRuns.shift();
        return out;
      },
    };
  }

  /* ------------------------------------------------------------------ *
   * 5. helpers: op deltas, memory, env
   * ------------------------------------------------------------------ */
  function opsSnapshot() {
    const s = {};
    for (const [k, v] of Object.entries(P.ops)) s[k] = { count: v.count, totalMs: v.totalMs };
    return s;
  }
  function opsDelta(before) {
    const d = {};
    for (const [k, v] of Object.entries(P.ops)) {
      const b = before[k] || { count: 0, totalMs: 0 };
      const dc = v.count - b.count;
      if (dc > 0) {
        const dm = v.totalMs - b.totalMs;
        d[k] = { calls: dc, totalMs: +dm.toFixed(1), avgMs: +(dm / dc).toFixed(1) };
      }
    }
    return d;
  }
  function heapMB() {
    return performance.memory
      ? +(performance.memory.usedJSHeapSize / 1048576).toFixed(1)
      : null;
  }
  function glInfo() {
    try {
      const gl = window.map.painter.context.gl;
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      return {
        renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
        vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
      };
    } catch (e) { return null; }
  }
  function saveCam() {
    const m = window.map;
    return m ? { center: m.getCenter(), zoom: m.getZoom(), bearing: m.getBearing(), pitch: m.getPitch() } : null;
  }
  function restoreCam(c) { if (c && window.map) window.map.jumpTo(c); }

  // IMPORTANT: the app's state vars (gridData, currentTheme, currentPalette,
  // colorScale, LOADED_ISOCHRONE, ...) are `let`-declared in a classic script:
  // they are NOT window properties (only function declarations + the explicit
  // window.map are). So we derive state from the DOM selects + the live
  // maplibre source instead of reading the script-scoped variables.
  function getState() {
    const val = (id) => { const el = document.getElementById(id); return el ? el.value : null; };
    return {
      theme: val('theme-select') || (document.body.className.match(/theme-(\w+)/) || [])[1] || null,
      palette: val('palette-select'),
      lineStyle: val('linestyle-select'),
      colorScale: val('color-scale') !== null ? parseFloat(val('color-scale')) : null,
      resolution: (document.getElementById('stat-res') || {}).textContent || null,
    };
  }
  // the grid GeoJSON as last pushed via setData (maplibre GeoJSONSource._data)
  function getGridData() {
    try {
      const d = window.map.getSource('hexgrid')._data;
      return (d && d.features) ? d : null;
    } catch (e) { return null; }
  }

  /* ------------------------------------------------------------------ *
   * 6. stress scenarios
   * ------------------------------------------------------------------ */
  const S = {};

  // full-world res-4 build: z2.5 => res 4 selected (2116) but NO viewport
  // bounds (gate is z>=3, line 2714) => all 109k cells through the pipeline
  S.worldView = async () => {
    const cam = saveCam();
    const before = opsSnapshot();
    const heap0 = heapMB();
    const t0 = now();
    window.map.jumpTo({ center: [-2.587, 51.454], zoom: 2.5 });
    await sleep(600);              // moveend fires; app debounce is 350ms (:2199)
    await window.updateGrid(window.getResolutionForZoom(2.5), false); // deterministic build
    const idleMs = await waitIdle(60000);
    const gd = getGridData();                  // capture BEFORE camera restore rebuilds the grid
    const cells = gd ? gd.features.length : null;
    const wallMs = +(now() - t0).toFixed(0);
    const heap1 = heapMB();
    const ops = opsDelta(before);
    restoreCam(cam);
    await waitIdle(30000);
    return {
      wallMs,
      settleToIdleMs: idleMs,
      cells,
      heapBeforeMB: heap0,
      heapAfterMB: heap1,
      ops,
    };
  };

  // the real pipeline at each zoom tier (incl. r5/r6 chunk loads)
  S.zoomLadder = async () => {
    const cam = saveCam();
    const steps = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5];
    const rows = [];
    for (const z of steps) {
      const before = opsSnapshot();
      const t0 = now();
      window.map.jumpTo({ center: [-2.587, 51.454], zoom: z });
      await sleep(600);            // let the 350ms moveend debounce fire updateGrid
      const idleMs = await waitIdle(60000);
      const gd = getGridData();
      rows.push({
        zoom: z,
        res: window.getResolutionForZoom(z),
        cells: gd ? gd.features.length : null,
        wallToIdleMs: +(now() - t0).toFixed(0),
        idleWaitMs: idleMs,
        ops: opsDelta(before),
      });
    }
    restoreCam(cam);
    await waitIdle(30000);
    return { steps: rows };
  };

  // simulated drag: dispatch 'input' at frame cadence like a real slider drag.
  // each event runs the FULL recolor+dissolve synchronously (listener :3644)
  S.colorscaleSpam = async () => {
    const el = document.getElementById('color-scale');
    if (!el) return { skipped: 'no #color-scale' };
    const orig = el.value;
    const before = opsSnapshot();
    const fps = startFPS('colorscale-spam');
    const heap0 = heapMB();
    const t0 = now();
    const values = [];
    for (let v = 0.5; v <= 4.001; v += 0.1) values.push(v);
    for (let v = 4.0; v >= 0.999; v -= 0.1) values.push(v);
    let events = 0;
    for (const v of values) {
      el.value = v.toFixed(1);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      events++;
      await sleep(16); // ~pointer-move cadence
    }
    const wallMs = +(now() - t0).toFixed(0);
    // restore
    el.value = orig;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    await waitIdle(30000);
    const d = opsDelta(before);
    return {
      events,
      wallMs,
      msPerEvent: +(wallMs / events).toFixed(1),
      recolorAvgMs: d.recolorGrid ? d.recolorGrid.avgMs : null,
      contourAvgMs: d.buildContourGeoJSON ? d.buildContourGeoJSON.avgMs : null,
      fps: fps.stop(),
      heapDeltaMB: heapMB() !== null ? +(heapMB() - heap0).toFixed(1) : null,
      ops: d,
    };
  };

  // rapid palette thrash (vintage-only feature; :1639)
  S.paletteThrash = async () => {
    if (getState().theme !== 'vintage') return { skipped: 'theme is not vintage' };
    const origPal = getState().palette || 'heatmap';
    const pals = ['heatmap', 'monowarm', 'viridis', 'galton'];
    const before = opsSnapshot();
    const fps = startFPS('palette-thrash');
    const t0 = now();
    let switches = 0;
    for (let cycle = 0; cycle < 3; cycle++) {
      for (const p of pals) {
        window.setVintagePalette(p);
        switches++;
        await sleep(30); // fast thrash, but let a frame through
      }
    }
    const wallMs = +(now() - t0).toFixed(0);
    window.setVintagePalette(origPal);
    await waitIdle(30000);
    const d = opsDelta(before);
    return {
      switches, wallMs,
      msPerSwitch: +(wallMs / switches).toFixed(1),
      fps: fps.stop(),
      ops: d,
    };
  };

  // line-style cycle — expected-cheap control (paint props only; :1666)
  S.lineStyleThrash = async () => {
    if (getState().theme !== 'vintage') return { skipped: 'theme is not vintage' };
    const origLS = getState().lineStyle || 'washes';
    const styles = ['washes', 'contours', 'layered'];
    const before = opsSnapshot();
    const t0 = now();
    let switches = 0;
    for (let i = 0; i < 10; i++) {
      for (const s of styles) { window.setLineStyle(s); switches++; }
      await sleep(16);
    }
    const wallMs = +(now() - t0).toFixed(0);
    window.setLineStyle(origLS);
    return { switches, wallMs, msPerSwitch: +(wallMs / switches).toFixed(2), ops: opsDelta(before) };
  };

  // repeated camera flights; FPS + settle per leg
  S.cameraTour = async () => {
    const cam = saveCam();
    const legs = [
      { name: 'newyork', center: [-74.006, 40.713], zoom: 4 },
      { name: 'tokyo', center: [139.692, 35.690], zoom: 3 },
      { name: 'sydney', center: [151.209, -33.868], zoom: 3 },
      { name: 'bristol', center: [-2.587, 51.454], zoom: 4 },
    ];
    const fps = startFPS('camera-tour');
    const rows = [];
    for (const leg of legs) {
      const t0 = now();
      window.map.flyTo({ center: leg.center, zoom: leg.zoom, duration: 2000 });
      await new Promise((r) => window.map.once('moveend', r));
      const flightMs = +(now() - t0).toFixed(0);
      const idleMs = await waitIdle(60000);
      rows.push({ leg: leg.name, flightMs, settleToIdleMs: idleMs });
    }
    const f = fps.stop();
    restoreCam(cam);
    await waitIdle(30000);
    return { legs: rows, fps: f };
  };

  // globe rotation FPS at low zoom (globe projection is vintage/modern default)
  S.globeSpin = async () => {
    const cam = saveCam();
    window.map.jumpTo({ center: [-2.587, 51.454], zoom: 1.8 });
    await waitIdle(30000);
    const fps = startFPS('globe-spin');
    let lng = -2.587;
    for (let i = 0; i < 12; i++) {
      lng += 30;
      const wrapped = ((lng + 180) % 360) - 180;
      window.map.easeTo({ center: [wrapped, 20], duration: 650 });
      await sleep(700);
    }
    const f = fps.stop();
    restoreCam(cam);
    await waitIdle(30000);
    return { fps: f };
  };

  // replay of the exact mousemove-handler work (:2153) on random cells —
  // replaces the brief's "OSRM click" scenario (no live OSRM in this app)
  S.hoverStorm = async () => {
    const gd = getGridData();
    if (!gd || !gd.features.length) return { skipped: 'no gridData in hexgrid source' };
    const N = Math.min(40, gd.features.length);
    const before = opsSnapshot();
    const t0 = now();
    for (let i = 0; i < N; i++) {
      const f = gd.features[Math.floor(Math.random() * gd.features.length)];
      // maplibre hands the handler STRINGIFIED nested props — mimic that cost
      const props = Object.assign({}, f.properties, {
        breakdown: JSON.stringify(f.properties.breakdown),
        route: JSON.stringify(f.properties.route),
        centroid: JSON.stringify(f.properties.centroid),
      });
      window.showTooltip(props);
      const src = window.map.getSource('route-line');
      if (src) src.setData(window.buildRouteGeoJSON(f.properties.route, f.properties.centroid));
      await sleep(30);
    }
    const wallMs = +(now() - t0).toFixed(0);
    window.hideTooltip();
    const src = window.map.getSource('route-line');
    if (src) src.setData({ type: 'FeatureCollection', features: [] });
    const d = opsDelta(before);
    return {
      hovers: N, wallMs,
      msPerHover: +((wallMs - N * 30) / N).toFixed(2), // net of the 30ms pacing sleeps
      tooltipAvgMs: d.showTooltip ? d.showTooltip.avgMs : null,
      routeGeoAvgMs: d.buildRouteGeoJSON ? d.buildRouteGeoJSON.avgMs : null,
      ops: d,
    };
  };

  // full theme cycle: basemap reload each time (setStyle diff:false, :1796).
  // network-heavy — run explicitly, last.
  S.themeCycle = async () => {
    const origTheme = getState().theme || 'vintage';
    const order = ['modern', 'dark', 'vintage'].filter((t) => t !== origTheme).concat([origTheme]);
    const rows = [];
    for (const t of order) {
      const before = opsSnapshot();
      const t0 = now();
      window.applyTheme(t);
      const idleMs = await waitIdle(90000);
      rows.push({ theme: t, wallToIdleMs: +(now() - t0).toFixed(0), idleWaitMs: idleMs, ops: opsDelta(before) });
      await sleep(500);
    }
    return { switches: rows, restoredTo: getState().theme };
  };

  P.runStress = async function runStress(name) {
    if (name === 'all') {
      const order = ['worldView', 'zoomLadder', 'colorscaleSpam', 'paletteThrash',
        'lineStyleThrash', 'cameraTour', 'globeSpin', 'hoverStorm'];
      for (const n of order) await P.runStress(n);
      return P.stress;
    }
    if (!S[name]) return { error: 'unknown scenario: ' + name + ' (have: ' + Object.keys(S).join(', ') + ', all)' };
    if (!window.map) return { error: 'map not ready' };
    console.log('[__perf] stress:', name);
    const t0 = now();
    let out;
    try { out = await S[name](); }
    catch (e) { out = { error: String(e) }; P.errors.push('stress ' + name + ': ' + String(e)); }
    out.scenarioWallMs = +(now() - t0).toFixed(0);
    out.at = new Date().toISOString();
    P.stress[name] = out;
    console.log('[__perf] stress done:', name, out);
    return out;
  };

  /* ------------------------------------------------------------------ *
   * 7. report
   * ------------------------------------------------------------------ */
  P.report = function report() {
    const nav = performance.getEntriesByType('navigation')[0];
    const lt = P.longtasks;
    return {
      meta: {
        installedAt: P.installedAt,
        reportAt: new Date().toISOString(),
        url: location.href,
        errors: P.errors,
      },
      env: {
        ua: navigator.userAgent,
        cores: navigator.hardwareConcurrency || null,
        deviceMemoryGB: navigator.deviceMemory || null,
        dpr: devicePixelRatio,
        viewport: { w: innerWidth, h: innerHeight },
        gl: glInfo(),
        heapMB: heapMB(),
      },
      appState: Object.assign(getState(), {
        // NB dataset per-res cell counts aren't reachable post-hoc
        // (LOADED_ISOCHRONE is let-scoped, not on window) — measured values
        // are recorded in perf-lab/benchmark.md section 1 + the app's console logs
        cellsRendered: (getGridData() || { features: [] }).features.length,
      }),
      coldLoad: nav ? {
        domContentLoadedMs: +nav.domContentLoadedEventEnd.toFixed(0),
        loadEventMs: +nav.loadEventEnd.toFixed(0),
        transferKB: +((nav.transferSize || 0) / 1024).toFixed(0),
      } : null,
      paint: P.paint,             // first-paint / FCP / LCP (ms from nav start)
      marks: P.marks,             // injectToFirstIdleMs etc
      ops: Object.fromEntries(Object.entries(P.ops).map(([k, v]) => [k, {
        count: v.count,
        totalMs: +v.totalMs.toFixed(1),
        avgMs: v.count ? +(v.totalMs / v.count).toFixed(2) : 0,
        maxMs: +v.maxMs.toFixed(1),
        recentTail: v.recent.slice(-10),
      }])),
      counters: P.counters,
      longtasks: {
        count: lt.length,
        totalBlockedMs: lt.reduce((a, b) => a + b.dur, 0),
        worstMs: lt.reduce((a, b) => Math.max(a, b.dur), 0),
      },
      network: Object.fromEntries(Object.entries(P.network).map(([k, v]) => [k, {
        count: v.count,
        totalMs: +v.totalMs.toFixed(0),
        avgMs: +(v.totalMs / v.count).toFixed(0),
        maxMs: v.maxMs,
        totalKB: +(v.bytes / 1024).toFixed(0),
      }])),
      camera: P.camera.slice(-20),
      fpsRuns: P.fpsRuns,
      stress: P.stress,
    };
  };

  console.log('[__perf] installed. usage: await __perf.runStress("all"); __perf.report()');
})();
