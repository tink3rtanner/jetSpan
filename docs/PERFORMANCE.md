# JetSpan Performance Documentation

## Overview

This document tracks performance benchmarks for the JetSpan flight isochrone visualization.
Benchmarks should be re-run after significant changes to measure improvement/regression.

## How to Benchmark

Built into `isochrone.html` — open browser console after page loads:

```javascript
// run benchmark (green overlay shows progress)
await runBenchmark()

// compare against a baseline
await benchLoadBaseline('docs/benchmarks/2026-01-29-baseline.json')
await runBenchmark()       // prints diff table vs baseline

// save results to commit
benchExport('my-label')    // downloads JSON file → commit to docs/benchmarks/
```

Tests: 14 zoom levels (z0.5–z7) + 4 pan targets × 3 zooms. Each test: 1 warm-up + 3 measured runs.

Baseline file: `docs/benchmarks/2026-01-29-baseline.json`

---

## Benchmark Results

### 2026-01-28 - Baseline (On-Demand Computation)

**Hardware**: MacBook (darwin 25.2.0)
**Data**: 4,518 airports, 58,359 routes

#### Zoom Suite (Bristol origin, z5)

| Zoom | Resolution | Cells | Time | ms/cell |
|------|------------|-------|------|---------|
| 0.8 | 1 (globe) | 331 | 15.8s | 47.6 |
| 1.5 | 2 | 2,291 | 19.0s | 8.3 |
| 2.5 | 3 | 15,949 | 31.3s | 2.0 |
| 4.0 | 4 | 7,937 | 18.4s | 2.3 |
| 5.5 | 5 | 6,280 | 29.4s | 4.7 |
| 7.0 | 6 | 5,574 | 22.4s | 4.0 |

**Slowest**: z2.5 continental view (31.3s) due to high cell count

#### Pan Suite (z5)

| Location | Time | Cells | ms/cell |
|----------|------|-------|---------|
| Tokyo | 19.6s | 2,395 | 8.2 |
| Sydney | 21.3s | 1,951 | 10.9 |
| Los Angeles | 21.9s | 1,922 | 11.4 |
| Pacific Ocean | 20.6s | 300 | 68.8 |

**Note**: Pacific Ocean has very few cells due to water skip optimization

#### Cache Effectiveness

| Test | Cold | Warm | Speedup |
|------|------|------|---------|
| Bristol | ~40s | ~13s | 3x |
| Paris | ~15s | ~12s | 1.25x |
| Berlin | ~18s | ~12s | 1.5x |

---

## Optimizations Applied

### 1. Resolution 1 for Far Globe (commit 4c58768)

**Change**: Use H3 resolution 1 for zoom < 1.5
**Impact**: Globe view 26s → 14s (2x faster), cells 13k → 331

### 2. Water Cell Skip (commit 6e13f4c)

**Change**: Skip cells >300km from nearest airport
**Impact**: ~35% faster for oceanic views (Cape Town 28s → 18s)

### 3. Travel Time Cache

**Change**: Cache results by H3 cell index
**Impact**: ~3x faster on revisits (40s → 13s for cached)

### 4. Spatial Index for Airports

**Change**: H3 res 3 index for fast nearest-airport lookup
**Impact**: Reduced O(n) airport search to O(1) area lookup

---

## Planned Optimizations

### Pre-computed Isochrones (IMPLEMENTED)

Pre-compute travel times as static JSON per origin city using dijkstra routing.

```
data/isochrones/bristol.json  (8.7 MB, 143,077 cells)
{
  "origin": "bristol",
  "resolutions": {
    "1": { "h3index": {"t": 180, "o": "BRS", "a": "JFK", "s": 0}, ... },
    "2": { ... },
    "3": { ... },
    "4": { ... }
  }
}
```

Compact format `{t, o, a, s}` = time, origin airport, dest airport, stops.
Breakdown derived client-side by `parseCellData()`.

**Actual Impact**:
- With grid iteration lookup: No improvement (still iterating all viewport cells)
- With direct rendering (hybrid): ~100x speedup for res 1-4

