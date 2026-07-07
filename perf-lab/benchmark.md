# jetSpan isochrone.html — performance benchmark methodology

Target: `~/repos/jetSpan/isochrone.html` (3,673 lines, single-file MapLibre GL v5 globe app).
Serve via `./start.sh` (python http.server on **:8765**) — `file://` fails, the app `fetch()`es local data.
Companion files: `perf-lab/instrument.js` (injectable probe), `perf-lab/run-plan.md` (execution checklist).

## 0. Corrected premises (read before trusting the task brief)

1. **There is NO live OSRM routing call in this app.** Zero references to
   `router.project-osrm.org` in any html in the repo. OSRM was used *offline* by the data
   pipeline; at runtime "OSRM" is just a per-cell boolean (`cellData.g`) driving the
   red/green coverage toggle (line 3638) and tooltip source tags. The "OSRM round-trip on
   click" scenario is replaced by the app's real interactive ops:
   - **hover route-line render** (`mousemove` on `hexgrid-fill`, lines 2153-2166: JSON.parse
     of stringified props + `route-line` setData + `showTooltip` innerHTML — *every* mousemove,
     no throttle), and
   - **r5/r6 gzip chunk fetches** (`loadChunksForViewport`, lines 912-957 — the only runtime
     network round-trips besides basemap tiles).
2. There's no click handler at all — all interaction is hover + UI controls.
3. The app already ships a built-in `runBenchmark()` (line 2778) and `runTests()` (line 2945).
   They cover grid-*generation* timing only (not recolor, not contours, not FPS, not paint).
   `instrument.js` complements rather than duplicates them; the built-in bench remains useful
   as a cross-check for `generateHexGrid` numbers.

## 1. The dataset (measured, 2026-07-06)

| res | cells | delivery | selected at zoom |
|---|---|---|---|
| 1 | 321 | base `bristol.json` (8.0 MB) | z < 1 |
| 2 | 2,227 | base | 1 ≤ z < 2 |
| 3 | 15,633 | base | **never** — `getResolutionForZoom` (2112-2119) skips it |
| 4 | **109,470** | base | 2 ≤ z < 4.5 |
| 5 | lazy | 504 gzip chunks (`data/isochrones/bristol/r5/`) | 4.5 ≤ z < 6.5 |
| 6 | lazy | 2,838 gzip chunks (`r6/`) | z ≥ 6.5 |

**The killer interaction:** `updateGrid` only computes `viewportBounds` when `zoom >= 3`
(line 2714), but res 4 is selected from z = 2. So **any view at 2 ≤ z < 3 builds the FULL
109,470-cell world**: `generateHexGridDirect` iterates every cell (`cellToLatLng` +
`parseCellData` + `cellToBoundary` per cell), then `smoothGridTimes` runs a 3-pass
`gridDisk` blur (~2.3M h3 neighbor lookups), then `buildContourGeoJSON` runs 9 *cumulative*
`cellsToMultiPolygon` dissolves, then a ~110k-polygon GeoJSON goes through `setData`
(worker tessellation). This is the worldwide-scale stress case.

## 2. Metric set

Collected by `instrument.js` into `window.__perf.report()`:

