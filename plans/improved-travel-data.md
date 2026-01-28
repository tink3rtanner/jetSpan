# JetSpan: Improved Travel Data Plan (v2)

## vision
beautiful, high-fidelity travel time visualization showing the "arteries" of global transport - where motorways, flight routes, and terrain create fingers of accessibility radiating from origin cities. think 1912 Vienna railway map but for modern multimodal travel.

## goals
1. **accurate flight routes** - real route network, not just distance-based guesses
2. **realistic ground transport** - actual road network effects (motorways fast, mountains slow)
3. **proper airport overhead** - domestic vs international differences
4. **hub routing** - connect through major hubs when no direct flight
5. **UK/EU rail** - train beats plane for short distances
6. **high fidelity** - resolution tunable, "go big" on data quality
7. **static hosting** - github pages compatible, no runtime APIs

## constraints
- all data pre-computed, shipped as static JSON
- lazy-load ground data by region (initial load ~2.5MB, then ~10-15MB per region on demand)
- 11 fixed origin cities (no "pick any city" yet)
- github pages: 100MB per file limit, 100GB bandwidth/month
- desktop-first (mobile optimization deferred to v2)

## known limitations
- water/island cells use 30km/h straight-line fallback (no real ferry modeling)
- flight times estimated from distance (no schedule data)
- mobile performance not optimized (large ground data files)

---

## technical decisions

### h3 resolution: display vs lookup
- **display resolution**: dynamic (res 2-6) based on zoom level
- **ground data resolution**: always res 6 (~10km cells)
- **solution**: always lookup at res 6 regardless of display res

```javascript
function getGroundTimeForCell(airportCode, displayCell) {
  const [lat, lng] = h3.cellToLatLng(displayCell);
  const lookupCell = h3.latLngToCell(lat, lng, 6);  // always res 6
  return groundData[airportCode]?.[lookupCell] ?? null;
}
```

### async ground loading: load-before-compute
- load all needed regions BEFORE cell computation (not per-cell async)
- user sees brief loading state when switching origins
- all cell lookups are then synchronous

```javascript
async function ensureGroundDataLoaded(airportCodes) {
  const regions = [...new Set(airportCodes.map(getAirportRegion))];
  await Promise.all(regions.map(loadGroundData));
  // now all lookups are sync
}
```

### data compression
- v1: ship uncompressed json, evaluate if problematic
- if needed: gzip (github pages can serve .json with gzip encoding)
- future: msgpack/protobuf if json too slow

### openflights usage
- **sanity check only** - do NOT merge into routes.json
- openflights data is stale (~2014), would pollute fresh amadeus data
- use for validation: "does amadeus have routes openflights has?"

---

## origin cities (11)

Bristol (default), London, Paris, New York, Los Angeles, Tokyo, Sydney, Dubai, São Paulo, Cape Town, Cincinnati

---

## data sources

| data | source | method |
|------|--------|--------|
| airports | OurAirports | curl (free, nightly updates) |
| flight routes | Amadeus Airport Routes API | one-time crawl ~500 airports |
| flight routes (backup) | OpenFlights | sanity check / gap filler |
| ground transport | OSRM | one-time batch compute |
| cities | SimpleMaps | already in repo |

---

## phase 1: data pipeline

### 1a: airports

**script:** `scripts/fetch-airports.py`

```python
import csv
import json
import urllib.request

# download OurAirports data
urllib.request.urlretrieve(
    "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "raw/ourairports.csv"
)

# parse and filter
airports = {}
with open("raw/ourairports.csv") as f:
    for row in csv.DictReader(f):
        if row["type"] in ["large_airport", "medium_airport"] and row["iata_code"]:
            airports[row["iata_code"]] = {
                "name": row["name"],
                "lat": float(row["latitude_deg"]),
                "lng": float(row["longitude_deg"]),
                "country": row["iso_country"],
                "type": row["type"].replace("_airport", ""),
            }

with open("data/airports.json", "w") as f:
    json.dump(airports, f)

print(f"Saved {len(airports)} airports")
```

**output:** `data/airports.json` (~500KB, ~800 airports)

---

### 1b: flight routes (Amadeus)

**script:** `scripts/crawl-amadeus.py`

```python
import requests
import json
import time
import os

API_KEY = os.environ["AMADEUS_API_KEY"]
API_SECRET = os.environ["AMADEUS_API_SECRET"]
CHECKPOINT_FILE = "raw/amadeus-checkpoint.json"

def get_token():
    r = requests.post(
        "https://api.amadeus.com/v1/security/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": API_KEY, "client_secret": API_SECRET}
    )
    return r.json()["access_token"]

def get_destinations(token, airport_code):
    r = requests.get(
        "https://api.amadeus.com/v1/airport/direct-destinations",
        params={"departureAirportCode": airport_code},
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code == 200:
        return [d["iataCode"] for d in r.json().get("data", [])]
    elif r.status_code == 429:  # rate limited
        time.sleep(60)
        return get_destinations(token, airport_code)
    return []

# load checkpoint if exists
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE) as f:
        checkpoint = json.load(f)
    routes = checkpoint["routes"]
    completed = set(checkpoint["completed"])
else:
    routes = {}
    completed = set()

# load airports to crawl
with open("data/airports.json") as f:
    airports = json.load(f)

token = get_token()
token_time = time.time()

for i, code in enumerate(airports.keys()):
    if code in completed:
        continue

    # refresh token every 25 minutes
    if time.time() - token_time > 1500:
        token = get_token()
        token_time = time.time()

    routes[code] = get_destinations(token, code)
    completed.add(code)
    print(f"[{i+1}/{len(airports)}] {code}: {len(routes[code])} destinations")

    # checkpoint every 50 airports
    if len(completed) % 50 == 0:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump({"routes": routes, "completed": list(completed)}, f)

    time.sleep(0.5)  # be nice to API

# save final
with open("data/routes.json", "w") as f:
    json.dump(routes, f)

print(f"Done. {len(routes)} airports, {sum(len(v) for v in routes.values())} route pairs")
```

