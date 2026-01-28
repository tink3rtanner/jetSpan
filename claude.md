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

See `HANDOFF.md` for detailed implementation notes.

## Other Files (legacy)
- `index.html` - Warped map visualizations
- `panels.html` - 9-panel comparison view
- `lhostis.html` - 3D shrivelled USA map

## Key Implementation Details

### Travel Time Calculation
```
Total = ground_to_airport + airport_overhead(90min) + flight + arrival_overhead(30-60min) + ground_from_airport
```

For each destination cell, the algorithm:
1. Finds top 10 nearest destination airports
2. Tries all combinations with origin airports
3. Picks route with minimum total travel time

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
6. **Hub routing** - 1-stop connections via major hubs
7. **Web Workers** - offload computation to background thread

## Performance Notes

- First render: ~28s (computing 40k cells)
- Cached render: ~0.4s (lookup only)
- Spatial index for airports built on load (12ms)
- Travel time cache clears on origin change