| metric | source | notes |
|---|---|---|
| cold load: DOMContentLoaded, load | Navigation Timing (buffered) | valid even when injected post-load |
| first-paint / first-contentful-paint / LCP | PerformanceObserver `paint`/`largest-contentful-paint`, buffered | FMP proxy = FCP; map-ready proxy = first `idle` |
| time-to-interactive proxy | inject-to-first-map-`idle` + longtask census | true TTI needs pre-nav injection; see run-plan |
| per-op latency | wrapped globals (count/total/max/last-300 samples) | `generateHexGridDirect`, `smoothGridTimes`, `buildContourGeoJSON`, `buildCentroidGeoJSON`, `refreshGridDerived`, `recolorGrid`, `updateGrid`, `applyTheme(Chrome)`, `setVintagePalette`, `setLineStyle`, `applyLineStylePaint`, `loadChunksForViewport`, `showTooltip`, `buildRouteGeoJSON` |
| hot-path call counts | counter-only wraps (no per-call clock — 110k `performance.now()` calls would distort) | `getTimeBandColor`, `getBandIndex`, `parseCellData`, `displayMinutes`, `hexLerp` |
| FPS during camera moves + slider drag | rAF frame-delta sampler | avg fps, p95 frame ms, worst frame, frames > 50 ms |
| main-thread jank | PerformanceObserver `longtask` | count + total blocked ms per scenario |
| network | PerformanceObserver `resource`, bucketed | openfreemap tiles / data chunks / core json / CDN libs; count, ms, transferSize |
| memory | `performance.memory` (Chromium-only) | JS heap before/after world-view stress |
| camera settle | wrapped `jumpTo`/`flyTo`/`easeTo` → `moveend` → `idle` | move ms + settle-to-idle ms |

## 3. Test matrix

All cells run at origin=bristol, default theme=vintage unless noted. 3 reps per cell,
report median. `S:` = driven by `__perf.runStress(name)`.

| # | operation | variants | scenario |
|---|---|---|---|
| M1 | cold load → first idle | vintage (default) | navigate + inject; `report()` |
| M2 | zoom ladder z 0.5→6.5 (real pipeline: moveend debounce → updateGrid) | — | `S: zoomLadder` |
| M3 | worldwide res-4 full build (z 2.5, no viewport bounds) | — | `S: worldView` |
| M4 | palette switch | heatmap→monowarm→viridis→galton (vintage only) | `S: paletteThrash` (also 1-shot timings in ops) |
| M5 | line-style switch | washes→contours→layered (vintage only) | `S: lineStyleThrash` — expect ~free (paint-props only, 1666-1692) |
| M6 | colorScale drag | 0.5→4.0→1.0 sweep, per-`input`-event cost + FPS | `S: colorscaleSpam` |
| M7 | theme switch (full basemap reload, `setStyle diff:false` line 1796) | vintage→modern→dark→vintage | `S: themeCycle` (network-heavy, run last) |
| M8 | camera flights + settle | bristol→NYC→tokyo→sydney→bristol flyTo | `S: cameraTour` |
| M9 | globe rotation FPS | z1.8, 12 easeTo bearing/lng steps | `S: globeSpin` |
| M10 | hover storm (tooltip + route-line per event) | 40 random cells | `S: hoverStorm` |
| M11 | chunk loading r5/r6 | captured inside M2 via `loadChunksForViewport` timings + resource bucket | — |

colorScale (M6) should additionally be run once in each theme: vintage recolors + rebuilds
contours; modern rebuilds the centroid field (`buildCentroidGeoJSON` 2039); dark recolors
extrusions — three different cost profiles from one slider.

### Stress scenarios (what each runStress drives)

- `worldView` — jumpTo z2.5 over Bristol → full 109k-cell pipeline; wall-to-idle, ops delta, heap delta.
- `zoomLadder` — jumpTo each of z 0.5/1.5/2.5/3.5/4.5/5.5/6.5, wait out the 350 ms moveend debounce (2199-2202) + idle; per-step cells + updateGrid ms.
- `colorscaleSpam` — ~70 slider `input` dispatches at 16 ms spacing (simulated drag); per-event `recolorGrid` cost, FPS, longtasks.
- `paletteThrash` — 3 fast cycles through all 4 palettes; per-switch cost + FPS.
- `lineStyleThrash` — 10 cycles through 3 line styles; control case (should stay cheap).
- `cameraTour` / `globeSpin` — FPS + settle during flyTo chain / continuous rotation.
- `hoverStorm` — 40 synthetic hovers replaying the exact mousemove-handler work.
- `themeCycle` — 3 full basemap swaps waiting for idle each (network + layer re-add).

## 4. Thresholds ("good" / "concerning")