**output:** `data/routes.json` (~2MB)

**amadeus setup:**
1. sign up: https://developers.amadeus.com/
2. create app, get API key + secret
3. set env vars: `AMADEUS_API_KEY`, `AMADEUS_API_SECRET`
4. free tier: 2000 calls/month (enough for one full crawl)

---

### 1c: flight routes (OpenFlights backup)

**script:** `scripts/fetch-openflights.py`

```python
import urllib.request
import json

# download OpenFlights routes
urllib.request.urlretrieve(
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat",
    "raw/openflights-routes.dat"
)

# parse (format: airline,airline_id,src,src_id,dst,dst_id,codeshare,stops,equipment)
routes = {}
with open("raw/openflights-routes.dat") as f:
    for line in f:
        parts = line.strip().split(",")
        if len(parts) >= 5:
            src, dst = parts[2], parts[4]
            if len(src) == 3 and len(dst) == 3:  # valid IATA codes
                if src not in routes:
                    routes[src] = []
                if dst not in routes[src]:
                    routes[src].append(dst)

with open("raw/openflights-routes.json", "w") as f:
    json.dump(routes, f)

print(f"OpenFlights: {len(routes)} airports, {sum(len(v) for v in routes.values())} routes")
```

**purpose:** sanity check against Amadeus only (NOT gap-filling - data is stale ~2014)

**validation script:** `scripts/validate-routes.py`
```python
# compare amadeus vs openflights for sanity checking
amadeus_routes = json.load(open("data/routes.json"))
openflights_routes = json.load(open("raw/openflights-routes.json"))

stats = {"amadeus_only": 0, "openflights_only": 0, "both": 0}
suspicious = []  # routes openflights has that amadeus doesn't

all_airports = set(amadeus_routes.keys()) | set(openflights_routes.keys())
for src in all_airports:
    amadeus_dests = set(amadeus_routes.get(src, []))
    openflights_dests = set(openflights_routes.get(src, []))

    stats["amadeus_only"] += len(amadeus_dests - openflights_dests)
    stats["openflights_only"] += len(openflights_dests - amadeus_dests)
    stats["both"] += len(amadeus_dests & openflights_dests)

    # flag major routes openflights has but amadeus doesn't
    for dst in openflights_dests - amadeus_dests:
        suspicious.append(f"{src}-{dst}")

print(f"Shared: {stats['both']}, Amadeus-only: {stats['amadeus_only']}, OpenFlights-only: {stats['openflights_only']}")
print(f"Suspicious (openflights-only): {len(suspicious)} routes - spot check these manually")
```

**DO NOT merge openflights into routes.json** - amadeus is authoritative

---

### 1d: ground transport (OSRM)

**OSRM setup options (pick one):**

| option | requirements | instructions |
|--------|--------------|--------------|
| **region-by-region** | 8-16GB RAM | process each continent separately |
| **cloud VM** | ~$5 | rent 64GB VM for 4 hours |
| **OpenRouteService** | patience | 2000 req/day free tier, takes weeks |

**recommended: region-by-region on local machine**

```bash
# install docker if needed
# download regional extracts (pick regions you need)
mkdir -p osrm-data && cd osrm-data

wget https://download.geofabrik.de/europe-latest.osm.pbf          # ~25GB
wget https://download.geofabrik.de/north-america-latest.osm.pbf   # ~12GB
wget https://download.geofabrik.de/asia-latest.osm.pbf            # ~12GB
wget https://download.geofabrik.de/australia-oceania-latest.osm.pbf
wget https://download.geofabrik.de/south-america-latest.osm.pbf
wget https://download.geofabrik.de/africa-latest.osm.pbf

# process each region (takes hours per region)
for region in europe north-america asia australia-oceania south-america africa; do
    docker run -t -v $(pwd):/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/${region}-latest.osm.pbf
    docker run -t -v $(pwd):/data osrm/osrm-backend osrm-partition /data/${region}-latest.osrm
    docker run -t -v $(pwd):/data osrm/osrm-backend osrm-customize /data/${region}-latest.osrm
done
```

**batch query script:** `scripts/compute-ground-times.py`

