// =============================================================================
// INTERACTION PERFORMANCE SUITE for isochrone.html
//
// Measures what the static runBenchmark() harness does NOT: frame pacing
// during real, continuous map interactions — panning, zooming, globe
// rotation, bearing spins, and the click-to-pin interaction (if present).
//
// Metrics per scenario (sampled via requestAnimationFrame + PerformanceObserver):
//   frames, duration, fps, avg/median/p95/max frame time (ms),
//   jank% (frames > 33.4ms, i.e. dropped below 30fps),
//   longTasks count + total blocked ms (PerformanceObserver 'longtask')
//
// Usage:
//   - console: paste this file, then `await runInteractionBench()`
//   - headless: scripts/run-interaction-bench.py (playwright driver) injects
//     this file and saves dated JSON to docs/benchmarks/
//
// The script is standalone-injectable so it can benchmark ANY revision of
// isochrone.html (including old baselines) without modifying that revision.
// =============================================================================

// Public readiness seam for browser runners. App state is declared with top-level
// `let`, so it is intentionally not available as window.LOADED_ISOCHRONE/map.
// Keeping this check in a classic script loaded by the app document gives runners
// an observable readiness contract without exposing or duplicating app internals.
window.waitForJetSpanReady = async function waitForJetSpanReady(timeoutMs = 120000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    if (typeof map !== 'undefined' && map &&
        typeof LOADED_ISOCHRONE !== 'undefined' && LOADED_ISOCHRONE &&
        typeof LOADED_ROUTE_TABLE !== 'undefined' && LOADED_ROUTE_TABLE &&
        typeof LOADED_AIRPORTS !== 'undefined' && LOADED_AIRPORTS &&
        typeof gridData !== 'undefined' && gridData?.features?.length) {
      return {
        ready: true,
        elapsedMs: Math.round(performance.now() - started),
        cells: gridData.features.length,
        resolution: currentResolution,
      };
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  return { ready: false, elapsedMs: Math.round(performance.now() - started) };
};

window.runInteractionBench = async function runInteractionBench(opts) {
  opts = opts || {}; // robust to being called with null (playwright evaluate)
  if (typeof map === 'undefined' || !map) {
    console.error('[IBENCH] no map — load isochrone.html first');
    return null;
  }
  // NB: app globals are `let`-declared (lexical), so check bare identifiers
  if (typeof LOADED_ISOCHRONE === 'undefined' || !LOADED_ISOCHRONE) {
    console.error('[IBENCH] isochrone data not loaded yet');
    return null;
  }

  // how long to keep sampling after an animation ends — captures the
  // debounced updateGrid() regen (350ms debounce) + setData cost that the
  // interaction actually triggers. This is deliberate: it is part of the
  // real cost of panning/zooming.
  const POST_MS = opts.postMs ?? 1400;

  // --- visual overlay so a human can watch the run ---
  let overlay = document.getElementById('ibench-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'ibench-overlay';
    overlay.style.cssText = `
      position:fixed; top:10px; left:50%; transform:translateX(-50%);
      background:rgba(0,0,0,0.85); color:#fb0; font-family:monospace;
      font-size:13px; padding:10px 18px; border-radius:8px; z-index:9999;
      border:1px solid #fb0; min-width:340px; text-align:center;
    `;
    document.body.appendChild(overlay);
  }
  const showStatus = (msg) => { overlay.textContent = msg; };

  // --- frame sampler ---
  let sampling = false;
  let frameTimes = [];
  let lastTs = null;
  function frameLoop(ts) {
    if (!sampling) return;
    if (lastTs !== null) frameTimes.push(ts - lastTs);
    lastTs = ts;
    requestAnimationFrame(frameLoop);
  }

  // --- long task observer (chromium supports 'longtask') ---
  let longTasks = [];
  let ltObserver = null;
  try {
    ltObserver = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) longTasks.push(e.duration);
    });
    ltObserver.observe({ type: 'longtask', buffered: false });
  } catch (e) {
    console.warn('[IBENCH] longtask observer unsupported:', e.message);
  }

  function startSampling() {
    frameTimes = [];
    longTasks = [];
    lastTs = null;
    sampling = true;
    requestAnimationFrame(frameLoop);
  }

  function stopSampling() {
    sampling = false;
    const ft = frameTimes.slice().sort((a, b) => a - b);
    const dur = frameTimes.reduce((s, t) => s + t, 0);
    const pct = (p) => ft.length ? ft[Math.min(ft.length - 1, Math.floor(ft.length * p))] : 0;
    return {
      frames: ft.length,
      durationMs: +dur.toFixed(0),
      fps: dur > 0 ? +(ft.length / (dur / 1000)).toFixed(1) : 0,
      avgFrameMs: ft.length ? +(dur / ft.length).toFixed(2) : 0,
      medianFrameMs: +pct(0.5).toFixed(2),
      p95FrameMs: +pct(0.95).toFixed(2),
      p99FrameMs: +pct(0.99).toFixed(2),
      maxFrameMs: ft.length ? +ft[ft.length - 1].toFixed(2) : 0,
      jankPct: ft.length ? +((ft.filter(t => t > 33.4).length / ft.length) * 100).toFixed(1) : 0,
      blockingMs: +frameTimes.reduce((sum, t) => sum + Math.max(0, t - 33.4), 0).toFixed(1),
      longTasks: longTasks.length,
      longTaskTotalMs: +longTasks.reduce((s, t) => s + t, 0).toFixed(0),
    };
  }

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  function resourceSnapshot() {
    return performance.getEntriesByType('resource').map(entry => ({
      name: entry.name,
      duration: entry.duration,
      transferSize: entry.transferSize || 0,
      encodedBodySize: entry.encodedBodySize || 0,
      decodedBodySize: entry.decodedBodySize || 0,
    }));
  }

  function resourceDelta(before) {
    const all = resourceSnapshot();
    const added = all.slice(before.length);
    const chunks = added.filter(entry => /\/r[56]\/[^/]+\.json\.gz(?:$|\?)/.test(entry.name));
    return {
      requests: added.length,
      chunks: chunks.length,
      transferBytes: added.reduce((sum, entry) => sum + entry.transferSize, 0),
      encodedBytes: added.reduce((sum, entry) => sum + entry.encodedBodySize, 0),
      decodedBytes: added.reduce((sum, entry) => sum + entry.decodedBodySize, 0),
      resourceMs: +added.reduce((sum, entry) => sum + entry.duration, 0).toFixed(1),
      chunkMs: +chunks.reduce((sum, entry) => sum + entry.duration, 0).toFixed(1),
    };
  }

  // ease the camera and resolve when the movement ends (linear easing so
  // frame load is constant across the animation)
  function ease(camOpts, duration) {
    return new Promise((resolve) => {
      map.once('moveend', resolve);
      map.easeTo({ ...camOpts, duration, easing: (t) => t });
    });
  }

  // settle the map fully (grid regen + tiles) between scenarios
  async function settle() {
    const started = performance.now();
    await sleep(425); // outlast the 350ms updateGrid debounce
    const deadline = performance.now() + 12000;
    while (performance.now() < deadline &&
           ((typeof isUpdatingGrid !== 'undefined' && isUpdatingGrid) ||
            (typeof _chunkLoadingInProgress !== 'undefined' && _chunkLoadingInProgress) ||
            (typeof pendingGridUpdate !== 'undefined' && pendingGridUpdate))) {
      await sleep(50);
    }
    // `idle` is edge-triggered. Waiting for it after a paint-only control while
    // the map is already idle adds a fake four-second stall to the measurement.
    if (!map.loaded() || map.isMoving()) {
      await Promise.race([
        new Promise(r => map.once('idle', r)),
        sleep(4000),
      ]);
    }
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return +(performance.now() - started).toFixed(1);
  }

  async function measureVisit(name, coords, zoom) {
    const resourcesBefore = resourceSnapshot();
    const traceBefore = window.getJetSpanPerfTrace?.().length || 0;
    const started = performance.now();
    map.jumpTo({ center: coords, zoom, bearing: 0, pitch: 0 });
    const settleMs = await settle();
    const trace = window.getJetSpanPerfTrace?.().slice(traceBefore) || [];
    return {
      name,
      zoom,
      resolution: currentResolution,
      cells: gridData?.features?.length || 0,
      settleMs,
      wallMs: +(performance.now() - started).toFixed(1),
      resources: resourceDelta(resourcesBefore),
      updates: trace,
    };
  }

  async function measureControl(name, element, mutate, eventName = 'change') {
    const started = performance.now();
    mutate(element);
    element.dispatchEvent(new Event(eventName, { bubbles: true }));
    const settleMs = await settle();
    return {
      name,
      settleMs,
      wallMs: +(performance.now() - started).toFixed(1),
    };
  }

  async function scenario(name, setupFn, actionFn) {
    showStatus(`SCENARIO: ${name} — setting up...`);
    await setupFn();
    await settle();
    showStatus(`SCENARIO: ${name} — measuring...`);
    const resourcesBefore = resourceSnapshot();
    const wallStarted = performance.now();
    startSampling();
    await actionFn();
    const settleMs = await settle();
    await sleep(POST_MS); // capture delayed MapLibre/source work
    const m = stopSampling();
    m.scenario = name;
    m.wallMs = +(performance.now() - wallStarted).toFixed(1);
    m.settleMs = settleMs;
    m.resources = resourceDelta(resourcesBefore);
    console.log(`[IBENCH] ${name}: ${m.fps}fps avg=${m.avgFrameMs}ms p95=${m.p95FrameMs}ms jank=${m.jankPct}% longTasks=${m.longTasks}/${m.longTaskTotalMs}ms`);
    return m;
  }

  const BRISTOL = [-2.5879, 51.4545];
  const results = [];
  const navigation = performance.getEntriesByType('navigation')[0];
  const startupResources = resourceSnapshot();
  const startup = {
    readyMs: +performance.now().toFixed(1),
    domInteractiveMs: navigation ? +navigation.domInteractive.toFixed(1) : null,
    domContentLoadedMs: navigation ? +navigation.domContentLoadedEventEnd.toFixed(1) : null,
    loadEventMs: navigation ? +navigation.loadEventEnd.toFixed(1) : null,
    requests: startupResources.length,
    transferBytes: startupResources.reduce((sum, entry) => sum + entry.transferSize, 0),
    encodedBytes: startupResources.reduce((sum, entry) => sum + entry.encodedBodySize, 0),
    decodedBytes: startupResources.reduce((sum, entry) => sum + entry.decodedBodySize, 0),
    cells: gridData?.features?.length || 0,
    resolution: currentResolution,
  };

  // --- 1. continuous pan at z4 (res 4, precomputed, city-hop sweep) ---
  results.push(await scenario('pan-continuous-z4',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 4, bearing: 0, pitch: 0 }); },
    async () => {
      await ease({ center: [-0.12, 51.51] }, 900);   // london
      await ease({ center: [2.35, 48.86] }, 900);    // paris
      await ease({ center: [28.98, 41.01] }, 1400);  // istanbul
      await ease({ center: [-21.9, 64.14] }, 1600);  // reykjavik
    }));

  // --- 2. continuous pan at z6 (res 6, chunked path — heaviest cells) ---
  results.push(await scenario('pan-continuous-z6',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 6, bearing: 0, pitch: 0 }); },
    async () => {
      await ease({ center: [-0.12, 51.51] }, 1200);  // london
      await ease({ center: [2.35, 48.86] }, 1200);   // paris
    }));

  // --- 3. each zoom threshold, in both directions ---
  // A single long zoom hides which resolution transition is expensive. Keep
  // the transitions as sub-results so regressions point at the exact boundary.
  const zoomTransitions = [];
  const thresholdSteps = [
    { name: 'r1-r2', zoom: 1.05, expectedRes: 2 },
    { name: 'r2-r3', zoom: 2.05, expectedRes: 3 },
    { name: 'r3-r4', zoom: 3.05, expectedRes: 4 },
    { name: 'r4-r5', zoom: 4.55, expectedRes: 5 },
    { name: 'r5-r6', zoom: 6.55, expectedRes: 6 },
  ];
  const thresholdResult = await scenario('zoom-thresholds',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 0.8, bearing: 0, pitch: 0 }); },
    async () => {
      for (const step of thresholdSteps) {
        const started = performance.now();
        await ease({ zoom: step.zoom }, 450);
        await settle();
        zoomTransitions.push({
          direction: 'in', threshold: step.name, zoom: step.zoom,
          expectedRes: step.expectedRes, actualRes: currentResolution,
          cells: gridData?.features?.length || 0,
          settleMs: +(performance.now() - started).toFixed(1),
        });
      }
      for (let i = thresholdSteps.length - 1; i >= 0; i--) {
        const step = thresholdSteps[i];
        const targetZoom = step.zoom - 0.1;
        const expectedRes = Math.max(1, step.expectedRes - 1);
        const started = performance.now();
        await ease({ zoom: targetZoom }, 450);
        await settle();
        zoomTransitions.push({
          direction: 'out', threshold: step.name, zoom: targetZoom,
          expectedRes, actualRes: currentResolution,
          cells: gridData?.features?.length || 0,
          settleMs: +(performance.now() - started).toFixed(1),
        });
      }
    });
  thresholdResult.transitions = zoomTransitions;
  thresholdResult.transitionFailures = zoomTransitions.filter(
    transition => transition.actualRes !== transition.expectedRes).length;
  results.push(thresholdResult);

  // --- 4. application chunk cache: first visit vs exact revisit ---
  const cacheVisits = [];
  const cacheResult = await scenario('chunk-cache',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 4, bearing: 0, pitch: 0 }); },
    async () => {
      cacheVisits.push(await measureVisit('tokyo-r5-cold', [139.691, 35.690], 5.2));
      cacheVisits.push(await measureVisit('cape-town-r5-detour', [18.424, -33.925], 5.2));
      cacheVisits.push(await measureVisit('tokyo-r5-warm', [139.691, 35.690], 5.2));
      cacheVisits.push(await measureVisit('new-york-r6-cold', [-74.006, 40.713], 7));
      cacheVisits.push(await measureVisit('sydney-r6-detour', [151.209, -33.869], 7));
      cacheVisits.push(await measureVisit('new-york-r6-warm', [-74.006, 40.713], 7));
    });
  cacheResult.visits = cacheVisits;
  cacheResult.cacheFailures = cacheVisits.filter(visit =>
    visit.name.endsWith('-warm') && visit.resources.chunks !== 0).length;
  results.push(cacheResult);

  // --- 5. discrete pans across representative global regions and resolutions ---
  const panStops = [];
  const panMatrix = [
    // Base-data path: seven regions, no chunk network.
    ['bristol-r4', BRISTOL, 4],
    ['reykjavik-r4', [-21.896, 64.147], 4],
    ['new-york-r4', [-74.006, 40.713], 4],
    ['sao-paulo-r4', [-46.633, -23.551], 4],
    ['cape-town-r4', [18.424, -33.925], 4],
    ['tokyo-r4', [139.691, 35.690], 4],
    ['sydney-r4', [151.209, -33.869], 4],
    // Lazy data paths: enough spread to expose request and merge hotspots.
    ['paris-r5', [2.352, 48.857], 5.2],
    ['dubai-r5', [55.270, 25.205], 5.2],
    ['mumbai-r5', [72.878, 19.076], 5.2],
    ['los-angeles-r5', [-118.244, 34.052], 5.2],
    ['frankfurt-r6', [8.682, 50.110], 7],
    ['singapore-r6', [103.8, 1.35], 7],
    ['los-angeles-r6', [-118.244, 34.052], 7],
  ];
  const panMatrixResult = await scenario('pan-load-matrix',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 4, bearing: 0, pitch: 0 }); },
    async () => {
      for (const [name, coords, zoom] of panMatrix) {
        panStops.push(await measureVisit(name, coords, zoom));
      }
    });
  panMatrixResult.stops = panStops;
  panMatrixResult.slowestStops = panStops.slice()
    .sort((a, b) => b.wallMs - a.wallMs)
    .slice(0, 5)
    .map(({ name, wallMs, resolution, cells, resources }) =>
      ({ name, wallMs, resolution, cells, chunks: resources.chunks }));
  results.push(panMatrixResult);

  // --- 6. rapid navigation while a lazy update is still running ---
  const rapidTarget = [-74.006, 40.713];
  const rapidResult = await scenario('rapid-navigation-race',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 5.2, bearing: 0, pitch: 0 }); },
    async () => {
      map.jumpTo({ center: [139.691, 35.690], zoom: 5.2 });
      await sleep(375); // first debounced lazy update has just started
      map.jumpTo({ center: rapidTarget, zoom: 7 });
    });
  const rapidCenter = map.getCenter();
  rapidResult.final = {
    expectedResolution: 6,
    actualResolution: currentResolution,
    centerError: +(
      Math.abs(rapidCenter.lng - rapidTarget[0]) +
      Math.abs(rapidCenter.lat - rapidTarget[1])
    ).toFixed(3),
    cells: gridData?.features?.length || 0,
  };
  rapidResult.navigationFailures =
    (rapidResult.final.actualResolution !== rapidResult.final.expectedResolution ||
     rapidResult.final.centerError > 0.1 || rapidResult.final.cells === 0) ? 1 : 0;
  results.push(rapidResult);

  // --- 7. date-line pans at every viewport-clipped resolution ---
  const antimeridianStops = [];
  const antimeridianResult = await scenario('antimeridian-navigation',
    async () => { map.jumpTo({ center: [178.1, -17.7], zoom: 4, bearing: 0, pitch: 0 }); },
    async () => {
      for (const [name, coords, zoom] of [
        ['fiji-r4', [178.1, -17.7], 4],
        ['samoa-r5', [-172.1, -13.8], 5.2],
        ['fiji-r6', [178.1, -17.7], 7],
        ['samoa-r6', [-172.1, -13.8], 7],
      ]) {
        antimeridianStops.push(await measureVisit(name, coords, zoom));
      }
    });
  antimeridianResult.stops = antimeridianStops;
  antimeridianResult.renderFailures = antimeridianStops.filter(stop => stop.cells === 0).length;
  results.push(antimeridianResult);

  // --- 8. real DOM controls: presets, scale, visibility, coverage, hover ---
  const uiSteps = [];
  let hoverVisible = false;
  const toggleIds = ['toggle-airports', 'toggle-grid', 'toggle-osrm', 'toggle-multiselect'];
  const toggleInitial = Object.fromEntries(toggleIds.map(id =>
    [id, document.getElementById(id).checked]));
  const uiResult = await scenario('ui-transitions',
    async () => { map.jumpTo({ center: [2.35, 48.86], zoom: 4.4, bearing: 0, pitch: 0 }); },
    async () => {
      const preset = document.getElementById('preset-select');
      for (const value of ['bold-heat', 'ink-heat', 'verdigris', 'hypso']) {
        uiSteps.push(await measureControl(`preset-${value}`, preset, el => { el.value = value; }));
      }

      const scale = document.getElementById('color-scale');
      for (const value of ['1', '2', '4', '3']) {
        uiSteps.push(await measureControl(`color-scale-${value}`, scale, el => { el.value = value; }));
      }

      for (const id of toggleIds) {
        const control = document.getElementById(id);
        const initial = control.checked;
        const changed = !initial;
        uiSteps.push(await measureControl(
          `${id}-${changed ? 'on' : 'off'}`, control, el => { el.checked = changed; }));
        uiSteps.push(await measureControl(
          `${id}-${initial ? 'on' : 'off'}`, control, el => { el.checked = initial; }));
      }

      const canvas = map.getCanvas();
      const point = map.project([2.35, 48.86]);
      const hoverStarted = performance.now();
      // Synthetic mouse events are not trusted and MapLibre intentionally does
      // not route them through delegated layer handlers. Exercise the same
      // user-visible tooltip transition from a rendered hit-layer feature here;
      // the CLI driver separately performs a trusted mouse move end-to-end.
      const hit = map.queryRenderedFeatures(point, { layers: ['hexgrid-fill'] })[0];
      if (hit) showTooltip(hit.properties);
      await sleep(100);
      hoverVisible = document.getElementById('tooltip').classList.contains('visible');
      uiSteps.push({
        name: 'hover-tooltip',
        visible: hoverVisible,
        wallMs: +(performance.now() - hoverStarted).toFixed(1),
      });
      hideTooltip();

      const infoButton = document.getElementById('info-btn');
      const infoPanel = document.getElementById('info-panel');
      const infoStarted = performance.now();
      infoButton.click();
      const opened = infoPanel.classList.contains('visible');
      infoButton.click();
      const closed = !infoPanel.classList.contains('visible');
      uiSteps.push({
        name: 'info-panel-open-close', opened, closed,
        wallMs: +(performance.now() - infoStarted).toFixed(1),
      });
    });
  uiResult.steps = uiSteps;
  uiResult.hoverFailures = hoverVisible ? 0 : 1;
  uiResult.panelFailures = uiSteps.some(step =>
    step.name === 'info-panel-open-close' && (!step.opened || !step.closed)) ? 1 : 0;
  uiResult.restoreFailures = toggleIds.filter(id =>
    document.getElementById(id).checked !== toggleInitial[id]).length;
  uiResult.slowestSteps = uiSteps.slice()
    .sort((a, b) => (b.wallMs || 0) - (a.wallMs || 0))
    .slice(0, 5);
  results.push(uiResult);

  // --- 9. long zoom sweep in and out (continuous gesture behavior) ---
  results.push(await scenario('zoom-in-out',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 1.5, bearing: 0, pitch: 0 }); },
    async () => {
      await ease({ zoom: 7 }, 2500);
      await ease({ zoom: 1.5 }, 2500);
    }));

  // --- 10. globe rotation (longitude spin at low zoom, globe projection) ---
  results.push(await scenario('rotate-globe',
    async () => { map.jumpTo({ center: [0, 30], zoom: 2, bearing: 0, pitch: 0 }); },
    async () => {
      await ease({ center: [120, 30] }, 1500);
      await ease({ center: [-120, 30] }, 1500);
      await ease({ center: [0, 30] }, 1500);
    }));

  // --- 11. bearing spin at mid zoom (rotation with dense cells on screen) ---
  results.push(await scenario('bearing-spin-z5',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 5, bearing: 0, pitch: 0 }); },
    async () => {
      await ease({ bearing: 180 }, 1200);
      await ease({ bearing: 360 }, 1200);
    }));

  // --- 12. pin, multi-select, and keyboard clear ---
  if (typeof window.pinCellAt === 'function' && typeof window.clearAllPins === 'function') {
    let pinFailures = 0;
    const pinResult = await scenario('pin-interaction',
      async () => {
        window.clearAllPins();
        map.jumpTo({ center: [2.0, 47.0], zoom: 4.4, bearing: 0, pitch: 0 });
      },
      async () => {
        const multi = document.getElementById('toggle-multiselect');
        multi.checked = true;
        multi.dispatchEvent(new Event('change', { bubbles: true }));
        // Three destinations coexist in multi-select mode, then Escape clears.
        for (let round = 0; round < 3; round++) {
          window.pinCellAt(-9.14, 38.72);  // lisbon
          await sleep(350);
          window.pinCellAt(2.35, 48.86);   // paris
          await sleep(350);
          window.pinCellAt(12.5, 41.9);    // rome
          await sleep(350);
          if (pinnedCells.size !== 3) pinFailures++;
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
          if (pinnedCells.size !== 0) pinFailures++;
          await sleep(250);
        }
        multi.checked = false;
        multi.dispatchEvent(new Event('change', { bubbles: true }));
      });
    pinResult.pinFailures = pinFailures;
    results.push(pinResult);
    window.clearAllPins();
  } else {
    console.log('[IBENCH] pin-interaction skipped (no window.pinCellAt — pre-pin build)');
    results.push({ scenario: 'pin-interaction', skipped: true });
  }

  if (ltObserver) ltObserver.disconnect();

  const ranked = results
    .filter(result => !result.skipped)
    .map(result => ({
      scenario: result.scenario,
      wallMs: result.wallMs || 0,
      maxFrameMs: result.maxFrameMs || 0,
      blockingMs: result.blockingMs || 0,
      longTaskTotalMs: result.longTaskTotalMs || 0,
      chunks: result.resources?.chunks || 0,
    }));
  const rankings = {
    slowestByWall: ranked.slice().sort((a, b) => b.wallMs - a.wallMs),
    worstFrameStalls: ranked.slice().sort((a, b) => b.maxFrameMs - a.maxFrameMs),
    mostMainThreadBlocking: ranked.slice().sort((a, b) => b.longTaskTotalMs - a.longTaskTotalMs),
  };

  const run = {
    kind: 'interaction-bench',
    timestamp: new Date().toISOString(),
    userAgent: navigator.userAgent,
    devicePixelRatio: window.devicePixelRatio,
    viewport: { w: window.innerWidth, h: window.innerHeight },
    postMs: POST_MS,
    startup,
    layout: {
      horizontalOverflowPx: Math.max(0,
        document.documentElement.scrollWidth - document.documentElement.clientWidth),
      mapWidth: Math.round(document.getElementById('map').getBoundingClientRect().width),
    },
    results,
    rankings,
  };

  console.log('\n[IBENCH] ========== RESULTS ==========');
  console.table(results);

  showStatus('INTERACTION BENCH COMPLETE — see console');
  setTimeout(() => { if (overlay.parentNode) overlay.remove(); }, 5000);

  // restore sane view
  map.jumpTo({ center: BRISTOL, zoom: 4, bearing: 0, pitch: 0 });

  window._lastInteractionBench = run;
  return run;
};
