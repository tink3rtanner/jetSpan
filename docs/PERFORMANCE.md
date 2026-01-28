# JetSpan Performance Documentation

## Overview

This document tracks performance benchmarks for the JetSpan flight isochrone visualization.
Benchmarks should be re-run after significant changes to measure improvement/regression.

## Test Suite

The test suite is located at `scripts/performance-tests.js` and can be injected into the browser console.

### Usage

```javascript
// Full suite (all tests)
await perfTests.runAll();

// Individual suites
await perfTests.runZoomSuite();      // Test all zoom levels
await perfTests.runPanSuite();       // Test panning globally
await perfTests.runEdgeCaseSuite();  // Test water, remote areas
await perfTests.runCacheSuite();     // Test cache effectiveness

// View results
perfTests.printResults();
perfTests.printSummary();
perfTests.exportJSON();  // Export for comparison
```

### Test Categories

| Category | Description |
|----------|-------------|
| zoom | Resolution transitions from z0.8 (globe) to z7 (street) |
| pan | Panning to 14 global locations |
| edge-water | Ocean areas (should be fast due to water skip) |
| edge-remote | Remote land areas (Siberia, Greenland) |
| edge-dense | High airport density areas (Singapore, Frankfurt) |
| cache-cold | First visit to locations |
| cache-warm | Revisit same locations (should be faster) |

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

### Pre-computed Isochrones (Priority: High)

Pre-compute travel times as static JSON per origin city.

```
data/isochrones/bristol.json
{
  "origin": "bristol",
  "resolutions": {
    "1": { "h3index": {"time": 180, "route": {...}}, ... },
    "2": { ... },
    ...
  }
}
```

**Expected Impact**: Near-instant rendering (just JSON lookup)

### Web Workers (Priority: Medium)

Offload computation to background thread to avoid UI blocking.

### Progressive Rendering (Priority: Low)

Render low-res first, then upgrade to high-res.

---

## How to Run Benchmarks

1. Start dev server: `python3 -m http.server 8765`
2. Open `http://localhost:8765/isochrone.html`
3. Open browser console
4. Paste contents of `scripts/performance-tests.js`
5. Run: `await perfTests.runAll()`
6. Save results: `perfTests.exportJSON()`

---

## Performance Goals

| Metric | Current | Target |
|--------|---------|--------|
| Initial render (cold) | 15-40s | <5s |
| Cached render | ~12s | <2s |
| Pan to new location | ~20s | <3s |
| Zoom level change | ~15-30s | <2s |

**Ultimate goal**: Pre-computed JSON makes all operations <1s

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

**Performance comparison:**

| Test | Before | After | Notes |
|------|--------|-------|-------|
| Globe z0.8 | 15.8s | 19.2s | No improvement |
| z1.5 | 19.0s | 21.0s | No improvement |

### Why Limited Benefit?

The pre-computed data IS being used, but benefits are limited because:

1. **Grid iteration overhead**: The code still iterates through ALL cells in the viewport to check if they exist in pre-computed data
2. **Most cells are water**: At res 1, only 46 of 842 cells have data (5.5%). The rest are water/unreachable and get skipped anyway
3. **Water skip is already fast**: The "water skip" optimization (>300km from airport) is very quick, so pre-computed lookup doesn't save much

### Architectural Improvements Needed

To fully benefit from pre-computed data:

1. **Direct rendering**: Render pre-computed cells directly without grid iteration
2. **Resolution-aware loading**: Only load pre-computed data for current resolution
3. **Tile-based approach**: Pre-compute in tiles, load tiles as needed
4. **Higher resolution**: Pre-compute res 4-6 for local views (requires bounded computation)

### Current Architecture

```
Current flow (slow):
1. Iterate all cells in viewport
2. For each cell:
   a. Check cache -> if hit, use cached
   b. Check pre-computed -> if hit, use pre-computed
   c. Check water skip -> if water, skip
   d. Compute on-demand -> expensive

Better flow (future):
1. Load pre-computed cells for viewport + resolution
2. Render directly (no iteration)
3. Only compute on-demand for res 4-6 (local views)
```
