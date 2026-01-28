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
| `compute-ground-times.py` | Computes OSRM driving times to H3 cells | Partial - 3 airports tested |
| `sanity-checks.py` | Validates all data files | Done |

### Data Files (`data/`)

| File | Size | Contents |
|------|------|----------|
| `airports.json` | 483 KB | 4518 airports (code -> {name, lat, lng, country, type}) |
| `routes.json` | 370 KB | 58,359 routes (airport -> [destinations]) |
| `ground/europe.json` | 98 KB | OSRM ground times for BRS, LHR, JFK (test data) |
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
- First render: ~28s for 40k cells (0.69ms/cell)
- Cached render: ~0.4s for 40k cells (cache hit)
- Spatial index build: 12ms

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

1. **Stats panel shows old data** - displays hardcoded 81 airports instead of loaded 4518
2. **Bristol→London seems slow** - showing 2-4h, should be <2h
3. **Water cells computed** - wastes time computing travel to ocean
4. **Far destinations look same** - color bands don't differentiate 10h vs 20h well

## Remaining Tasks

### High Priority
1. **Skip water cells** - check if cell centroid is water, skip computation
2. **Pre-compute on load** - compute all res 2-3 cells upfront for instant panning
3. **Run full OSRM computation** - ~50 hours on Pi overnight

### UI Improvements
1. **Collapse controls** - put settings behind (i) button
2. **Color distribution** - add config for better differentiation of distant places (10-16+ hours)
3. **Fix stats panel** - show loaded data counts

### Future
1. **Ship pre-computed JSON** - `data/isochrones/bristol.json` etc. for zero runtime computation
2. **Web Workers** - offload computation to background thread
3. **Hub routing** - 1-stop connections via major hubs

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

## Running OSRM Ground Computation

```bash
# install h3
pip install h3

# run (uses demo server, ~50 hours for all 1201 large airports)
python3 scripts/compute-ground-times.py

# checkpoints every 20 airports, resumable
```

## File Structure

```
jetspan/
  isochrone.html          # main visualization (modified)
  data/
    airports.json         # 4518 airports
    routes.json           # 58k routes
    ground/
      europe.json         # test ground data (3 airports)
  scripts/
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

The main performance bottleneck is computing travel times for each cell. With 40k cells and complex routing logic, this takes ~30s. The cache helps on re-renders but first render is slow.

**Best solution**: Pre-compute travel times as static JSON per origin city. Then runtime is just JSON lookup - instant.
