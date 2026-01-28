# JetSpan Data Pipeline

## Overview

JetSpan uses a multi-stage data pipeline to provide flight travel time visualizations.

```
                    ┌──────────────┐
                    │  OurAirports │
                    │    (CSV)     │
                    └──────┬───────┘
                           │
                           v
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Amadeus    │    │ fetch-       │    │   airports   │
│    API       │───>│ airports.py  │───>│    .json     │
└──────────────┘    └──────────────┘    └──────────────┘
       │                                      4,518 airports
       v
┌──────────────┐    ┌──────────────┐
│   crawl-     │    │   routes     │
│ amadeus.py   │───>│    .json     │
└──────┬───────┘    └──────────────┘
       │                  │              58,359 routes
       v                  v
┌──────────────┐    ┌──────────────┐
│ OpenFlights  │───>│  merge-      │
│   (backup)   │    │ routes.py    │
└──────────────┘    └──────────────┘

       ┌──────────────┐    ┌──────────────┐
       │   OSRM       │    │   ground/    │
       │   Server     │───>│  europe.json │
       └──────────────┘    └──────────────┘
                                 (partial)

       ┌──────────────┐    ┌──────────────┐
       │ precompute-  │    │ isochrones/  │
       │ isochrone.py │───>│ bristol.json │
       └──────────────┘    └──────────────┘
                                 (new!)
```

---

## Data Files

### `data/airports.json`

**Source**: OurAirports dataset
**Script**: `scripts/fetch-airports.py`
**Size**: ~483 KB
**Count**: 4,518 airports

```json
{
  "LHR": {
    "name": "London Heathrow Airport",
    "lat": 51.4706,
    "lng": -0.4619,
    "country": "GB",
    "type": "large_airport"
  },
  ...
}
```

**Filters applied**:
- Only `large_airport` and `medium_airport` types
- Must have valid IATA code
- Must have valid coordinates

---

### `data/routes.json`

**Source**: Amadeus API + OpenFlights (merged)
**Scripts**: `scripts/crawl-amadeus.py`, `scripts/fetch-openflights.py`, `scripts/merge-routes.py`
**Size**: ~370 KB
**Count**: 58,359 routes

```json
{
  "LHR": ["JFK", "LAX", "CDG", "FRA", ...],
  "BRS": ["DUB", "BCN", "AMS", ...],
  ...
}
```

**Notes**:
- Amadeus provides more accurate current routes
- OpenFlights fills gaps for airports not in Amadeus
- Merge prioritizes Amadeus data

---

### `data/ground/europe.json`

**Source**: OSRM demo server
**Script**: `scripts/compute-ground-times.py`
**Size**: ~98 KB (test data only)
**Coverage**: 3 airports (BRS, LHR, JFK)

```json
{
  "BRS": {
    "86194c47fffffff": 45,  // H3 cell -> minutes driving
    "86194c4ffffffff": 52,
    ...
  },
  ...
}
```

**Status**: Partial - full computation (~50 hours) not yet run.

---

### `data/isochrones/{origin}.json` (NEW)

**Source**: Pre-computed travel times
**Script**: `scripts/precompute-isochrone.py`
**Format**:

```json
{
  "origin": "bristol",
  "origin_name": "Bristol, UK",
  "computed": "2026-01-28T...",
  "resolutions": {
    "1": {
      "8001fffffffffff": {"time": 420, "route": {...}},
      ...
    },
    "2": {...},
    "3": {...}
  }
}
```

**Purpose**: Eliminate runtime computation - instant JSON lookup.

---

## Scripts

### `scripts/fetch-airports.py`

Downloads airport data from OurAirports and filters to usable airports.

```bash
python3 scripts/fetch-airports.py
```

**Output**: `data/airports.json`

---

### `scripts/crawl-amadeus.py`

Crawls Amadeus API for route data. Uses test environment (free).

```bash
# Requires AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET env vars
python3 scripts/crawl-amadeus.py
```

**Output**: `raw/amadeus-checkpoint.json` (intermediate), `data/routes.json` (final)

**Notes**:
- Checkpoints every 20 airports
- Resumable if interrupted
- Rate limited, takes ~2-3 hours for all airports

---

### `scripts/fetch-openflights.py`

Downloads routes from OpenFlights (backup/merge source).

```bash
python3 scripts/fetch-openflights.py
```

**Output**: `raw/openflights-routes.json`

---

### `scripts/merge-routes.py`

Merges Amadeus and OpenFlights routes for best coverage.

```bash
python3 scripts/merge-routes.py
```

**Output**: `data/routes.json`, `data/routes-stats.json`

---

### `scripts/compute-ground-times.py`

Computes driving times from airports to H3 cells using OSRM.

```bash
python3 scripts/compute-ground-times.py
```

**Output**: `data/ground/{region}.json`

**Notes**:
- Uses OSRM demo server (slow, rate limited)
- ~50 hours for all 1,201 large airports
- Checkpoints every 20 airports

---

### `scripts/precompute-isochrone.py`

Pre-computes travel times for a specific origin city.

```bash
python3 scripts/precompute-isochrone.py bristol
python3 scripts/precompute-isochrone.py --all
```

**Output**: `data/isochrones/{origin}.json`

**Resolutions computed**:
- Res 1: 842 cells (globe view)
- Res 2: 5,882 cells (continental)
- Res 3: 41,162 cells (regional)

**Notes**:
- Res 4-6 skipped (millions of cells, impractical)
- Most cells skipped as water/unreachable
- ~2-3 minutes per origin

---

### `scripts/sanity-checks.py`

Validates all data files.

```bash
python3 scripts/sanity-checks.py
```

---

## Adding New Origins

To add a new origin city to the pre-compute:

1. Edit `scripts/precompute-isochrone.py`
2. Add entry to `ORIGINS` dict:

```python
ORIGINS = {
    "bristol": {...},
    "london": {
        "name": "London, UK",
        "coords": [-0.118, 51.509],
        "airports": [
            {"code": "LHR", "coords": [-0.461, 51.470], "ground_min": 45},
            {"code": "LGW", "coords": [-0.190, 51.148], "ground_min": 60},
            ...
        ]
    }
}
```

3. Run: `python3 scripts/precompute-isochrone.py london`

---

## Raw Files (gitignored)

Located in `raw/`:

- `ourairports.csv` - source airport data
- `openflights-routes.json` - parsed OpenFlights routes
- `amadeus-checkpoint.json` - crawl progress
- `ground-checkpoint.json` - OSRM compute progress