```python
import h3
import requests
import json
import os
from math import radians, sin, cos, sqrt, atan2

CHECKPOINT_FILE = "raw/ground-checkpoint.json"
CONFIG = {
    "resolution": 6,      # ~10km cells (tunable: 5=25km, 6=10km, 7=4km)
    "max_hours": 6,       # driving radius
    "max_km": 400,
    "fallback_speed_kmh": 30,  # for water/unreachable
}

def haversine(coord1, coord2):
    """Distance in km between two [lng, lat] points"""
    R = 6371
    lat1, lat2 = radians(coord1[1]), radians(coord2[1])
    dlat = radians(coord2[1] - coord1[1])
    dlng = radians(coord2[0] - coord1[0])
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def query_osrm(origin, destinations, port=5000):
    """Query OSRM table API: one origin to many destinations"""
    if not destinations:
        return []
    coords = f"{origin[0]},{origin[1]};" + ";".join(f"{d[0]},{d[1]}" for d in destinations)
    try:
        r = requests.get(f"http://localhost:{port}/table/v1/driving/{coords}?sources=0", timeout=30)
        if r.ok:
            durations = r.json().get("durations", [[]])[0][1:]  # skip self
            return [d/60 if d else None for d in durations]  # seconds to minutes
    except:
        pass
    return [None] * len(destinations)

def compute_airport(airport_code, airport_coords, resolution, max_km):
    """Compute ground times from one airport to surrounding H3 cells"""
    center = h3.latlng_to_cell(airport_coords[1], airport_coords[0], resolution)

    # calculate k rings needed for max_km
    cell_km = {5: 25, 6: 10, 7: 4}[resolution]
    k = int(max_km / cell_km) + 2

    cells = list(h3.grid_disk(center, k))
    results = {}

    # batch query OSRM (100 destinations at a time)
    batch_size = 100
    for i in range(0, len(cells), batch_size):
        batch_cells = cells[i:i+batch_size]
        batch_coords = [[h3.cell_to_latlng(c)[1], h3.cell_to_latlng(c)[0]] for c in batch_cells]  # [lng, lat]

        times = query_osrm([airport_coords[1], airport_coords[0]], batch_coords)

        for cell, coords, time in zip(batch_cells, batch_coords, times):
            if time is not None and time <= CONFIG["max_hours"] * 60:
                results[cell] = round(time)
            elif time is None:
                # fallback for water/unreachable: straight line at slow speed
                dist = haversine([airport_coords[1], airport_coords[0]], coords)
                if dist <= max_km:
                    results[cell] = round(dist / CONFIG["fallback_speed_kmh"] * 60)

    return results

# load checkpoint
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE) as f:
        checkpoint = json.load(f)
    ground_data = checkpoint["data"]
    completed = set(checkpoint["completed"])
else:
    ground_data = {}
    completed = set()

# load airports
with open("data/airports.json") as f:
    airports = json.load(f)

# compute for each airport
for i, (code, info) in enumerate(airports.items()):
    if code in completed:
        continue

    print(f"[{i+1}/{len(airports)}] {code}...", end=" ", flush=True)

    result = compute_airport(
        code,
        [info["lng"], info["lat"]],
        CONFIG["resolution"],
        CONFIG["max_km"]
    )

    if result:
        ground_data[code] = result
        print(f"{len(result)} cells")
    else:
        print("no results")

    completed.add(code)

    # checkpoint every 20 airports
    if len(completed) % 20 == 0:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump({"data": ground_data, "completed": list(completed)}, f)

# save by region for lazy loading (complete mapping)
REGION_MAP = {
    "europe": [
        "GB", "FR", "DE", "ES", "IT", "NL", "BE", "AT", "CH", "PT", "IE", "NO", "SE", "DK", "FI",
        "PL", "CZ", "HU", "GR", "RO", "BG", "HR", "SK", "SI", "LT", "LV", "EE", "CY", "MT", "LU",
        "IS", "RS", "UA", "BY", "MD", "AL", "MK", "BA", "ME", "XK"
    ],
    "north-america": [
        "US", "CA", "MX", "GT", "BZ", "HN", "SV", "NI", "CR", "PA",
        "CU", "JM", "HT", "DO", "PR", "BS", "BB", "TT"
    ],
    "asia": [
        "JP", "CN", "KR", "IN", "TH", "SG", "MY", "ID", "PH", "VN", "HK", "TW", "MO",
        "MM", "KH", "LA", "BD", "LK", "NP", "PK", "MN", "KZ", "UZ", "KG", "TJ"
    ],
    "middle-east": [
        "AE", "QA", "SA", "IL", "TR", "EG", "JO", "KW", "BH", "OM",
        "LB", "IQ", "IR", "SY", "YE", "PS"
    ],
    "oceania": ["AU", "NZ", "FJ", "PG", "NC", "PF", "GU", "WS"],
    "south-america": ["BR", "AR", "CL", "CO", "PE", "EC", "VE", "BO", "PY", "UY", "GY", "SR"],
    "africa": [
        "ZA", "KE", "NG", "EG", "MA", "ET", "GH", "TZ", "UG", "RW", "SN", "CI", "CM",
        "AO", "MZ", "ZW", "BW", "NA", "MU", "TN", "DZ", "LY", "SD"
    ],
}

def get_region(country_code):
    for region, countries in REGION_MAP.items():
        if country_code in countries:
            return region
    return "other"

# split by region
by_region = {}
for code, cells in ground_data.items():
    country = airports.get(code, {}).get("country", "")
    region = get_region(country)
    if region not in by_region:
        by_region[region] = {}
    by_region[region][code] = cells

# save each region
os.makedirs("data/ground", exist_ok=True)
for region, data in by_region.items():
    with open(f"data/ground/{region}.json", "w") as f:
        json.dump(data, f)
    size_mb = os.path.getsize(f"data/ground/{region}.json") / 1024 / 1024
    print(f"Saved data/ground/{region}.json ({size_mb:.1f}MB, {len(data)} airports)")
```

