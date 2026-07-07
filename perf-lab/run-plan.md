# perf-lab run plan — ordered checklist for the orchestrator

Execute via the shared playwright-mcp headless chromium (:8003). Full methodology +
thresholds: `perf-lab/benchmark.md`. Probe: `perf-lab/instrument.js`.

Pi caveat: headless chromium here renders via SwiftShader (software GL). FPS numbers are a
relative regression signal on this box, not user-facing UX. Absolute UX numbers need a
laptop-class run of the same plan (any chrome, paste instrument.js in devtools console).

## 0. serve

```bash
cd ~/repos/jetSpan && ./start.sh &   # python http.server on :8765
curl -sI http://localhost:8765/isochrone.html | head -1   # expect 200
```
(file:// will NOT work — the app fetches `data/*.json`.)

## 1. navigate + let it settle

- `browser_navigate` → `http://localhost:8765/isochrone.html`
- `browser_wait_for` the loading overlay to clear (text "Calculating travel times..." gone),
  or just wait ~10-30 s on the pi. The base data alone is ~8 MB.
- optional sanity: `browser_console_messages` should show
  `[JetSpan] Loaded ... airports` and `Loaded pre-computed isochrone for bristol: ... cells`.

## 2. inject the probe

- Read `perf-lab/instrument.js` and pass its full text to `browser_evaluate` /
  `browser_run_code` (wrap as needed — it's a self-executing IIFE, returns nothing).
- Verify: evaluate `typeof window.__perf === 'object' && window.__perf.__installed` → true.
- Idempotent: re-injecting later (e.g. after a tab hiccup) is safe. But a page RELOAD wipes
  it — re-inject after any navigation.
- Injection is post-load, so `report().paint` + `coldLoad` still carry the real cold-load
  numbers (buffered observers); `marks.injectToFirstIdleMs` is the map-interactive proxy.

## 3. baseline snapshot before stressing

- evaluate `JSON.stringify(__perf.report())` → save as `perf-lab/results/<date>-baseline.json`
  (mkdir results/ if absent). This captures cold load, FCP/LCP, env, GL renderer, and any
  op timings the page racked up while settling.

## 4. drive the scenarios (one evaluate each; AWAIT each before the next)

Order matters — cheap/read-only first, theme-cycle (basemap refetch) last:

| step | evaluate | budget (pi) |
|---|---|---|
| 4.1 | `await __perf.runStress('zoomLadder')` | ~2-4 min |
| 4.2 | `await __perf.runStress('worldView')` | ~1-3 min (the 109k-cell whale) |
| 4.3 | `await __perf.runStress('hoverStorm')` | <1 min |
| 4.4 | `await __perf.runStress('lineStyleThrash')` | seconds |
| 4.5 | `await __perf.runStress('paletteThrash')` | ~1-2 min |
| 4.6 | `await __perf.runStress('colorscaleSpam')` | ~2-5 min on pi — this is the jank probe |
| 4.7 | `await __perf.runStress('cameraTour')` | ~1-2 min |
| 4.8 | `await __perf.runStress('globeSpin')` | ~30 s |
| 4.9 | `await __perf.runStress('themeCycle')` | ~2-5 min, network-heavy |

Each call returns its own result JSON immediately — log it as you go. If an evaluate times
out on the MCP side, the scenario keeps running in-page; poll
`__perf.stress['<name>']` until it has an `at` field.
`runStress('all')` runs 4.1-4.8 unattended (skips themeCycle) if you prefer one long call.

Repeat the matrix cells that need variants:
- colorScale in modern + dark themes: `applyTheme('modern')` (evaluate, await
  `__perf.runStress('colorscaleSpam')`), same for `'dark'`, then `applyTheme('vintage')`.

## 5. collect

- evaluate `JSON.stringify(__perf.report())` → save `perf-lab/results/<date>-full.json`.
- also grab `browser_console_messages` — the app self-logs `[PERF] Direct render res N: ...`
  and `[JetSpan] Loaded X rN cells in Yms` lines that cross-check the probe.
- optional cross-check: evaluate `await runBenchmark()` (the app's built-in grid-gen bench,
  isochrone.html:2778) and save `window._lastBench`.

## 6. interpret

Compare against the thresholds table in `benchmark.md` section 4. Reading guide:

- `stress.worldView` — expect cells ≈ 109,470 and `ops.generateHexGridDirect` /
  `smoothGridTimes` / `buildContourGeoJSON` to dominate. If `buildContourGeoJSON.totalMs`
  is the largest line, bottleneck #2 (cumulative dissolve) is confirmed.
- `stress.colorscaleSpam` — the headline: `msPerEvent` vs threshold, `fps.avgFps` during
  drag, and `ops.buildContourGeoJSON.calls` (should equal events — proof there's no
  debounce; that's iteration candidate #1's before-number).
- `stress.lineStyleThrash` — control: msPerSwitch should be ~ms-level. If it isn't,
  something is wrong with the run (thermal throttle, another heavy proc — check
  `vcgencmd measure_temp`, `free -m`).
- `stress.paletteThrash` vs lineStyleThrash — the gap between them IS the cost of
  recolor+setData+dissolve vs paint-only; iteration candidate #2's before/after metric.
- `stress.zoomLadder` — per-tier cells + updateGrid ms; the z2.5 row should stick out
  (full-world res4). r5/r6 rows show `loadChunksForViewport` + `network['hex-chunks']`.
- `report().longtasks` — total blocked ms across the session; pair with fpsRuns.
- `report().network` — basemap-tiles bucket sanity (theme switches refetch; palette
  switches must NOT add tile fetches — if they do, that's a new bug).
- `camera[]` — settleToIdleMs after flyTo legs = the "map is usable again" number.

Regression protocol for iteration: fix one candidate (benchmark.md section 6), re-run
steps 1-5 on the SAME box, diff the two `results/*.json` (jq the op avgs + stress
headlines). One variable at a time.
