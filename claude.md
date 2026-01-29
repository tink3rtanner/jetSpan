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
- Pre-computed dijkstra routing with multi-stop connections
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
- `dijkstra_router.py` - one-to-all shortest path routing (core algorithm)
- `precompute-isochrone.py` - generates `data/isochrones/{origin}.json` using dijkstra
- `routing_algo.py` - per-cell routing test harness (legacy, not used)
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
Total = ground_to_airport + airport_overhead(90min) + flight(s) + connection_overhead(90+30 min each) + arrival_overhead(30-60min) + ground_from_airport
```

**Routing (dijkstra, integrated):** one-to-all shortest path with multi-stop connections
1. `dijkstra_router.py` runs bounded-stops dijkstra from origin airports (once, 0.3s)
2. `precompute-isochrone.py` uses spatial index to find best airport per H3 cell
3. output: `data/isochrones/{origin}.json` — compact format, loaded by UI

Coverage from Bristol: 338 direct + 2156 one-stop + 645 two-stop = 3139 airports reachable

See `scripts/ROUTING.md` for algorithm details.

### Rendering Architecture (Hybrid Direct Rendering)

```
zoom 0-5.5:  res 1-4 → direct render from pre-computed JSON (instant, <100ms)
zoom 5.5+:   res 5-6 → grid iteration with on-demand compute (~1-3s)
```

Pre-computed data: `data/isochrones/bristol.json` (8.7 MB, 143,077 cells)
- Compact JSON format: `{t, o, a, s}` per cell (time, origin airport, dest airport, stops)
- Breakdown derived client-side by `parseCellData()` using ORIGINS config
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

1. **Higher-res rendering** - res 4 is coarse at medium zoom; consider per-res file splitting, zoom threshold tuning, possibly res 5 selective precompute
2. **Strip on-demand fallback code** - once fully precomputed, the grid iteration path in isochrone.html can be removed
3. **Run full OSRM** - `python scripts/compute-ground-times.py` (~50h on Pi)
4. **Crawl actual flight times** - amadeus flight offers API for real durations (currently estimated from distance)
5. **Color distribution** - more granularity for 10-16+ hour destinations
6. **UI cleanup** - collapse settings behind (i) button
7. **Add more origin cities** - london, NYC, tokyo etc. (run precompute per origin)

### Done
- ~~Hub routing~~ — `dijkstra_router.py` (bounded-stops dijkstra)
- ~~Integrate dijkstra~~ — wired into `precompute-isochrone.py`, compact JSON format
- ~~Pre-compute on load~~ — res 1-4 pre-computed, direct rendering
- ~~Skip water cells~~ — spatial index skips cells >400km from any airport

## Performance Notes

- **Pre-computed res 1-4**: <100ms render (143k cells, was 15-40s with grid iteration)
- **Dijkstra precompute**: 10.7s for all 4 resolutions (was 18 min with per-cell routing)
- **On-demand res 5-6**: 1-3s (grid iteration, only when zoomed in)
- **Cached render**: <15ms
- Spatial index for airports built on load (12ms)
- Travel time cache clears on origin change
- See `docs/PERFORMANCE.md` for full benchmarks

## Agent Handoff: Next Steps

### what's done
- **dijkstra routing integrated** — `precompute-isochrone.py` imports and runs dijkstra_router directly
- **precompute pipeline works** — 10.7s for res 1-4, 143k cells, 8.7 MB output
- **compact JSON format** — `{t, o, a, s}` per cell, breakdown derived client-side by `parseCellData()`
- **UI rendering is fast** — hybrid direct rendering, res 1-4 instant from pre-computed JSON
- **multi-stop routing** — 338 direct + 2156 one-stop + 645 two-stop from bristol
- **tooltips work** — show full breakdown + route path for multi-stop flights

### what needs to happen next
1. **higher resolution / smoother display**
   - res 4 is coarse at medium zoom, some discontinuities visible
   - options: per-resolution file splitting (load only needed res), zoom threshold tuning, selective res 5
   - constraint: total file size must stay <10 MB for github pages
   - res 5 globally = 2M cells, ~52 MB — need selective approach or split files

2. **strip on-demand fallback** (if fully precomputed)
   - isochrone.html still has grid iteration code for res 5-6
   - once display is fully precomputed, this dead code can be removed
   - simplifies the rendering path significantly

3. **more origin cities**
   - run `python scripts/precompute-isochrone.py --all` (or per-city)
   - each city needs entry in `ORIGINS` dict in dijkstra_router.py
   - UI already supports origin dropdown

### file map
```
precompute-isochrone.py   ← generates pre-computed JSON (uses dijkstra)
dijkstra_router.py        ← core routing algorithm (FlightGraph + DijkstraRouter)
isochrone.html            ← renders JSON via generateHexGridDirect() + parseCellData()
data/isochrones/*.json    ← pre-computed output (re-generate after routing change)
scripts/ROUTING.md        ← algorithm docs
docs/PERFORMANCE.md       ← benchmark docs
```

### key constraints
- `data/isochrones/bristol.json` must stay <10 MB (github pages)
- res 1-4 at 8.7 MB is close to limit — adding res 5 needs file splitting
- compact JSON: `{ resolutions: { "1": { h3index: { t, o, a, s } } } }`
- isochrone.html reads via `generateHexGridDirect()` → `parseCellData()`