**output:** `data/ground/{region}.json` files (total ~50MB at res 6)

**tunable parameters:**
- `resolution`: 5 (25km), 6 (10km), or 7 (4km) - higher = more detail, more data
- `max_hours`: 6 (default) - how far from airports to compute
- `max_km`: 400 (default) - distance cutoff

---

### 1e: status file

**script:** `scripts/build-status.py`

```python
import json
from datetime import datetime

status = {
    "last_updated": datetime.now().isoformat()[:10],
    "sources": {
        "airports": "OurAirports",
        "routes": "Amadeus Airport Routes API",
        "ground": "OSRM (OpenStreetMap)",
    },
    "config": {
        "ground_resolution": 6,
        "ground_max_hours": 6,
        "flight_overhead_domestic": 65,
        "flight_overhead_international": 135,
    },
    "stats": {
        "airports": len(json.load(open("data/airports.json"))),
        "routes": sum(len(v) for v in json.load(open("data/routes.json")).values()),
    }
}

with open("data/status.json", "w") as f:
    json.dump(status, f, indent=2)
```

---

## phase 2: integrate into isochrone.html

### 2a: data loading with lazy load

```javascript
// === DATA LOADING ===
let AIRPORTS_DATA = {};
let ROUTES_DATA = {};
let GROUND_DATA = {};  // {region: {airport: {h3cell: minutes}}}

async function loadCoreData() {
  const [airportsRes, routesRes] = await Promise.all([
    fetch('data/airports.json'),
    fetch('data/routes.json')
  ]);
  AIRPORTS_DATA = await airportsRes.json();
  ROUTES_DATA = await routesRes.json();

  // convert to array format for compatibility with existing code
  AIRPORTS = Object.entries(AIRPORTS_DATA).map(([code, data]) => ({
    code,
    name: data.name,
    coordinates: [data.lng, data.lat],
    country: data.country
  }));
}

async function loadGroundData(region) {
  if (!GROUND_DATA[region]) {
    try {
      const res = await fetch(`data/ground/${region}.json`);
      GROUND_DATA[region] = await res.json();
    } catch {
      GROUND_DATA[region] = {};
    }
  }
  return GROUND_DATA[region];
}

// Complete country→region mapping (ISO 3166-1 alpha-2)
const COUNTRY_TO_REGION = {
  // Europe
  'GB': 'europe', 'FR': 'europe', 'DE': 'europe', 'ES': 'europe', 'IT': 'europe',
  'NL': 'europe', 'BE': 'europe', 'AT': 'europe', 'CH': 'europe', 'PT': 'europe',
  'IE': 'europe', 'NO': 'europe', 'SE': 'europe', 'DK': 'europe', 'FI': 'europe',
  'PL': 'europe', 'CZ': 'europe', 'HU': 'europe', 'GR': 'europe', 'RO': 'europe',
  'BG': 'europe', 'HR': 'europe', 'SK': 'europe', 'SI': 'europe', 'LT': 'europe',
  'LV': 'europe', 'EE': 'europe', 'CY': 'europe', 'MT': 'europe', 'LU': 'europe',
  'IS': 'europe', 'RS': 'europe', 'UA': 'europe', 'BY': 'europe', 'MD': 'europe',
  'AL': 'europe', 'MK': 'europe', 'BA': 'europe', 'ME': 'europe', 'XK': 'europe',
  // North America
  'US': 'north-america', 'CA': 'north-america', 'MX': 'north-america',
  'GT': 'north-america', 'BZ': 'north-america', 'HN': 'north-america',
  'SV': 'north-america', 'NI': 'north-america', 'CR': 'north-america',
  'PA': 'north-america', 'CU': 'north-america', 'JM': 'north-america',
  'HT': 'north-america', 'DO': 'north-america', 'PR': 'north-america',
  'BS': 'north-america', 'BB': 'north-america', 'TT': 'north-america',
  // Asia
  'JP': 'asia', 'CN': 'asia', 'KR': 'asia', 'IN': 'asia', 'TH': 'asia',
  'SG': 'asia', 'MY': 'asia', 'ID': 'asia', 'PH': 'asia', 'VN': 'asia',
  'HK': 'asia', 'TW': 'asia', 'MO': 'asia', 'MM': 'asia', 'KH': 'asia',
  'LA': 'asia', 'BD': 'asia', 'LK': 'asia', 'NP': 'asia', 'PK': 'asia',
  'MN': 'asia', 'KZ': 'asia', 'UZ': 'asia', 'KG': 'asia', 'TJ': 'asia',
  // Middle East
  'AE': 'middle-east', 'QA': 'middle-east', 'SA': 'middle-east', 'IL': 'middle-east',
  'TR': 'middle-east', 'EG': 'middle-east', 'JO': 'middle-east', 'KW': 'middle-east',
  'BH': 'middle-east', 'OM': 'middle-east', 'LB': 'middle-east', 'IQ': 'middle-east',
  'IR': 'middle-east', 'SY': 'middle-east', 'YE': 'middle-east', 'PS': 'middle-east',
  // Oceania
  'AU': 'oceania', 'NZ': 'oceania', 'FJ': 'oceania', 'PG': 'oceania',
  'NC': 'oceania', 'PF': 'oceania', 'GU': 'oceania', 'WS': 'oceania',
  // South America
  'BR': 'south-america', 'AR': 'south-america', 'CL': 'south-america',
  'CO': 'south-america', 'PE': 'south-america', 'EC': 'south-america',
  'VE': 'south-america', 'BO': 'south-america', 'PY': 'south-america',
  'UY': 'south-america', 'GY': 'south-america', 'SR': 'south-america',
  // Africa
  'ZA': 'africa', 'KE': 'africa', 'NG': 'africa', 'EG': 'africa', 'MA': 'africa',
  'ET': 'africa', 'GH': 'africa', 'TZ': 'africa', 'UG': 'africa', 'RW': 'africa',
  'SN': 'africa', 'CI': 'africa', 'CM': 'africa', 'AO': 'africa', 'MZ': 'africa',
  'ZW': 'africa', 'BW': 'africa', 'NA': 'africa', 'MU': 'africa', 'TN': 'africa',
  'DZ': 'africa', 'LY': 'africa', 'SD': 'africa',
};

function getAirportRegion(airportCode) {
  const country = AIRPORTS_DATA[airportCode]?.country || '';
  return COUNTRY_TO_REGION[country] || 'other';
}
```

