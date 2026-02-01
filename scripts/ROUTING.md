# Flight Routing Algorithm

documentation for the flight connection routing logic in jetspan.

## overview

the routing problem: given an origin city (e.g., bristol), compute travel time to any point on earth considering:
- ground transport to departure airport
- flight(s) with possible connections
- ground transport from arrival airport to destination

## approaches

### 1. direct-only (original, buggy)

**file:** `routing_algo.py` - `BuggyRouter` class

the original implementation had a bug: when no direct flight existed, it estimated flight time from distance anyway, treating every airport as reachable.

```
for each cell:
  find nearest airports
  for each origin-dest pair:
    if route exists: use it
    else: ESTIMATE ANYWAY (bug!)
```

**result:** fake routes to places like LAF, CMI from bristol.

### 2. direct-only (fixed)

**file:** `routing_algo.py` - `FixedRouter` class

fixes the bug by only considering routes that actually exist in `routes.json`. precomputes reachable airport set for O(1) lookup.

```
reachable = {all airports with routes from origin airports}
for each cell:
  find nearest airports IN reachable set
  calc travel time
```

**coverage:** 375 airports from bristol (direct nonstops only)

### 3. hub-based 1-stop

**file:** `routing_algo.py` - `ConnectionRouter` class

adds 1-stop connections via predefined hub list.

```
HUBS = [LHR, SIN, DXB, LAX, ORD, ...]
for each cell:
  try direct first
  if no direct:
    for each hub:
      if origin->hub AND hub->dest: calc route
```

**coverage:** ~600 airports, but misses regional connections (e.g., ORD->LAF)

### 4. dijkstra (recommended)

**file:** `dijkstra_router.py` - `DijkstraRouter` class

the correct approach: compute best time to ALL airports once, then hex queries are just nearest-airport lookups.

```
1. build flight graph from routes.json
2. run multi-source bounded-stops dijkstra from origin airports
3. output: best_time_to_airport[code] for all reachable airports
4. hex query: min(best_time[a] + ground_time(a, cell)) for k nearest
```

**coverage:** 3192 airports from bristol (with 2-stop cap)
**advantage:** finds regional connections the hub-list approach misses

## dijkstra algorithm details

### state

```python
(total_time, airport_code, stops_used, path)
```

### stop counting

- 0 stops = direct flight (origin -> dest)
- 1 stop = one connection (origin -> hub -> dest)
- 2 stops = two connections (origin -> hub1 -> hub2 -> dest)

### cost model

```
total = ground_to_origin
      + origin_overhead (90m)
      + flight_time
      + [connection_time (90m) + stop_penalty (30m)] * num_connections
      + arrival_overhead (30-60m)
      + ground_from_dest
```

### parameters

| parameter | value | notes |
|-----------|-------|-------|
| ORIGIN_OVERHEAD | 90m | security, boarding |
| CONNECTION_TIME | 90m | deplane, walk, reboard |
| STOP_PENALTY | 30m | discourage unnecessary connections |
| ARRIVAL_OVERHEAD_DOMESTIC | 30m | quick deplane |
| ARRIVAL_OVERHEAD_INTL | 60m | customs, bags |
| MAX_STOPS | 2 | covers 99% of sane itineraries |
| MAX_GROUND_DIST | 400km | no 3000km drives |
| MAX_CIRCUITY | 1.8x | reject routes > 1.8x direct distance |
| MIN_FLY_DISTANCE | 150km | just drive if closer than this |

### filters applied

1. **circuity filter**: rejects routes where total flight distance > 1.8x great-circle distance (prevents absurd routings like BRS->EDI->BOH for nearby destinations)

2. **min fly distance**: destinations < 150km from origin return "drive only" (no point flying)

3. **fly vs drive comparison**: for destinations 150-400km, compares flight route vs driving and picks faster option

### flight time estimation

**limitation:** routes.json only has connectivity (origin -> [destinations]), not actual flight durations. we estimate from distance:

