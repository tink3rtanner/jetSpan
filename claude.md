# JetSpan - Claude Context

## Quick Start
When working on this project, start the dev server:
```bash
python -m http.server 8765
```
Then open http://localhost:8765/isochrone.html

## Verification
After any visual/data change, take screenshots via Chrome browser automation to verify the data looks correct. Check multiple zoom levels and hover tooltips.

## Testing
Two test suites available:
- **Standalone**: open `http://localhost:8765/_test_runner.html` — tests data files, route table, gzipped chunks, airports, consistency, page integrity (75 tests)
- **In-app**: call `runTests()` in the browser console on isochrone.html — tests rendering at every zoom level, chunk loading, pan across 7 cities, cell integrity, color mapping (96 tests)
- **Benchmark**: call `runBenchmark()` in console — performance timing at all zoom levels

## Project Overview
JetSpan visualizes flight travel times on a 3D globe using hexagonal isochrone cells.

## Main File: `isochrone.html`

**Tech Stack:**
- MapLibre GL JS v5.0.0 (globe projection)
- H3-js v4.1.0 (hexagonal grid)
- OpenFreeMap tiles (no API key needed)

**Key Features:**
- Globe projection with rotatable 3D view
- H3 hexagonal cells colored by travel time bands (adjustable color scale slider)
- 3139 reachable airports shown on map, 4518 total in dataset, 58k routes
- Pre-computed dijkstra routing with multi-stop connections (res 1-6)
- Lazy-loaded gzipped chunks for res 5-6 (DecompressionStream API)
- Route table with per-leg flight times for accurate tooltip breakdowns
- Interactive tooltips with full multi-stop routing breakdown
- OSRM-based ground transport times (partial, europe + north america)
- Drive-only zone near origin (cells where driving is faster than flying)

## Data Pipeline

### Data files loaded by the client:
- `airports.json` — 4518 airports from OurAirports
- `routes.json` — 58k routes merged from Amadeus + OpenFlights
- `data/isochrones/bristol.json` — res 1-4 cell data (8.7 MB, 143k cells)
- `data/isochrones/bristol/routes.json` — route table (224 KB, 3139 airports)
- `data/isochrones/bristol/r5/*.json.gz` — res 5 chunks (~4.5 MB gzipped, 527 files)
- `data/isochrones/bristol/r6/*.json.gz` — res 6 chunks (~60 MB gzipped, 3042 files)

### Data file structure:
```
data/isochrones/
  bristol.json                      # res 1-4 base data (loaded on init)
  bristol/
    routes.json                     # per-airport routing info for tooltips
    r5/{res1_parent}.json.gz        # res 5 chunks, gzipped (lazy loaded)
    r6/{res2_parent}.json.gz        # res 6 chunks, gzipped (lazy loaded)
```

Total on disk: ~74 MB (gzipped chunks). Wire transfer: ~65 MB worst case.
GitHub Pages auto-gzips the base JSON; chunks are pre-gzipped and decompressed client-side.

### Cell format:
```json
{"t": 329, "o": "BRS", "a": "CDG", "s": 0}        // flight cell
{"t": 45, "d": 1, "g": 1}                          // drive-only cell (g=1 means OSRM)
```

### Route table format:
```json
{"CDG": {"p": ["BRS","CDG"], "l": [85], "t": 214, "s": 0}}
```
- `p`: airport path, `l`: per-leg flight minutes, `t`: dijkstra total, `s`: stops

## Scripts

- `precompute-isochrone.py` — generates all data files using dijkstra (res 1-6 + route table)
- `dijkstra_router.py` — core routing algorithm (FlightGraph + DijkstraRouter)
- `fetch-airports.py` — download airport data
- `crawl-amadeus.py` — crawl route data (needs AMADEUS_API_KEY/SECRET env vars)
- `compute-ground-times.py` — compute OSRM ground times (~50h for all airports)
- `osrm-crawler.py` — long-running OSRM crawler with checkpoint/resume
- `sanity-checks.py` — validate data

See `scripts/ROUTING.md` for routing algorithm documentation.

## Key Implementation Details

### Travel Time Calculation
```
Total = ground_to + overhead(90min) + flights + connections(120min/stop) + arrival(30-60min) + ground_from
```

### Rendering Architecture (All Pre-computed)
```
zoom < 1:    res 1 → direct render from base JSON
zoom < 2:    res 2 → direct render from base JSON
zoom < 4.5:  res 4 → direct render from base JSON (res 3 skipped)
zoom < 6.5:  res 5 → lazy-loaded gzipped chunks, decompressed client-side
zoom 6.5+:   res 6 → lazy-loaded gzipped chunks, decompressed client-side
```

All rendering is pre-computed. No on-demand computation. Chunk loading:
1. On zoom/pan, `loadChunksForViewport()` identifies needed parent cells
2. Fetches `.json.gz` files via `fetchGzipJSON()` (DecompressionStream API)
3. Merges into `LOADED_ISOCHRONE.resolutions[res]`
4. `generateHexGridDirect()` renders from merged data

### H3 Grid Resolution
- Res 1: Far globe (zoom < 1) — ~609k km² cells, 355 cells
- Res 2: Globe (zoom < 2) — ~86k km² cells, 2500 cells
- Res 4: Regional (zoom < 4.5) — ~1.7k km² cells, 122k cells
- Res 5: Local (zoom < 6.5) — ~252 km² cells, ~2M cells (chunked)
- Res 6: Street (zoom 6.5+) — ~36 km² cells, ~7M cells (chunked)

### Antimeridian Handling
Cells crossing 180deg longitude are normalized by shifting negative longitudes to positive (adding 360) to keep polygons contiguous.

## OSRM Ground Times Crawl (In Progress)

Crawler running on raspberry pi, hitting the demo OSRM server.

**Scripts:**
- `scripts/osrm-crawler.py` — long-running crawler with checkpoint/resume
- `scripts/check-crawler.sh` — quick status check (run from mac)

**Pi details:**
- host: `raspberrypi.local`, user: `joshpriebe`
- venv: `~/jetspan/venv/bin/python`
- output: `~/jetspan/data/ground/{region}.json`

**To check:** `bash scripts/check-crawler.sh`
**To sync data back:** `scp raspberrypi.local:~/jetspan/data/ground/*.json data/ground/`

## Performance Notes

- **Pre-computed res 1-4**: <100ms render (143k cells)
- **Full precompute**: ~570s for res 1-6 (7M cells, 3500+ chunk files)
- **Chunk loading**: ~200-500ms per viewport (parallel fetch + decompress)
- **Cached render**: <15ms

## Remaining Tasks

1. **Run full OSRM** — crawler on pi, ~36h remaining
2. **Crawl actual flight times** — amadeus flight offers API for real durations
3. **Add more origin cities** — london, NYC, tokyo etc. (run precompute per origin)
4. **UI cleanup** — collapse settings behind (i) button

### Done
- Dijkstra routing integrated
- Full precompute res 1-6 with chunked loading
- Gzipped chunks for GitHub Pages deployment (~74 MB vs ~434 MB raw)
- Route table with per-leg breakdown
- Color scale slider
- OSRM ground data integration (partial)
- Drive-only zone near origin
- Water filtering via OSRM detour ratio
- Comprehensive test suite (standalone + in-app)
- All 3139 reachable airports shown on map