### 2b: flight time estimation (no hardcoded times)

```javascript
// === FLIGHT TIME ===

function hasRoute(fromCode, toCode) {
  return ROUTES_DATA[fromCode]?.includes(toCode) ||
         ROUTES_DATA[toCode]?.includes(fromCode);
}

function estimateFlightMinutes(distKm) {
  // effective speed based on distance (includes climb/descent, not just cruise)
  if (distKm < 500) return Math.round(distKm / 400 * 60 + 30);      // regional
  if (distKm < 1500) return Math.round(distKm / 550 * 60 + 25);     // short-haul
  if (distKm < 4000) return Math.round(distKm / 700 * 60 + 25);     // medium-haul
  if (distKm < 8000) return Math.round(distKm / 800 * 60 + 25);     // long-haul
  return Math.round(distKm / 850 * 60 + 30);                         // ultra-long
}

function getFlightTime(fromCode, toCode) {
  if (!hasRoute(fromCode, toCode)) return null;

  const from = AIRPORTS_DATA[fromCode];
  const to = AIRPORTS_DATA[toCode];
  if (!from || !to) return null;

  const dist = haversineDistance([from.lng, from.lat], [to.lng, to.lat]);
  return estimateFlightMinutes(dist);
}
```

### 2c: ground time with OSRM data

```javascript
// === GROUND TIME ===

async function getGroundTime(airportCode, destCoords) {
  const region = getAirportRegion(airportCode);
  const groundData = await loadGroundData(region);

  // look up H3 cell
  const h3Cell = h3.latLngToCell(destCoords[1], destCoords[0], 6);  // match computed resolution

  if (groundData[airportCode]?.[h3Cell]) {
    return groundData[airportCode][h3Cell];
  }

  // fallback: haversine estimate at 50km/h
  const airport = AIRPORTS_DATA[airportCode];
  if (!airport) return null;
  const dist = haversineDistance([airport.lng, airport.lat], destCoords);
  return Math.round(dist / 50 * 60);
}
```

---

## phase 3: variable airport overhead

```javascript
const SCHENGEN = ['AT','BE','CZ','DK','EE','FI','FR','DE','GR','HU','IS','IT','LV','LI','LT','LU','MT','NL','NO','PL','PT','SK','SI','ES','SE','CH'];

function getAirportOverhead(originCode, destCode) {
  const oCountry = AIRPORTS_DATA[originCode]?.country || '';
  const dCountry = AIRPORTS_DATA[destCode]?.country || '';

  // domestic: 45 + 20 = 65min
  if (oCountry === dCountry) return { dep: 45, arr: 20 };

  // schengen internal: 50 + 20 = 70min
  if (SCHENGEN.includes(oCountry) && SCHENGEN.includes(dCountry)) return { dep: 50, arr: 20 };

  // UK <-> EU: 60 + 30 = 90min
  if ((oCountry === 'GB' && SCHENGEN.includes(dCountry)) ||
      (SCHENGEN.includes(oCountry) && dCountry === 'GB')) return { dep: 60, arr: 30 };

  // US domestic: 60 + 20 = 80min (TSA slow)
  if (oCountry === 'US' && dCountry === 'US') return { dep: 60, arr: 20 };

  // international: 90 + 45 = 135min (default)
  return { dep: 90, arr: 45 };
}
```

---

## phase 4: hub routing

