# JetSpan

interactive flight travel-time visualization on a 3D globe. hexagonal isochrone cells show how long it takes to reach anywhere in the world from a given origin, accounting for ground transport, layovers, and multi-stop connections.

**[Live demo](https://tink3rtanner.github.io/jetSpan/isochrone.html)**

## Running Locally

```bash
python -m http.server 8765
# visit http://localhost:8765/isochrone.html
```

no build step. all deps loaded via CDN (MapLibre GL JS v5, H3-js v4.1).

## How It Works

### System Overview

```
 ┌─────────────────────────────────────────────────────────────────┐
 │                     PRECOMPUTE (python, offline)                │
 │                                                                 │
 │  airports.json ──┐                                              │
 │  (4518 airports) │    ┌──────────────┐    ┌──────────────────┐  │
 │                  ├──> │ FlightGraph  │──> │ DijkstraRouter   │  │
 │  routes.json ────┘    │ 4500 nodes   │    │ multi-source     │  │
 │  (58k routes)         │ ~116k edges  │    │ max 2 stops      │  │
 │                       └──────────────┘    └───────┬──────────┘  │
 │                                                   │             │
 │                                  best_times: 3139 reachable     │
 │                                  airports w/ optimal routes     │
 │                                                   │             │
 │  ground/{region}.json ──┐                         │             │
 │  (OSRM drive times)     │    ┌────────────────────▼───────────┐ │
 │                         ├──> │ Cell Iterator (res 1-6)        │ │
 │  spatial index ─────────┘    │ for each H3 cell on earth:     │ │
 │  (res-2 buckets)             │   find nearest airport         │ │
 │                              │   compute ground_from time     │ │
 │                              │   pick best: fly vs drive      │ │
 │                              └─────────────┬──────────────────┘ │
 │                                            │                    │
 │              ┌────────────────────────────┬┴──────────────┐     │
 │              ▼                            ▼               ▼     │
 │      bristol.json               r5/*.json.gz      r6/*.json.gz  │
 │      (res 1-4, 8.7MB)          (527 chunks)      (3042 chunks)  │
 │      routes.json                (~5 MB gz)        (~31 MB gz)   │
 │      (route table, 224KB)                                       │
 └─────────────────────────────────────────────────────────────────┘
              │                         │                │
              ▼                         ▼                ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │                      CLIENT (browser, runtime)                  │
 │                                                                 │
 │  on load:  fetch base JSON + route table + airports             │
 │  on zoom:  pick H3 resolution for zoom level                    │
 │  on pan:   fetch needed .gz chunks, decompress, merge           │
 │  render:   iterate cells → viewport filter → color → polygon    │
 │  hover:    route table lookup → per-leg breakdown tooltip       │
 └─────────────────────────────────────────────────────────────────┘
```

### The Routing Algorithm

the core question: "what's the fastest way to get from bristol to every reachable point on earth?"

```
step 1: build flight graph
─────────────────────────
    airports = nodes, routes = directed edges
    edge weight = estimated flight time (haversine-based speed model)

        BRS ──85m──> CDG ──145m──> IST ──410m──> SIN
         │                                        │
         └──130m──> AMS ──510m──────────────────> NRT
                     │
                     └──490m──> JFK ──330m──> LAX

step 2: multi-source dijkstra
─────────────────────────────
    seed priority queue with ALL origin city airports:
      BRS (25m ground), LHR (110m), LGW (150m), BHX (131m)

    explore outward, tracking:
      - cumulative cost (ground_to + overhead + flights + connections)
      - stop count (max 2 stops = 3 flights)
      - full path for route reconstruction

    result: best_times[airport] for all 3139 reachable airports

                            ┌─ direct:  ~500 airports
    3139 reachable ─────────┼─ 1-stop: ~1800 airports
                            └─ 2-stop:  ~800 airports

step 3: assign cells
────────────────────
    for each H3 hex cell at each resolution (1 through 6):
      1. find nearby airports via spatial index (res-2 buckets)
      2. for each candidate airport:
           total = best_times[airport] + arrival_overhead + ground_from
      3. also check: is driving faster? (near origin)
      4. pick minimum → that's this cell's travel time
```

### Travel Time Formula

every cell's time is the sum of five legs:

```
  origin city                                                    cell
      │                                                           │
      ▼                                                           ▼
  ┌───────┐   ┌────────┐   ┌─────────────────────┐   ┌───────┐
  │ground │   │overhead│   │      flights        │   │airport│
  │  to   │──>│security│──>│  + connections      │──>│ to    │
  │airport│   │boarding│   │  (per stop: 90+30m  │   │ground │
  └───────┘   └────────┘   └─────────────────────┘   └───────┘
   25-150m      90m          varies                    0-60m
                                                    + 30-60m arrival

  total = ground_to + 90 + sum(flights) + 120*stops + arrival + ground_from

  example: bristol → CDG (direct)
    25m(BRS) + 90m(security) + 85m(flight) + 0 + 60m(intl) + 20m(ground) = 280m

  example: bristol → sydney (2-stop via SIN, MEL)
    110m(LHR) + 90m + (410+205+120)m + 240m(2×120) + 60m + 30m = 1265m
```

### Zoom → Resolution Mapping

the client picks an H3 resolution based on zoom level. higher zoom = smaller cells = more detail. res 5-6 are chunked bc they'd be hundreds of MB unchunked.

```
  zoom level    H3 res    cell size       cells     source
  ──────────    ──────    ─────────       ─────     ──────
    < 1          1        ~609k km²         355     base JSON
    < 2          2         ~86k km²       2,500     base JSON
    < 4.5        4         ~1.7k km²    143,000     base JSON
    < 6.5        5          ~252 km²  ~2,100,000    lazy chunks (r5/)
    ≥ 6.5        6           ~36 km²  ~7,200,000    lazy chunks (r6/)
                                                       │
  res 3 skipped — too coarse for its zoom range    decompressed
                                                   client-side via
                                                   DecompressionStream
```

### Chunk Loading

res 5-6 data is split into chunks grouped by coarser parent cells. the client only fetches chunks overlapping the current viewport.

```
  user pans/zooms
       │
       ▼
  getResolutionForZoom(zoom)  ──>  res 5 or 6?
       │                                │
       │  yes                           │
       ▼                                ▼
  getVisibleParentCells(bounds)    parent res:
       │                            res 5 chunks → grouped by res-1 parent
       │                            res 6 chunks → grouped by res-2 parent
       ▼
  filter out already-loaded parents
       │
       ▼
  parallel fetch: r{res}/{parent}.json.gz
       │
       ▼
  DecompressionStream('gzip')  ──>  JSON.parse
       │
       ▼
  merge into LOADED_ISOCHRONE.resolutions[res]
       │
       ▼
  generateHexGridDirect()  ──>  GeoJSON FeatureCollection
       │
       ▼
  map.getSource('hexgrid').setData(...)
       │
       ▼
  maplibre paints polygons w/ fill-color, opacity, outlines
```

### Color Scale

```
  travel time          color         hex
  ───────────          ─────         ───
    < 2h               green         #22c55e
    < 4h               lime          #84cc16
    < 6h               yellow        #eab308
    < 8h               orange        #f97316
    < 10h              red           #ef4444
    < 12h              dark red      #dc2626
    < 14h              purple        #a855f7
    < 18h              violet        #7c3aed
    < 24h              deep purple   #4c1d95
    ≥ 24h              near black    #1e1b4b

  band thresholds scale with the color slider (default 1.0x)
```

## Project Structure

```
jetspan/
├── isochrone.html              ← main app (single-file, ~2500 lines)
├── airports.json               ← 4518 airports from OurAirports
├── routes.json                 ← 58k routes (amadeus + openflights)
├── data/
│   ├── ground/                 ← OSRM driving times by region
│   │   └── {region}.json
│   └── isochrones/
│       ├── bristol.json        ← res 1-4 cells (8.7 MB, 143k cells)
│       └── bristol/
│           ├── routes.json     ← route table (224 KB, 3139 airports)
│           ├── r5/             ← res 5 chunks (527 files, ~5 MB gz)
│           │   └── {res1_parent}.json.gz
│           └── r6/             ← res 6 chunks (3042 files, ~31 MB gz)
│               └── {res2_parent}.json.gz
├── scripts/
│   ├── precompute-isochrone.py ← generates all data files
│   ├── dijkstra_router.py      ← FlightGraph + DijkstraRouter
│   ├── fetch-airports.py       ← download airport data
│   ├── crawl-amadeus.py        ← crawl flight routes (needs API key)
│   ├── compute-ground-times.py ← OSRM ground time computation
│   ├── osrm-crawler.py         ← long-running OSRM crawler w/ resume
│   ├── sanity-checks.py        ← data validation
│   └── ROUTING.md              ← routing algorithm docs
├── _test_runner.html           ← standalone test suite (75 tests)
├── _benchmark_runner.html      ← performance benchmarks
├── index.html                  ┐
├── panels.html                 ├── earlier d3/three.js prototypes
└── lhostis.html                ┘   (superseded by isochrone.html)
```

### Cell Data Format

```
  flight cell:     {"t": 280, "o": "LHR", "a": "CDG", "s": 0}
                    │          │           │           └─ stops (0=direct)
                    │          │           └─ arrival airport
                    │          └─ origin airport (which one we flew from)
                    └─ total travel time (minutes)

  drive-only cell: {"t": 45, "d": 1, "g": 1}
                    │         │       └─ OSRM-verified (optional)
                    │         └─ drive flag
                    └─ drive time (minutes)

  route table:     {"CDG": {"p":["BRS","CDG"], "l":[85], "t":214, "s":0}}
                             │                   │        │        └─ stops
                             │                   │        └─ dijkstra total
                             │                   └─ per-leg flight minutes
                             └─ airport path
```

## Tests

- **standalone**: open `http://localhost:8765/_test_runner.html` (75 tests)
- **in-app**: call `runTests()` in browser console on isochrone.html (96 tests)
- **benchmark**: call `runBenchmark()` in console