```python
def estimate_flight_minutes(dist_km):
    if dist_km < 500:   return dist_km / 400 * 60 + 30  # regional
    if dist_km < 1500:  return dist_km / 550 * 60 + 25  # short-haul
    if dist_km < 4000:  return dist_km / 700 * 60 + 25  # medium-haul
    if dist_km < 8000:  return dist_km / 800 * 60 + 25  # long-haul
    return dist_km / 850 * 60 + 30  # ultra-long-haul
```

this is ~10-15% accurate but has discontinuities at bucket boundaries (e.g., 1499km vs 1501km uses different speeds, can cause shorter distance to estimate longer).

**todo:** crawl actual flight times from amadeus or similar. stale data is fine - schedules don't change that often. can throttle slowly during precompute. would store as `data/flight_times.json` with `{origin: {dest: minutes}}` structure.

## ground transport

### current state

OSRM data exists for all 8 regions (complete as of Jan 2026):
- `data/ground/europe.json` - BRS coverage

US and other regions use distance-based estimates (40kph default, too conservative).

### bristol origin airports

hardcoded realistic train/drive times for bristol:
```
BRS: 25min  - drive to bristol airport
LHR: 110min - 1h30 train to paddington + 20min heathrow express
LGW: 150min - train via london victoria
BHX: 131min - 1h20 train to birmingham + 50min to airport
```

LHR generally preferred over BHX due to better connectivity and similar ground time.

### regional considerations

the "should i fly or drive" threshold varies significantly by region:

| region | typical behavior | notes |
|--------|------------------|-------|
| UK/europe | train for 100-400km | trains often beat flying for short trips |
| US | drive up to 4-6h | americans avoid airports for short trips |
| australia | drive long distances | similar to US |
| asia | varies | dense rail in japan/china, driving elsewhere |

current MIN_FLY_DISTANCE (150km) is euro-centric. for US origins, should probably be 300-400km.

**future improvement:** region-aware thresholds
```python
MIN_FLY_DISTANCE = {
    'europe': 150,
    'US': 400,
    'AU': 400,
    'asia': 200,
    'default': 250,
}
```

### OSRM coordinate snapping problem

OSRM's table API snaps input coordinates to the nearest road segment before routing.
for coordinates over land, the snap distance is negligible (<100m). for coordinates
in the ocean near islands, the snap can be tens of km — OSRM silently routes from
the snapped coastal road point instead of the actual cell center.

**symptom:** island airports (bermuda, comoros, mallorca, etc.) show large blobs of
colored cells extending far into the ocean. all cells receive plausible-looking drive
times (6-66 minutes for bermuda) because OSRM is routing between points on the
island's road network, not to the actual ocean locations.

**detection:** two signals distinguish snapped ocean cells from legitimate land cells:

1. **implied speed:** `straight_line_distance / osrm_time`. for real driving this is
   30-100 km/h (roads wind). for snapped cells far from shore, the straight-line
   distance is large but the time is short (routing from a closer snap point), giving
   implied speeds >130 km/h — physically impossible on any road.

2. **time-distance correlation:** for continental airports, drive time increases with
   distance (pearson r > 0.7). for island airports with snap contamination, times
   cluster in a narrow band regardless of distance (r < 0.5) because all cells snap
   to the same small road network.

**current filter** (in `precompute-isochrone.py` `load_osrm_ground_data()`):

```
stage 1: hard speed cap
  implied speed > 130 km/h → remove (catches distant ocean cells)

stage 2: island detection
  compute pearson r(distance, time) for remaining cells
  if r < 0.6:
    find cells with "on-island" speeds (< 30 km/h)
    island_radius = max distance of slow cells × 1.2
    remove cells beyond island_radius
```

**results:** strips ~82k snap artifacts across 1,201 airports. bermuda: 1,519 → 108
cells. continental airports (CDG, LHR, NRT) lose <0.1% of cells.

**known limitations:**

- near-shore ocean cells within the island radius still pass the filter. these have
  small snap distances so their implied speeds are plausible. a proper land/water mask
  (e.g., natural earth coastline data or OSM water polygons) would fix this but adds
  a data dependency.

