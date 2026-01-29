# Routing Algorithm - Next Steps

*logged 2026-01-28*

## current state

dijkstra router is working correctly:
- multi-source bounded-stops shortest path from bristol
- correctly selects origin airport (BRS direct when available, else LHR)
- circuity filter prevents absurd routes
- 3192 airports reachable with 2-stop cap

**known limitations:**
1. flight times estimated from distance (not actual schedules)
2. ground transport hardcoded for bristol only
3. no UI integration yet - python precompute only

## priority order

### 1. crawl actual flight times (high value, medium effort)

current distance-based estimation has ~10-15% error and bucket boundary quirks. amadeus flight offers API returns actual scheduled durations.

approach:
- extend `crawl-amadeus.py` to fetch one sample flight per route
- store in `data/flight_times.json` as `{origin: {dest: minutes}}`
- throttle to stay within rate limits (already doing this for route crawl)
- run periodically (monthly?) - schedules don't change often
- fallback to distance estimation for missing pairs

### 2. export precomputed times for UI (high value, low effort)

run dijkstra once per origin, export to `data/airport_times_{origin}.json`. UI just does nearest-airport lookup instead of computing routes.

format:
```json
{
  "origin": "bristol",
  "computed": "2026-01-28",
  "airports": {
    "JFK": {"time": 702, "stops": 0, "path": ["LHR", "JFK"]},
    ...
  }
}
```

### 3. wire precomputed times into isochrone.html (high value, medium effort)

replace the buggy per-cell routing with:
1. load `airport_times_{origin}.json` on origin change
2. cell query = find k nearest airports, add ground time, pick min
3. much faster + correct

### 4. ground transport improvements (medium value, high effort)

options:
- run OSRM for more regions (already have europe, need US/asia)
- or just hardcode major origin cities like we did for bristol
- hardcoding is probably fine for MVP - only need ~10 cities

### 5. add more origin cities (medium value, low effort once #4 done)

london, NYC, LA, tokyo, singapore, dubai - cover major population centers. each needs:
- list of nearby airports with ground times
- run dijkstra export
- add to UI dropdown

## deferred / nice-to-have

- **smooth flight time estimation** - fix bucket boundary discontinuities (minor impact)
- **region-aware MIN_FLY_DISTANCE** - 150km for europe, 400km for US (matters when adding US origins)
- **port dijkstra to JS** - probably not worth it, precompute is fast enough
- **transit API for ground times** - overkill, hardcoding works

## files to know

- `scripts/dijkstra_router.py` - main routing algorithm
- `scripts/crawl-amadeus.py` - route data crawler (extend for flight times)
- `scripts/ROUTING.md` - algorithm documentation
- `isochrone.html` - UI (needs integration with precomputed times)
- `data/routes.json` - connectivity only, no times
- `data/airports.json` - airport coords and metadata