### Web Workers (Priority: Medium)

Offload computation to background thread to avoid UI blocking.
Only relevant for res 4-6 now since res 1-3 use direct rendering.

### Progressive Rendering (Priority: Low)

Render low-res first, then upgrade to high-res.
Less important now that res 1-3 are fast via direct rendering.

---

## Legacy Test Suite

`scripts/performance-tests.js` — older external benchmark, predates the built-in one.
Mostly obsolete but kept for reference.

---

## Performance Goals

| Metric | Before | Target | After (Hybrid) | Status |
|--------|--------|--------|----------------|--------|
| Initial render res 1-3 | 15-40s | <5s | **<15ms** | ✅ EXCEEDED |
| Initial render res 4+ | 15-40s | <5s | 3-5s | ✅ MET |
| Cached render | ~12s | <2s | **<15ms** | ✅ EXCEEDED |
| Pan (zoomed out) | ~20s | <3s | **<15ms** | ✅ EXCEEDED |
| Pan (zoomed in) | ~20s | <3s | 3-5s | ✅ MET |
| Zoom level change | ~15-30s | <2s | **<15ms** | ✅ EXCEEDED |

**Ultimate goal achieved**: Pre-computed JSON + direct rendering = instant for res 1-4

---

## Session Notes (2026-01-28 late)

### Pre-compute Expansion (res 1-4, per-cell routing)

Initial expansion from res 1-3 to res 1-4 using per-cell routing (before dijkstra):

| Resolution | Global cells | Computed | Skipped | Time |
|------------|-------------|----------|---------|------|
| 1 | 842 | 46 | 796 | 2.9s |
| 2 | 5,882 | 344 | 5,538 | 19.9s |
| 3 | 41,162 | 2,348 | 38,814 | 137.5s |
| 4 | 288,122 | 16,252 | 271,870 | 934.2s |

**Total:** 18 min compute, **3.5 MB** file, **18,990 cells** (direct flights only)

---

## 2026-01-29 - Dijkstra Integration

### Precompute with Dijkstra Routing

Rewrote `precompute-isochrone.py` to use `dijkstra_router.py` directly:
- dijkstra runs once (0.3s), builds spatial index of 3139 reachable airports
- per-cell lookup via h3 res-2 spatial buckets (~50 airports checked per cell vs ~3k)
- multi-stop connections: 338 direct + 2156 one-stop + 645 two-stop

| Resolution | Global cells | Computed | Skipped | Time |
|------------|-------------|----------|---------|------|
| 1 | 842 | 355 | 487 | 0.1s |
| 2 | 5,882 | 2,500 | 3,382 | 0.5s |
| 3 | 41,162 | 17,515 | 23,647 | 2.6s |
| 4 | 288,122 | 122,707 | 165,415 | 7.2s |

**Total:** 10.7s compute, **8.7 MB** file, **143,077 cells**

### Improvement vs Per-Cell Routing

| Metric | Per-cell (old) | Dijkstra (new) | Change |
|--------|---------------|----------------|--------|
| Compute time | 18 min | 10.7s | **100x faster** |
| Cells computed | 18,990 | 143,077 | **7.5x more** |
| Airports reachable | ~375 (direct) | 3,139 (multi-stop) | **8.4x more** |
| File size | 3.5 MB | 8.7 MB | 2.5x (compact format) |

### Compact JSON Format

To keep file under 10 MB, switched from verbose to compact format:
- Verbose: `{time, route: {originAirport, destAirport, isDirect, ...}}` — 35.6 MB
- Compact: `{t, o, a, s}` (time, origin airport, dest airport, stops) — 8.7 MB
- Drive-only cells: `{t, d: 1}`
- Breakdown derived client-side by `parseCellData()` in isochrone.html

### UI Render Performance (Chrome verified)

| Resolution | Cells rendered | Render time |
|------------|---------------|-------------|
| res 3 (continental) | 17,515 | 56ms |
| res 4 (regional) | 9,759 visible | 84ms |