- the 130 km/h hard cap may clip some german autobahn cells where sustained average
  speed is genuinely >120 km/h. these cells would fall back to haversine estimation
  or be covered by neighboring airports. not observed as a visual issue.

- the r < 0.6 threshold catches ~131 airports including some coastal (not island)
  airports like miami and vancouver. for these, the island_radius is large (100+ km)
  so only far-offshore ocean cells are removed — correct behavior, not a false positive.

- the slow-cell radius estimate (speed < 30 km/h) can be contaminated by near-shore
  snapped cells. for very small islands this inflates the radius slightly. bermuda's
  island_radius is 39km for a ~30km island — close but includes some reef area.

**potential improvements:**

- use OSRM's `waypoints[].distance` field (snap distance in meters) during crawl
  to filter at crawl time rather than post-hoc. would require re-crawling.
- integrate a coastline/water polygon dataset for definitive land/water classification
- use satellite-derived land cover data (natural earth, modis) to mask water cells
- re-crawl with a self-hosted OSRM instance that returns snap distance metadata

### todo

- ~~run `compute-ground-times.py` for US/other regions~~ (done, all regions crawled)
- use region-specific speeds as fallback (65mph US, 50kph europe mixed)
- add region-aware MIN_FLY_DISTANCE when supporting multiple origins

## validation

### route data validation

**file:** `route_validation.py`

checks that:
- known nonstops exist (LHR-JFK, LAX-SYD, etc.)
- connection-only routes are absent (LHR-SYD, LHR-MEL)

**result:** 15/15 known nonstops present, 0/7 false positives

### test cases

| destination | direct | 1-stop | dijkstra |
|-------------|--------|--------|----------|
| sydney | ❌ | 27h47m | 27h47m (LHR->PEK->SYD) |
| melbourne | ❌ | 28h00m | 27h47m (BHX->DEL->MEL) |
| honolulu | ❌ | 22h20m | 22h20m (LHR->YVR->HNL) |
| wellington | ❌ | ❌ | 32h58m (LHR->NRT->AKL->WLG) |
| lafayette IN | 17h43m | 17h43m | 15h55m (LHR->ORD->LAF) |
| new york | 11h34m | 11h34m | 11h34m (BHX->EWR) |

note: lafayette IN shows dijkstra finding the ORD->LAF regional flight that hub-based routing missed. actual benefit is marginal (~40min) given ORD connection overhead.

## usage

```bash
# run dijkstra router tests
python scripts/dijkstra_router.py

# query specific coordinate
python scripts/dijkstra_router.py --coord -86.9 40.4

# show top N airports by travel time
python scripts/dijkstra_router.py --top 50

# export airport times to json
python scripts/dijkstra_router.py --export

# run old routing algo comparison
python scripts/routing_algo.py

# validate route data
python scripts/route_validation.py
```

## origin airport selection

the algorithm picks the best origin airport automatically based on total time:

| destination | origin | reason |
|-------------|--------|--------|
| Paris (CDG) | BRS | direct flight, no need for london |
| Rome (FCO) | BRS | direct flight |
| New York | LHR | 110min train vs 131min BHX, LHR has better US routes |
| Chicago | LHR | better connections |
| Tokyo | LHR | only LHR has direct |

example: NYC routing comparison
```
LHR->EWR: 110m train + 90m overhead + 442m flight + 60m arrival = 11h42m
BHX->EWR: 131m train + 90m overhead + 433m flight + 60m arrival = 11h54m
```
LHR wins by ~12min. generally LHR preferred for long-haul due to better connectivity.

## next steps

1. **export dijkstra results** - `data/airport_times_{origin}.json` for UI consumption
2. **crawl actual flight times** - amadeus or similar, store in `data/flight_times.json`. stale data ok, can throttle slowly during precompute
3. **wire up OSRM** - use real ground times where available
4. **tune parameters** - connection time, stop penalty based on real itineraries
5. ~~**circuity filter**~~ - DONE (reject routes > 1.8x direct distance)
6. **port to JS** - or keep python for precompute, js for display only
7. **region-aware MIN_FLY_DISTANCE** - when adding US/other origins