Laptop-class = mid-range x86/ARM laptop, hardware WebGL. Pi-class = RPi5-4GB; NB a
**headless** chromium on the pi renders via SwiftShader (software GL) — FPS there measures
CPU rasterization, not what a pi-attached display with GPU accel would do. Interpret
pi FPS as a relative regression signal, not absolute UX.

| metric | laptop good | laptop concerning | pi good | pi concerning |
|---|---|---|---|---|
| cold load → first map idle | < 5 s | > 12 s | < 20 s | > 45 s |
| FCP | < 1.5 s | > 4 s | < 5 s | > 12 s |
| `generateHexGridDirect` res4 world (M3) | < 400 ms | > 1.5 s | < 3 s | > 10 s |
| `smoothGridTimes` res4 world | < 600 ms | > 2 s | < 5 s | > 15 s |
| `buildContourGeoJSON` res4 world | < 900 ms | > 3 s | < 7 s | > 20 s |
| M3 total wall-to-idle | < 3 s | > 8 s | < 15 s | > 40 s |
| colorScale: one `input` event (vintage, res4 regional z4) | < 120 ms | > 400 ms | < 800 ms | > 3 s |
| colorScale drag FPS | ≥ 20 | < 8 | ≥ 4 | < 1 |
| palette switch (vintage) | < 300 ms | > 1 s | < 2 s | > 6 s |
| line-style switch | < 16 ms | > 100 ms | < 60 ms | > 300 ms |
| theme switch wall-to-idle | < 2.5 s | > 8 s | < 10 s | > 30 s |
| camera flyTo FPS | ≥ 30 | < 15 | ≥ 5 | < 2 |
| settle-to-idle after flyTo | < 1.5 s | > 5 s | < 6 s | > 20 s |
| hover event (tooltip + route line) | < 8 ms | > 33 ms | < 30 ms | > 100 ms |
| r5 chunk load (per viewport batch) | < 800 ms | > 3 s | < 2 s | > 8 s |
| longtasks during any single scenario | < 5 / < 1 s total | > 20 / > 5 s | < 15 / < 8 s | > 50 / > 30 s |
| JS heap after M3 | < 700 MB | > 1.2 GB | < 700 MB | > 1.2 GB (earlyoom risk) |

## 5. Likely bottlenecks, ranked (from code reading — to be confirmed by numbers)

1. **colorScale `input` handler does the full recolor + contour dissolve per slider tick**
   (listener 3644-3650 → `recolorGrid` 1873-1885 → `setData` of the whole grid +
   `refreshGridDerived` 2090 → `buildContourGeoJSON` 1997-2035). No debounce anywhere. A drag
   emits dozens of `input` events; each one loops every feature through `getTimeBandColor`,
   re-serializes ~110k polygons into the geojson worker, and re-dissolves 9 cumulative band
   sets with `h3.cellsToMultiPolygon`. This is the #1 predicted jank source, and it degrades
   quadratically with visible cell count.

2. **`buildContourGeoJSON`'s cumulative dissolve** (1997-2035). `cumulative = cumulative.concat(buckets[i])`
   then `cellsToMultiPolygon(cumulative)` for bands 0..8 — band 8's dissolve processes nearly
   the whole dataset, so total work ≈ 9× a full-set dissolve. Runs on *every* grid change,
   recolor, and colorScale tick (via `refreshGridDerived`). At 109k cells this is likely the
   single most expensive function in the app.

3. **Full-world res-4 build at 2 ≤ z < 3** — the `viewportBounds` gate at `zoom >= 3`
   (2714) mismatches the res-4 selection at z ≥ 2 (2116). 109,470 × (`cellToLatLng` +
   `parseCellData` + `cellToBoundary` + antimeridian fixup) in `generateHexGridDirect`
   (1085-1187), followed by bottleneck #4 and #2 on the full set, then a ~50 MB+ GeoJSON
   `setData`. Also the memory high-water mark.

4. **`smoothGridTimes` 3-pass neighbor blur** (1940-1970): 3 × N × `h3.gridDisk(cell,1)`
   ≈ 2.3M h3 calls + Map churn at res-4 world. Recomputed from scratch on every `updateGrid`
   (2741) even though the result only depends on the cell set — pan within the same loaded
   set recomputes identical values.