---

## Pre-computed Data Analysis (2026-01-28)

### Implementation

Pre-computed isochrone data is now generated and loaded:
- `data/isochrones/bristol.json` - 2,738 cells across res 1-3
- Loaded automatically on page init
- Used as fast lookup before on-demand computation

### Results

**Pre-computed cells by resolution:**
| Resolution | Cells | Coverage |
|------------|-------|----------|
| 1 (globe) | 46 | Land near airports |
| 2 (continental) | 344 | Land near airports |
| 3 (regional) | 2,348 | Land near airports |

**Performance comparison (grid iteration lookup - deprecated):**

| Test | Before | After | Notes |
|------|--------|-------|-------|
| Globe z0.8 | 15.8s | 19.2s | No improvement |
| z1.5 | 19.0s | 21.0s | No improvement |

### 2026-01-28 - Hybrid Direct Rendering

**Implementation**: Direct render pre-computed cells for res 1-4, skip grid iteration entirely.

| Resolution | Cells | Before (grid) | After (direct) | Speedup |
|------------|-------|---------------|----------------|---------|
| res 1 (globe) | 355 | 15.8s | **<1ms** | ∞ |
| res 2 (continental) | 2,500 | 19.0s | **~5ms** | ~4000x |
| res 3 (regional) | 17,515 | 31.3s | **56ms** | ~560x |
| res 4 (regional) | 122,707 | N/A | **84ms** | N/A |

**Key insight**: The bottleneck was grid iteration, not computation. By iterating only pre-computed cells instead of all viewport cells, we eliminate the overhead entirely.

### Historical Note: Why Grid Iteration Was Slow

The initial approach (grid iteration with pre-computed lookup) showed no improvement because:
1. Code still iterated ALL viewport cells to check against pre-computed data
2. Most cells are water/unreachable and get skipped anyway
3. Water skip optimization was already quick

**Solution (implemented)**: Direct rendering — iterate only pre-computed cells, skip grid iteration entirely. Combined with dijkstra routing for 7.5x more cell coverage.

### Current Architecture (Hybrid - Implemented)

```
HYBRID RENDERING APPROACH (updated 2026-01-29)
===============================================

res 1-4 (zoomed out, globe/continental/regional):
  1. Load pre-computed cells for resolution (dijkstra + compact JSON)
  2. Filter to viewport bounds
  3. Render directly (no grid iteration)
  -> O(pre-computed cells) = ~143k total across 4 resolutions
  -> Actual: <100ms

res 5-6 (zoomed in, local views):
  1. Iterate cells in viewport grid
  2. For each cell:
     a. Check cache
     b. Water skip (>400km from airport)
     c. Compute on-demand
  -> O(viewport cells) but viewport is smaller when zoomed in
  -> Acceptable: few seconds

WHY HYBRID?
- Grid iteration is slow because we check ALL viewport cells
- Pre-computed data covers res 1-4 (~143k cells globally, 8.7 MB)
- Res 5 would require 2M+ cells, ~52 MB — needs file splitting or selective compute
- When zoomed in, viewport has fewer cells anyway so grid iteration is tolerable
```

### Trade-offs

| Approach | Pros | Cons |
|----------|------|------|
| Direct render (res 1-4) | Near-instant, no iteration | Only shows pre-computed cells |
| Grid iteration (res 5+) | Gap-free coverage, dynamic | Slow for large viewports |

**What you lose with direct rendering:**
- Cells not in pre-computed set won't render (gaps if bugs in pre-compute)
- Can't dynamically switch origins without pre-computing each one
- Higher resolutions need separate pre-compute runs

**What you gain:**
- 100x+ speedup for zoomed-out views (15s → <100ms)
- Predictable performance
- Eliminates grid iteration overhead entirely for res 1-4

---

## 2026-01-29 — Benchmark Tooling & Threshold Tuning

### Built-in Benchmark

`runBenchmark()` is now built into `isochrone.html`. Call from browser console.