```javascript
const REGIONAL_HUBS = {
  'europe': ['LHR', 'FRA', 'AMS', 'CDG', 'MAD', 'IST'],
  'north-america': ['JFK', 'ORD', 'LAX', 'ATL', 'DFW', 'YYZ'],
  'middle-east': ['DXB', 'DOH', 'AUH'],
  'asia': ['SIN', 'HKG', 'NRT', 'ICN', 'BKK', 'PEK'],
  'oceania': ['SYD', 'MEL', 'AKL'],
  'south-america': ['GRU', 'EZE', 'BOG', 'SCL'],
  'africa': ['JNB', 'ADD', 'CAI', 'CMN'],
};

function getConnectingFlight(fromCode, toCode) {
  // try direct first
  const direct = getFlightTime(fromCode, toCode);
  if (direct) return { time: direct, via: null };

  // try 1-stop via regional hubs
  const fromRegion = getAirportRegion(fromCode);
  const toRegion = getAirportRegion(toCode);

  const candidateHubs = new Set([
    ...(REGIONAL_HUBS[fromRegion] || []),
    ...(REGIONAL_HUBS[toRegion] || []),
  ]);

  // middle east connects EU <-> Asia/Oceania
  if ((fromRegion === 'europe' && ['asia', 'oceania'].includes(toRegion)) ||
      (toRegion === 'europe' && ['asia', 'oceania'].includes(fromRegion))) {
    REGIONAL_HUBS['middle-east'].forEach(h => candidateHubs.add(h));
  }

  let best = { time: Infinity, via: null };
  const LAYOVER = 90;  // minutes

  for (const hub of candidateHubs) {
    if (hub === fromCode || hub === toCode) continue;
    const leg1 = getFlightTime(fromCode, hub);
    const leg2 = getFlightTime(hub, toCode);
    if (leg1 && leg2) {
      const total = leg1 + LAYOVER + leg2;
      if (total < best.time) {
        best = { time: total, via: hub };
      }
    }
  }

  return best.time < Infinity ? best : { time: null, via: null };
}
```

---

## phase 5: UK/EU rail

```javascript
const RAIL_TIMES = {
  // UK intercity
  'Bristol': { 'London': 100, 'Cardiff': 50, 'Birmingham': 90 },
  'Birmingham': { 'London': 85, 'Manchester': 85, 'Bristol': 90, 'Nottingham': 70 },
  'Manchester': { 'London': 125, 'Liverpool': 35, 'Leeds': 55, 'Sheffield': 50 },
  'Liverpool': { 'London': 135, 'Manchester': 35 },
  'Leeds': { 'London': 130, 'Manchester': 55, 'Sheffield': 40, 'Newcastle': 90 },
  'Sheffield': { 'London': 120, 'Manchester': 50, 'Leeds': 40 },
  'Newcastle': { 'London': 170, 'Edinburgh': 90, 'Leeds': 90 },
  'Edinburgh': { 'London': 265, 'Glasgow': 50, 'Newcastle': 90 },
  'Glasgow': { 'London': 270, 'Edinburgh': 50 },
  'Cardiff': { 'London': 120, 'Bristol': 50 },
  'Cambridge': { 'London': 50 },
  'Oxford': { 'London': 60 },
  // Eurostar + EU HSR
  'London': { 'Paris': 135, 'Brussels': 120, 'Amsterdam': 225 },
  'Paris': { 'Lyon': 120, 'Marseille': 195, 'Brussels': 80 },
  'Frankfurt': { 'Munich': 195, 'Berlin': 240, 'Cologne': 60 },
  'Madrid': { 'Barcelona': 155, 'Seville': 150 },
  'Rome': { 'Milan': 175, 'Florence': 95 },
};

const LONDON_AIRPORT_ACCESS = { 'LHR': 45, 'LGW': 35, 'STN': 50, 'LTN': 45, 'LCY': 25 };

function getTrainTime(fromCity, toCity) {
  return RAIL_TIMES[fromCity]?.[toCity] || RAIL_TIMES[toCity]?.[fromCity] || null;
}

function getTrainThenFlyTime(originCity, destAirportCode) {
  const toKingsX = RAIL_TIMES[originCity]?.['London'];
  if (!toKingsX) return null;

  let best = Infinity;
  for (const [londonAirport, accessTime] of Object.entries(LONDON_AIRPORT_ACCESS)) {
    const flightTime = getFlightTime(londonAirport, destAirportCode);
    if (flightTime) {
      const overhead = getAirportOverhead(londonAirport, destAirportCode);
      const total = toKingsX + 30 + accessTime + overhead.dep + flightTime + overhead.arr;
      best = Math.min(best, total);
    }
  }

  return best < Infinity ? best : null;
}
```

---

## sanity checks

**automated test script:** `scripts/sanity-checks.py`