5. **Unthrottled `mousemove` hover work** (2153-2166): per pointer event — 3× `JSON.parse`
   (props arrive stringified by maplibre), `buildRouteGeoJSON` + `route-line` setData, and
   `showTooltip` (3458-3541) rebuilding innerHTML. Fine on a laptop, likely visible drag on
   pi-class pointer interaction.

6. **Theme switch reloads the entire basemap** (`applyTheme` 1777-1803, `setStyle(..., {diff:false})`
   at 1796 — deliberate, commented) + `tuneBasemapForTheme` iterating every style layer twice
   (2217-2241, re-run on `idle` at 2639). Bounded but the heaviest single UI action; palette
   switching correctly avoids it (1639-1651) — worth verifying the palette path never
   accidentally triggers tile refetch.

7. **`getTimeBandColor` per-cell scan** (1852-1870): loops ≤ 10 bands with a multiply per
   band per call, ×110k calls per recolor. Cheap individually; only matters because of how
   often callers invoke it. Fix belongs in the callers (see below) or precomputed scaled
   thresholds.

## 6. Iteration candidates (proposals only — isochrone.html NOT edited)

1. **Debounce the colorScale slider + split cheap/expensive work** (listener 3644-3650).
   Update the label per `input`; run `recolorGrid` at most every ~100 ms trailing; defer
   `buildContourGeoJSON`/`refreshGridDerived` to the `change` event (drag release) or a 250 ms
   idle. Expected win: drag goes from N×(recolor+dissolve) to ~a few recolors + exactly one
   dissolve — order-of-magnitude jank reduction, zero visual cost beyond contours lagging the
   wash by a beat.

2. **Move band coloring to a GPU-side style expression instead of per-feature `color` writes.**
   `wash-bands` uses `'fill-color': ['get','color']` (2317) forcing recolor = rewrite 110k
   feature props + full `setData` (1873-1885). Replace with a `['step', ['get','smoothTimeMinutes'], ...]`
   expression built from `TIME_BANDS × colorScale`; palette AND colorScale switches become one
   `setPaintProperty` call — no setData, no re-tessellation. (Contours still need a rebuild on
   colorScale since band *membership* moves, but washes/relief/field-color become ~free.)
   Expected win: palette switch ~O(1); colorScale recolor cost drops ~95%. The OSRM-coverage
   toggle can be its own boolean-driven expression.

3. **Incremental / cached contour dissolve** (1997-2035). Cache per-band `cellsToMultiPolygon`
   results keyed by (cell-set identity, band bucketing). On colorScale change only bands whose
   membership changed need re-dissolving; on pure palette change, nothing does (colors live in
   paint, not geometry — pair with #2). Also consider dissolving per-band (non-cumulative) and
   stacking rings visually. Expected win: removes the ~9× multiplier; typical recolor skips
   dissolve entirely.

4. **Memoize `smoothGridTimes` by cell-set** (1940-1970, called at 2741). Key: resolution +
   loadedChunks size (or a cheap hash of feature count + first/last h3 index). Pan/zoom within
   an already-smoothed set skips ~2.3M h3 calls. Alternatively precompute smoothed values into
   the data pipeline (they're camera-independent). Expected win: removes #4 entirely from the
   interactive path.

5. **Close the z 2→3 viewport gap** (2714 vs 2116): either lower the bounds gate to z ≥ 2
   (globe `getBounds` is unreliable at low zoom — so clamp to a generous hemisphere box from
   center instead), or serve the never-used res-3 data (15,633 cells) for 2 ≤ z < 3.
   Expected win: worldwide view drops from 109k to ≤ 16k cells — ~7× on every full-build
   metric, and the biggest memory saving available.

Bonus (cheap): throttle the hover handler with a rAF gate (2153) and precompute
`TIME_BANDS` scaled thresholds in minutes once per colorScale change instead of
`band.maxHours * colorScale` per cell per band (1858, 1985).