- Waits for isochrone data to load before running
- Shows green overlay with live status during run
- Phase 1: zoom sweep (z0.5–z7, 14 steps) centered on origin
- Phase 2: pan tests (4 cities × 3 zoom levels = 12 tests)
- Each test: 1 warm-up run + 3 measured runs → reports avg/min/max
- Results stored in `window._lastBench`, logged via `console.table()`

### Zoom Threshold Changes

Shifted precomputed resolutions to kick in earlier (finer detail sooner).
The res 4→5 boundary is the critical cliff — precomputed ends, on-demand begins.

```
zoom   old res   new res   path
────   ───────   ───────   ───────────
<1     1         1         precomputed
<1.5   1         2         precomputed (was res 1)
<2     2         2         precomputed
<2.5   2         3         precomputed (was res 2)
<3     3         3         precomputed
<4     3         4         precomputed (was res 3)
<4.5   4         4         precomputed
<5     4         4         precomputed
<5.5   4         5 !!      ON-DEMAND (was precomputed — reverted)
<5     —         4         precomputed (final: boundary at z5)
<6.5   5         5         on-demand
<7     5         6         on-demand (was res 5)
7+     6         6         on-demand
```

Final thresholds: `1 / 2 / 3 / 5 / 6.5` (was `1.5 / 2.5 / 4 / 5.5 / 7`)

Net effect: finer precomputed cells earlier, no regression on the precomputed→on-demand cliff.

### Benchmark Results (new thresholds)

**Hardware**: MacBook (darwin 25.2.0), Chrome
**Origin**: Bristol
**Data**: bristol.json (8.7 MB, 143,077 cells, res 1-4 precomputed)

#### Zoom Sweep

| Zoom | Res | Path | Cells | Run 1 (ms) | Run 2 (ms) | Δ |
|------|-----|------|-------|------------|------------|---|
| 0.5 | 1 | precomputed | 355 | 1.6 | 1.5 | -6% |
| 1.0 | 2 | precomputed | 2,500 | 6.2 | 5.6 | -10% |
| 1.5 | 2 | precomputed | 2,500 | 6.0 | 5.7 | -5% |
| 2.0 | 3 | precomputed | 17,515 | 39.2 | 44.4 | +13% |
| 2.5 | 3 | precomputed | 17,515 | 42.9 | 43.8 | +2% |
| 3.0 | 4 | precomputed | 72,312 | 204.1 | 217.4 | +7% |
| 3.5 | 4 | precomputed | 28,141 | 112.7 | 108.0 | -4% |
| 4.0 | 4 | precomputed | 9,759 | 75.9 | 74.4 | -2% |
| 4.5 | 4 | precomputed | 4,044 | 63.3 | 62.8 | -1% |
| **5.0** | **5** | **on-demand** | **8,737** | **2,444** | **2,397** | **-2%** |
| 5.5 | 5 | on-demand | 4,507 | 354 | 352 | -1% |
| 6.0 | 5 | on-demand | 2,545 | 104.8 | 105.7 | +1% |
| 6.5 | 6 | on-demand | 8,039 | 543.7 | 546.6 | +1% |
| 7.0 | 6 | on-demand | 4,268 | 257.3 | 258.3 | +0.4% |

#### Pan Tests

| Location | z=4 precomp (ms) | z=5.5 on-demand (ms) | z=7 on-demand (ms) |
|----------|-----------------|---------------------|-------------------|
| London | 79 / 75 | 254 / 255 | 283 / 276 |
| Paris | 77 / 77 | 253 / 245 | 320 / 321 |
| Reykjavik | 64 / 65 | 332 / 326 | 177 / 171 |
| Istanbul | 92 / 89 | 373 / 363 | 386 / 392 |

(format: run 1 / run 2)

### Reproducibility

Run-to-run variance with 3-trial averaging:
- **Precomputed path**: ±5-13% on fast tests (<10ms), ±1-7% on larger (>60ms)
- **On-demand path**: ±0.1-2% — very stable
- **Cell counts**: identical both runs (deterministic)

