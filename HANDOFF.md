# JetSpan Handoff Document

## What Was Built

This session implemented a real data pipeline for the flight isochrone visualization, replacing hardcoded sample data with actual airport/route data.

## Data Pipeline

### Scripts Created (`scripts/`)

| Script | Purpose | Status |
|--------|---------|--------|
| `fetch-airports.py` | Downloads OurAirports data, filters to large/medium airports | Done - 4518 airports |
| `fetch-openflights.py` | Downloads OpenFlights routes for sanity checking | Done - 37k routes |
| `crawl-amadeus.py` | Crawls Amadeus API for route data (uses test env) | Done - 40k routes |
| `merge-routes.py` | Merges Amadeus + OpenFlights for best coverage | Done - 58k routes |
| `compute-ground-times.py` | Computes OSRM driving times to H3 cells | Done - 1201 airports, 1.6M cells |
| `sanity-checks.py` | Validates all data files | Done |
| `dijkstra_router.py` | One-to-all shortest path routing | Done - 3139 airports from Bristol |
| `precompute-isochrone.py` | Generates pre-computed isochrone JSON | Done - 143k cells, 8.7 MB |

### Data Files (`data/`)

| File | Size | Contents |
|------|------|----------|
| `airports.json` | 483 KB | 4518 airports (code -> {name, lat, lng, country, type}) |
| `routes.json` | 370 KB | 58,359 routes (airport -> [destinations]) |
| `ground/{region}.json` | 34 MB total | OSRM ground times, 8 regions, 1201 airports |
| `routes-stats.json` | ~1 KB | Merge statistics |

### Raw Files (`raw/` - gitignored)

- `ourairports.csv` - source airport data
- `openflights-routes.json` - openflights parsed routes
- `amadeus-checkpoint.json` - crawl progress
- `ground-checkpoint.json` - OSRM compute progress

## Architecture Decisions

### H3 Resolution Strategy
- **Display**: Dynamic res 2-6 based on zoom
- **Ground data**: Always stored at res 6 (~10km cells)
- **Lookup**: Convert any cell to res 6 for ground time lookup

### Async Data Loading
- Load all needed regions BEFORE computing cells
- Ground data lazy-loaded by region (europe, north-america, etc.)
- All cell lookups are synchronous after loading

### Performance Optimizations Implemented
1. **Spatial index for airports** - H3 res 3 index for fast nearest-airport lookup
2. **Travel time cache** - Caches results by H3 cell, clears on origin change
3. **Airport array cache** - Avoids recreating array on every call
4. **Airport coords lookup** - O(1) lookup instead of Array.find()
5. **Reduced airport search** - 5 nearest airports instead of 10
6. **Early exit** - Stop searching when route < 4 hours found

### Current Performance
- **Pre-computed res 1-4**: <100ms direct render (143k cells from JSON)
- **On-demand res 5-6**: 1-3s (grid iteration, only when zoomed in)
- **Dijkstra precompute**: 10.7s for all 4 resolutions (was 18 min with per-cell routing)
- Spatial index build: 12ms
- Legacy: first render was ~28s for 40k cells before precompute

## Integration Points in isochrone.html

### Data Loading (lines ~435-520)
```javascript
let LOADED_AIRPORTS = null;  // {code: {name, lat, lng, country, type}}
let LOADED_ROUTES = null;    // {code: [destinations]}
let LOADED_GROUND = {};      // {region: {airport: {h3cell: minutes}}}

async function loadJetSpanData()  // loads airports + routes
async function loadGroundData(region)  // lazy loads ground data
```

### Key Functions Modified
- `findNearestAirports()` - uses spatial index
- `getFlightTime()` - checks loaded routes, estimates from distance
- `calculateTotalTravelTime()` - uses OSRM ground data when available
- `generateHexGrid()` - has timing logs, uses cache

## Known Issues

1. **Display coarseness** - res 4 cells are visible at medium zoom, some discontinuities
2. **Far destinations look same** - color bands don't differentiate 10h vs 20h well
3. **Flight times estimated** - distance-based, not actual schedules (~10-15% error)
4. **Bristol only** - precomputed data exists only for bristol origin so far

## Remaining Tasks

### High Priority
1. **Higher-res rendering** - per-resolution file splitting, zoom threshold tuning, possibly selective res 5
2. **Strip on-demand fallback** - once fully precomputed, remove grid iteration code from isochrone.html
3. **Expand OSRM coverage** - 36% of airports covered, need self-hosted instance for full coverage
4. **Crawl actual flight times** - amadeus flight offers API for real durations

### UI Improvements
1. **Color distribution** - add config for better differentiation of distant places (10-16+ hours)
2. **Collapse controls** - put settings behind (i) button

### Future
1. **More origin cities** - run precompute per origin, add to UI dropdown
2. **Web Workers** - offload computation to background thread (only matters if on-demand code stays)

### Done
- ~~Skip water cells~~ — spatial index skips cells >400km from any airport
- ~~Pre-compute on load~~ — res 1-4 pre-computed, direct rendering
- ~~Ship pre-computed JSON~~ — `data/isochrones/bristol.json` (8.7 MB, 143k cells)
- ~~Hub routing~~ — dijkstra with bounded stops (direct + 1-stop + 2-stop)

## API Credentials

Amadeus credentials in user's env (test environment):
- Uses `test.api.amadeus.com` (free, unlimited)
- Production requires separate application

## Running the Project

```bash
# start dev server
python3 -m http.server 8765

# open browser
open http://localhost:8765/isochrone.html
```

## OSRM Ground Computation (Done)

Crawl completed Jan 31 2026 via `scripts/osrm-crawler.py` on raspberry pi.
1,201 airports, 1.6M cells, ~57 hours on OSRM demo server.
Data in `data/ground/{region}.json` (34 MB total, 8 region files).

To re-run or extend: `python3 scripts/osrm-crawler.py` (checkpoints every airport, resumable).

## File Structure

```
jetspan/
  isochrone.html          # main visualization
  data/
    airports.json         # 4518 airports
    routes.json           # 58k routes
    isochrones/
      bristol.json        # precomputed isochrone (8.7 MB, 143k cells)
    ground/
      europe.json         # test ground data (3 airports)
  scripts/
    dijkstra_router.py    # core routing algorithm
    precompute-isochrone.py # generates isochrone JSON
    fetch-airports.py
    fetch-openflights.py
    crawl-amadeus.py
    merge-routes.py
    compute-ground-times.py
    sanity-checks.py
  raw/                    # gitignored intermediate files
  plans/
    improved-travel-data.md  # detailed implementation plan
```

## Key Insight

Pre-computing travel times as static JSON per origin city was the right call. dijkstra + spatial index precompute runs in 10.7s (was 18 min), produces 143k cells. runtime is just JSON lookup — instant (<100ms for any zoom level at res 1-4).
