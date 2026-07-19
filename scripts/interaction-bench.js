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
      maxFrameMs: ft.length ? +ft[ft.length - 1].toFixed(2) : 0,
      jankPct: ft.length ? +((ft.filter(t => t > 33.4).length / ft.length) * 100).toFixed(1) : 0,
      longTasks: longTasks.length,
      longTaskTotalMs: +longTasks.reduce((s, t) => s + t, 0).toFixed(0),
    };
  }

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

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
    await sleep(600); // outlast the 350ms updateGrid debounce
    await Promise.race([
      new Promise(r => map.once('idle', r)),
      sleep(4000),
    ]);
    await sleep(200);
  }

  async function scenario(name, setupFn, actionFn) {
    showStatus(`SCENARIO: ${name} — setting up...`);
    await setupFn();
    await settle();
    showStatus(`SCENARIO: ${name} — measuring...`);
    startSampling();
    await actionFn();
    await sleep(POST_MS); // capture post-interaction grid regen cost
    const m = stopSampling();
    m.scenario = name;
    console.log(`[IBENCH] ${name}: ${m.fps}fps avg=${m.avgFrameMs}ms p95=${m.p95FrameMs}ms jank=${m.jankPct}% longTasks=${m.longTasks}/${m.longTaskTotalMs}ms`);
    return m;
  }

  const BRISTOL = [-2.5879, 51.4545];
  const results = [];

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

  // --- 3. zoom sweep in and out (crosses every res threshold) ---
  results.push(await scenario('zoom-in-out',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 1.5, bearing: 0, pitch: 0 }); },
    async () => {
      await ease({ zoom: 7 }, 2500);
      await ease({ zoom: 1.5 }, 2500);
    }));

  // --- 4. globe rotation (longitude spin at low zoom, globe projection) ---
  results.push(await scenario('rotate-globe',
    async () => { map.jumpTo({ center: [0, 30], zoom: 2, bearing: 0, pitch: 0 }); },
    async () => {
      await ease({ center: [120, 30] }, 1500);
      await ease({ center: [-120, 30] }, 1500);
      await ease({ center: [0, 30] }, 1500);
    }));

  // --- 5. bearing spin at mid zoom (rotation with dense cells on screen) ---
  results.push(await scenario('bearing-spin-z5',
    async () => { map.jumpTo({ center: BRISTOL, zoom: 5, bearing: 0, pitch: 0 }); },
    async () => {
      await ease({ bearing: 180 }, 1200);
      await ease({ bearing: 360 }, 1200);
    }));

  // --- 6. pin interaction (only if the click-to-pin feature exists) ---
  if (typeof window.pinCellAt === 'function' && typeof window.clearAllPins === 'function') {
    results.push(await scenario('pin-interaction',
      async () => {
        window.clearAllPins();
        map.jumpTo({ center: [2.0, 47.0], zoom: 4.4, bearing: 0, pitch: 0 });
      },
      async () => {
        // 3 rounds of pin 3 cells + clear — measures pin render + card DOM cost
        for (let round = 0; round < 3; round++) {
          window.pinCellAt(-9.14, 38.72);  // lisbon
          await sleep(350);
          window.pinCellAt(2.35, 48.86);   // paris
          await sleep(350);
          window.pinCellAt(12.5, 41.9);    // rome
          await sleep(350);
          window.clearAllPins();
          await sleep(250);
        }
      }));
    window.clearAllPins();
  } else {
    console.log('[IBENCH] pin-interaction skipped (no window.pinCellAt — pre-pin build)');
    results.push({ scenario: 'pin-interaction', skipped: true });
  }

  if (ltObserver) ltObserver.disconnect();

  const run = {
    kind: 'interaction-bench',
    timestamp: new Date().toISOString(),
    userAgent: navigator.userAgent,
    devicePixelRatio: window.devicePixelRatio,
    viewport: { w: window.innerWidth, h: window.innerHeight },
    postMs: POST_MS,
    results,
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