The high % variance on fast precomputed tests (e.g. 39→44ms = +13%) is noise —
absolute delta is only ~5ms, well within JS timer granularity and GC jitter.
On-demand tests are stable bc they're slower and dominate the measurement.

### Key Insight: The Precomputed Cliff

```
              precomputed                    on-demand
         ◄──────────────────►    ◄──────────────────────────►
  z: 0.5  1  1.5  2  2.5  3  3.5  4  4.5 │ 5    5.5   6   6.5   7
 ms:   2   6   6  39  43  204 113  76  63 │ 2444  354  105  544  257
                                           │
                                    39x cliff ─┘
```

At z5.0 (res 5), render time jumps from 63ms → 2,444ms.
This is the precomputed→on-demand boundary: res 4 data exists in JSON, res 5 does not.

### Path to Full Precompute

Eliminating on-demand rendering entirely requires precomputing res 5-6.

| Res | Est cells | Est size | Compute time (est) | Notes |
|-----|-----------|----------|--------------------|-|
| 5 | ~860k | ~58 MB raw | ~30-60s | 7x res 4 cells |
| 6 | ~6M | ~400 MB raw | ~5-10 min | impractical as single file |

With water/remote filtering: res 5 likely ~500k cells, ~35 MB.

**Options to stay under GitHub Pages limits:**
1. Split by resolution — lazy-load `bristol_r5.json` when zoom crosses threshold
2. gzip — GitHub Pages serves gzip; ~60-70% compression on JSON → ~10-15 MB
3. Binary packing — `{t,o,a,s}` as fixed-width fields instead of JSON keys
4. Selective res 5 — only precompute within ~2000km of origin (covers useful zoom range)

---

## 2026-01-29 — Full Precompute (Res 1-6)

### Architecture Change: On-Demand Eliminated

All resolutions now precomputed. Client is a pure renderer — zero on-demand routing.

```
BEFORE (hybrid):
  res 1-4: precomputed JSON, direct render (<100ms)
  res 5-6: grid iteration + on-demand compute (250-2400ms)

AFTER (full precompute):
  res 1-4: precomputed base JSON, direct render (<100ms)
  res 5-6: lazy-loaded chunks per viewport, direct render (<30ms)
  route table: per-airport routing info for exact tooltip breakdown
```

**Code stripped**: `calculateTotalTravelTime`, `buildAirportSpatialIndex`,
`findNearestAirports`, `estimateFlightMinutes`, `getOSRMGroundTime`,
`loadGroundData`, `COUNTRY_TO_REGION`, `LOADED_GROUND`, `FLIGHT_TIMES`,
travel time cache, spatial index. ~400 lines removed.

### Precompute Output

| Resolution | Cells | Time | Output |
|------------|-------|------|--------|
| 1 | 355 | 0.1s | base JSON |
| 2 | 2,500 | 0.5s | base JSON |
| 3 | 17,515 | 2.6s | base JSON |
| 4 | 122,707 | 7.2s | base JSON |
| 5 | 858,921 | 82.2s | 527 chunk files |
| 6 | 6,012,353 | 469.1s | 3,042 chunk files |

**Total**: 7,014,351 cells in 551.5s (dijkstra: 0.4s, cell iteration: 551.1s)

### File Size

| Component | Size | Notes |
|-----------|------|-------|
| Base JSON (res 1-4) | 8.7 MB | loaded on init |
| Route table | 224 KB | 3,139 airports, per-leg times |
| Res 5 chunks | 52.3 MB | 527 files, grouped by res-1 parent |
| Res 6 chunks | 418.1 MB | 3,042 files, grouped by res-2 parent |
| **Total** | **479 MB** | gzip ~91% → ~43 MB |

### Chunk Loading Performance

Chunks are lazy-loaded by viewport on zoom/pan:

| Event | Chunks | Cells | Fetch time | Render time |
|-------|--------|-------|------------|-------------|
| Zoom to res 5 (Bristol) | 2 | 4,263 | 8ms | 10ms |
| Zoom to res 6 (Bristol) | 2 | 4,802 | 6ms | 8ms |

