# JetSpan - Claude Context

## Quick Start
When working on this project, start the dev server:
```bash
python -m http.server 8765
```
Then open http://localhost:8765/isochrone.html

## Project Overview
JetSpan visualizes flight travel times on a 3D globe using hexagonal isochrone cells.

## Main File: `isochrone.html`

**Tech Stack:**
- MapLibre GL JS v5.0.0 (globe projection)
- H3-js v4.1.0 (hexagonal grid)
- OpenFreeMap tiles (no API key needed)

**Key Features:**
- Globe projection with rotatable 3D view
- H3 hexagonal cells colored by travel time bands
- 6 origin cities, 4518 airports, 58k routes (from data/*.json)
- Dynamic resolution based on zoom level
- Interactive tooltips with routing breakdown
- OSRM-based ground transport times (partial, 3 airports tested)

## Data Pipeline

Real data loaded from `data/` directory:
- `airports.json` - 4518 airports from OurAirports
- `routes.json` - 58k routes merged from Amadeus + OpenFlights
- `ground/{region}.json` - OSRM driving times (lazy loaded)

Scripts in `scripts/`:
- `fetch-airports.py` - download airport data
- `crawl-amadeus.py` - crawl route data (needs AMADEUS_API_KEY/SECRET env vars)
- `compute-ground-times.py` - compute OSRM ground times (~50h for all airports)
- `sanity-checks.py` - validate data
- `dijkstra_router.py` - **one-to-all shortest path routing** (recommended)
- `routing_algo.py` - per-cell routing test harness (legacy comparison)
- `route_validation.py` - validate route data against known nonstops

See `HANDOFF.md` for detailed implementation notes.
See `scripts/ROUTING.md` for routing algorithm documentation.

## Other Files (legacy)
- `index.html` - Warped map visualizations
- `panels.html` - 9-panel comparison view
- `lhostis.html` - 3D shrivelled USA map

## Key Implementation Details

### Travel Time Calculation
```
Total = ground_to_airport + airport_overhead(90min) + flight(s) + connection_overhead(90min each) + arrival_overhead(30-60min) + ground_from_airport
```

**Current UI (isochrone.html):** per-cell routing, direct flights only (fake-flight bug FIXED)

**New approach (dijkstra_router.py):** one-to-all shortest path with connections
1. Run bounded-stops dijkstra from origin airports (once)
2. Output: best_time_to_airport for all 3192 reachable airports
3. For each cell: `min(best_time[a] + ground_time(a, cell))` for k nearest

Coverage: 344 direct + 2202 one-stop + 646 two-stop = 3192 airports from Bristol

See `scripts/ROUTING.md` for algorithm details.

### Rendering Architecture (Hybrid Direct Rendering)

```
zoom 0-5.5:  res 1-4 → direct render from pre-computed JSON (instant, <15ms)
zoom 5.5+:   res 5-6 → grid iteration with on-demand compute (~1-3s)
```

Pre-computed data: `data/isochrones/bristol.json` (3.5 MB, 18,990 cells)
- Loaded on page init, direct rendering skips grid iteration entirely
- See `docs/PERFORMANCE.md` for benchmarks

### H3 Grid Resolution
- Res 2: Globe view (zoom < 2) - ~86k km² cells
- Res 3: Continental (zoom 2-3.5) - ~12k km² cells
- Res 4: Regional (zoom 3.5-5) - ~1.7k km² cells
- Res 5: Local (zoom 5-7) - ~252 km² cells
- Res 6: Street level (zoom 7+) - ~36 km² cells

### Antimeridian Handling
Cells crossing 180° longitude are normalized by shifting negative longitudes to positive (adding 360°) to keep polygons contiguous.

## Documentation
- `ISOCHRONE-DEV-NOTES.md` - Detailed technical documentation
- `flight-isochrone-spec.md` - Original specification
- `spec.md` - General project spec

## Remaining Tasks (Priority Order)

1. **Skip water cells** - don't compute travel time for ocean cells
2. **Pre-compute on load** - compute all res 2-3 cells upfront for instant panning
3. **Run full OSRM** - `python scripts/compute-ground-times.py` (~50h on Pi)
4. **UI cleanup** - collapse settings behind (i) button
5. **Color distribution** - more granularity for 10-16+ hour destinations
6. ~~**Hub routing**~~ - DONE: see `dijkstra_router.py` (bounded-stops dijkstra)
7. **Web Workers** - offload computation to background thread
8. **Integrate dijkstra results** - export airport times, use in UI/precompute

## Performance Notes

- **Pre-computed res 1-4**: <15ms render (was 15-40s)
- **On-demand res 5-6**: 1-3s (grid iteration, only when zoomed in)
- **Cached render**: <15ms
- Spatial index for airports built on load (12ms)
- Travel time cache clears on origin change
- See `docs/PERFORMANCE.md` for full benchmarks

## Agent Handoff: Merge Dijkstra Routing + Recompute

### what's done
- **UI rendering is fast** — hybrid direct rendering works, res 1-4 are instant
- **dijkstra_router.py exists** — finds 3192 reachable airports (vs 375 direct-only)
- **precompute-isochrone.py exists** — generates `data/isochrones/{origin}.json`
- **fake-flight bug is fixed** in isochrone.html (only real routes used)

### what needs to happen
1. **wire dijkstra results into precompute-isochrone.py**
   - currently precompute uses its own per-cell routing (direct flights only)
   - dijkstra_router.py computes best_time_to_airport for ALL reachable airports
   - precompute should use dijkstra output instead of its own routing
   - approach: run dijkstra once → export airport times → precompute reads those times + does ground_time(airport, cell) lookups

2. **re-run precompute for bristol**
   ```bash
   python scripts/precompute-isochrone.py bristol
   ```
   - outputs `data/isochrones/bristol.json` (res 1-4, ~3.5 MB)
   - res 4 takes ~15 min, res 1-3 are fast
   - res 5+ not worth precomputing (2M+ cells, diminishing returns)

3. **update isochrone.html on-demand routing** (res 5-6 fallback)
   - the grid iteration path for res 5+ still uses per-cell routing
   - could load dijkstra airport times and do fast nearest-airport lookups
   - or just accept that zoomed-in views are slightly slower

### file map
```
precompute-isochrone.py   ← generates pre-computed JSON (needs dijkstra)
dijkstra_router.py        ← computes best airport times (needs integration)
isochrone.html            ← renders JSON + on-demand fallback
data/isochrones/*.json    ← pre-computed output (re-generate after routing change)
scripts/ROUTING.md        ← algorithm docs
docs/PERFORMANCE.md       ← benchmark docs
```

### key constraint
- `data/isochrones/bristol.json` must stay <10 MB (github pages)
- res 1-4 at 3.5 MB is fine, don't go higher
- the JSON structure is: `{ resolutions: { "1": { h3index: { time, route } } } }`
- isochrone.html reads this structure in `generateHexGridDirect()`