```python
import json
import math

def haversine(coord1, coord2):
    R = 6371
    lat1, lat2 = math.radians(coord1[1]), math.radians(coord2[1])
    dlat = math.radians(coord2[1] - coord1[1])
    dlng = math.radians(coord2[0] - coord1[0])
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def estimate_flight(dist_km):
    if dist_km < 500: return dist_km / 400 * 60 + 30
    if dist_km < 1500: return dist_km / 550 * 60 + 25
    if dist_km < 4000: return dist_km / 700 * 60 + 25
    if dist_km < 8000: return dist_km / 800 * 60 + 25
    return dist_km / 850 * 60 + 30

airports = json.load(open("data/airports.json"))
routes = json.load(open("data/routes.json"))

TESTS = [
    # (from, to, expected_flight_min, tolerance)
    # Flight time sanity (distance-based estimation)
    ("LHR", "CDG", 75, 20),     # 350km, actual ~75min
    ("LHR", "JFK", 480, 60),    # 5500km, actual ~480min
    ("LHR", "SYD", 1320, 120),  # 17000km, actual ~1320min
    ("JFK", "LAX", 330, 40),    # 3980km, actual ~330min
    ("SIN", "SYD", 480, 60),    # 6300km, actual ~480min

    # Route existence
    ("LHR", "JFK", "route_exists", None),
    ("BRS", "DUB", "route_exists", None),
    ("LHR", "SYD", "route_exists", None),  # via hub or direct
]

print("=== SANITY CHECKS ===\n")

errors = []

for test in TESTS:
    src, dst = test[0], test[1]

    if test[2] == "route_exists":
        exists = dst in routes.get(src, []) or src in routes.get(dst, [])
        status = "✓" if exists else "✗"
        print(f"{status} {src}-{dst}: route {'exists' if exists else 'MISSING'}")
        if not exists:
            errors.append(f"{src}-{dst} route missing")
    else:
        expected, tolerance = test[2], test[3]
        src_coords = [airports[src]["lng"], airports[src]["lat"]]
        dst_coords = [airports[dst]["lng"], airports[dst]["lat"]]
        dist = haversine(src_coords, dst_coords)
        estimated = estimate_flight(dist)
        diff = abs(estimated - expected)
        status = "✓" if diff <= tolerance else "✗"
        print(f"{status} {src}-{dst}: {dist:.0f}km, estimated {estimated:.0f}min (expected {expected}±{tolerance})")
        if diff > tolerance:
            errors.append(f"{src}-{dst} flight time off by {diff:.0f}min")

# Ground transport checks
print("\n=== GROUND TRANSPORT CHECKS ===\n")
try:
    ground_europe = json.load(open("data/ground/europe.json"))

    # Bristol airport should have cells around it
    brs_cells = ground_europe.get("BRS", {})
    print(f"✓ BRS has {len(brs_cells)} ground cells")

    # LHR should have more (bigger hub area)
    lhr_cells = ground_europe.get("LHR", {})
    print(f"✓ LHR has {len(lhr_cells)} ground cells")

    if len(brs_cells) < 100:
        errors.append("BRS has too few ground cells")
    if len(lhr_cells) < 200:
        errors.append("LHR has too few ground cells")
except FileNotFoundError:
    print("✗ Ground data not yet computed")
    errors.append("Ground data missing")

print("\n" + "="*40)
if errors:
    print(f"FAILED: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
else:
    print("ALL CHECKS PASSED")
```

**visual validation (via Chrome):**
after integration, capture screenshots and verify:
1. **artery effect visible** - motorway corridors show as faster access fingers
2. **terrain shadows** - mountainous areas (Alps, Rockies) show slower times
3. **hub patterns** - cells near major airports (LHR, JFK) are greener
4. **color gradients** - smooth transitions, no weird discontinuities
5. **remote areas** - Alaska, outback, Patagonia show as dark (far from airports)

**expected results:**

| route | distance | estimated flight | actual | overhead | total |
|-------|----------|------------------|--------|----------|-------|
| Bristol→Paris | 500km | ~85min | ~80min | 90min | ~4h |
| Bristol→Edinburgh | 500km | ~85min fly | 265min train | 65min fly | train wins ~4.5h |
| Bristol→Tokyo | 9500km | ~750min | via LHR | 135min | ~17h |
| NYC→LA | 3980km | ~330min | ~330min | 80min | ~7h |
| Cincinnati→London | 6300km | ~520min | ~520min | 135min | ~12h |

---

## file structure

```
jetspan/
  isochrone.html              # main visualization
  data/
    airports.json             # ~500KB
    routes.json               # ~2MB
    status.json               # metadata
    ground/
      europe.json             # ~15MB
      north-america.json      # ~10MB
      asia.json               # ~8MB
      middle-east.json        # ~3MB
      oceania.json            # ~2MB
      south-america.json      # ~3MB
      africa.json             # ~3MB
      other.json              # ~1MB
  scripts/
    fetch-airports.py
    crawl-amadeus.py
    fetch-openflights.py
    compute-ground-times.py
    build-status.py
    sanity-checks.py
  raw/                        # intermediate files (gitignored)
  plans/
    improved-travel-data.md
```

---

## execution checklist

### phase 1: data pipeline (no auth required)

- [ ] create directory structure: `scripts/`, `data/`, `data/ground/`, `raw/`
- [ ] add `raw/` to `.gitignore`
- [ ] `python scripts/fetch-airports.py`
  - [ ] verify: ~2000+ airports in raw csv
  - [ ] verify: ~800+ airports after filtering (large/medium with IATA)
  - [ ] sanity: LHR, JFK, BRS, NRT all present
- [ ] `python scripts/fetch-openflights.py`
  - [ ] verify: routes parsed into raw/openflights-routes.json
  - [ ] sanity: LHR has 100+ destinations
- [ ] `python scripts/sanity-checks.py` (airports-only mode)

### phase 1b: amadeus (needs API creds)