### Benchmark Results (all precomputed)

**Hardware**: MacBook (darwin 25.2.0), Chrome
**Origin**: Bristol
**Data**: 7M cells across res 1-6, route table with 3,139 airports

#### Zoom Sweep

| Zoom | Res | Cells | Avg (ms) | Min (ms) | Max (ms) | vs Old On-Demand |
|------|-----|-------|----------|----------|----------|------------------|
| 0.5 | 1 | 355 | 1.9 | 1.8 | 1.9 | — |
| 1.0 | 2 | 2,500 | 6.2 | 5.5 | 7.1 | — |
| 1.5 | 2 | 2,500 | 6.0 | 5.8 | 6.4 | — |
| 2.0 | 3 | 17,515 | 37.1 | 36.3 | 37.6 | — |
| 2.5 | 3 | 17,515 | 38.2 | 37.4 | 38.9 | — |
| 3.0 | 4 | 72,312 | 194.4 | 184.1 | 212.1 | — |
| 3.5 | 4 | 28,141 | 108.1 | 101.5 | 121.0 | — |
| 4.0 | 4 | 9,759 | 72.9 | 71.6 | 73.9 | — |
| 4.5 | 4 | 4,044 | 61.7 | 61.5 | 61.8 | — |
| **5.0** | **5** | **8,046** | **20.6** | **19.1** | **22.0** | **was 2,444ms → 119x** |
| **5.5** | **5** | **5,668** | **17.4** | **16.7** | **17.9** | **was 354ms → 20x** |
| **6.0** | **5** | **3,877** | **15.8** | **14.5** | **17.0** | **was 105ms → 7x** |
| **6.5** | **6** | **11,541** | **28.4** | **27.9** | **29.3** | **was 544ms → 19x** |
| **7.0** | **6** | **6,325** | **18.5** | **17.8** | **19.8** | **was 257ms → 14x** |

#### Pan Tests (3-run avg, ms)

| Location | z=4 res 4 | z=5.5 res 5 | z=7 res 6 |
|----------|-----------|-------------|-----------|
| London | 72.2 | 21.5 | 17.7 |
| Paris | 74.0 | 23.4 | 20.4 |
| Reykjavik | 62.6 | 16.1 | 17.2 |
| Istanbul | 85.7 | 20.2 | 22.6 |

#### Comparison: On-Demand vs Full Precompute (pan @ z=5.5)

| Location | On-demand (old) | Precomputed (new) | Speedup |
|----------|----------------|-------------------|---------|
| London | 255ms | 21.5ms | **12x** |
| Paris | 245ms | 23.4ms | **10x** |
| Reykjavik | 326ms | 16.1ms | **20x** |
| Istanbul | 363ms | 20.2ms | **18x** |

### The Cliff Is Gone

```
BEFORE (precomputed cliff at z5.0):
  z: 0.5  1  1.5  2  2.5  3   3.5  4   4.5 │ 5     5.5   6    6.5   7
 ms:   2  6   6  39  43  204  113  76   63  │ 2444  354   105  544   257
                                              │
                                       39x cliff ─┘

AFTER (all precomputed):
  z: 0.5  1  1.5  2  2.5  3   3.5  4   4.5   5    5.5  6   6.5  7
 ms:   2  6   6  37  38  194  108  73   62   21   17   16   28  19
                                              │
                                    no cliff ─┘  (62→21ms, smooth)
```

### Route Table & Tooltip

New route table (`data/isochrones/bristol/routes.json`, 224 KB) provides:
- Full airport path per destination: `["LHR", "OSL", "LYR"]`
- Per-leg flight times: `[157, 198]` minutes
- Total dijkstra time + stop count

Tooltip now shows exact per-leg breakdown:
```
Bristol → LHR ✈ PEK ✈ NDG → dest
Ground to LHR          2h 00m
Airport overhead       1h 30m
LHR → PEK            10h 06m
Connection at PEK      2h 00m
PEK → NDG             2h 13m
Arrival + ground       6h 31m
```