- [ ] sign up: developers.amadeus.com
- [ ] set env vars: `AMADEUS_API_KEY`, `AMADEUS_API_SECRET`
- [ ] `python scripts/crawl-amadeus.py`
  - [ ] checkpoint file saves every 50 airports
  - [ ] resumable if interrupted
- [ ] `python scripts/validate-routes.py` (compare amadeus vs openflights)
- [ ] `python scripts/sanity-checks.py` (full route checks)

### phase 1d: osrm (heavyweight)

- [ ] install docker
- [ ] download regional OSM extracts (~50GB total)
- [ ] process with osrm-backend (hours per region)
- [ ] `python scripts/compute-ground-times.py`
  - [ ] checkpoint every 20 airports
  - [ ] output: data/ground/{region}.json files
- [ ] verify ground data sizes reasonable

### phase 2: integrate into isochrone.html

- [ ] add data loading layer (loadCoreData, loadGroundData)
- [ ] implement ensureGroundDataLoaded pattern
- [ ] update calculateTravelTime to use new data
- [ ] test with bristol origin, europe ground data
- [ ] test origin switching (lazy load triggers)

### phase 3-5: enhancements

- [ ] variable airport overhead (domestic/schengen/international)
- [ ] hub routing (1-stop via major hubs)
- [ ] UK/EU rail integration

### validation

- [ ] visual check: motorway "arteries" visible
- [ ] visual check: mountain areas slower (alps, rockies)
- [ ] visual check: hub airports create green zones
- [ ] spot check: bristol→paris ~4h, nyc→la ~7h

---

## manual steps required

1. **Amadeus account:** sign up at developers.amadeus.com, get API key/secret
2. **OSRM setup:** download regional OSM extracts, run docker commands
3. **SimpleMaps:** unzip `World Cities Database v1.901.zip` (if using city data)

---

---

## origin→airport ground time (using OSRM)

current code uses hardcoded `groundTimeMinutes` in ORIGINS. should use OSRM lookup.

**approach:** pre-compute ground times from each origin city center to nearby airports.

```python
# in compute-ground-times.py, also compute for origin cities
ORIGIN_CITIES = {
    "Bristol": {"lat": 51.454, "lng": -2.587, "airports": ["BRS", "LHR", "LGW", "BHX"]},
    "London": {"lat": 51.509, "lng": -0.118, "airports": ["LHR", "LGW", "STN", "LTN", "LCY"]},
    "Paris": {"lat": 48.857, "lng": 2.352, "airports": ["CDG", "ORY"]},
    "New York": {"lat": 40.713, "lng": -74.006, "airports": ["JFK", "EWR", "LGA"]},
    "Los Angeles": {"lat": 34.052, "lng": -118.244, "airports": ["LAX", "BUR", "SNA"]},
    "Tokyo": {"lat": 35.690, "lng": 139.692, "airports": ["NRT", "HND"]},
    "Sydney": {"lat": -33.868, "lng": 151.209, "airports": ["SYD"]},
    "Dubai": {"lat": 25.276, "lng": 55.296, "airports": ["DXB", "DWC"]},
    "São Paulo": {"lat": -23.550, "lng": -46.633, "airports": ["GRU", "CGH"]},
    "Cape Town": {"lat": -33.925, "lng": 18.424, "airports": ["CPT"]},
    "Cincinnati": {"lat": 39.103, "lng": -84.512, "airports": ["CVG", "DAY"]},
}

origin_ground_times = {}
for city, info in ORIGIN_CITIES.items():
    origin_ground_times[city] = {}
    for airport in info["airports"]:
        apt = airports.get(airport)
        if apt:
            time = query_osrm_single([info["lng"], info["lat"]], [apt["lng"], apt["lat"]])
            if time:
                origin_ground_times[city][airport] = round(time)

with open("data/origin-ground-times.json", "w") as f:
    json.dump(origin_ground_times, f)
```

**output:** `data/origin-ground-times.json` (~1KB)

**JS usage:**
```javascript
let ORIGIN_GROUND_TIMES = {};
// load with core data

function getOriginToAirportTime(originCity, airportCode) {
  return ORIGIN_GROUND_TIMES[originCity]?.[airportCode] ??
         estimateFallback(ORIGINS[originCity].coordinates, AIRPORTS_DATA[airportCode]);
}
```

---

## related research / alternatives

**OSM-based isochrone projects (no flight data - opportunity for JetSpan):**

| project | URL | notes |
|---------|-----|-------|
| OpenRouteService | openrouteservice.org | free API, isochrone endpoint |
| Valhalla | github.com/valhalla | self-hosted, used by Mapbox |
| GraphHopper | graphhopper.com | has isochrone API |
| OSRM | project-osrm.org | experimental isochrone support |
| Targomo | targomo.com | commercial, nice viz |
| TravelTime | traveltime.com | commercial, global coverage |

**none combine flight + ground transport** - JetSpan's unique value proposition.

**potential future approach:** use their isochrone polygons for ground transport instead of H3 cells, overlay with flight network. would simplify ground compute but lose H3 consistency.

---

## deferred (v2)

- "any city" picker (current: 11 fixed cities)
- real-time flight schedules
- ferry routes
- 2-stop hub routing
- mobile optimization
- service worker caching
- binary data format (protobuf/msgpack)
