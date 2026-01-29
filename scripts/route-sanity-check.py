#!/usr/bin/env python3
"""
sanity check: mimic the UI travel time calculation and flag
routes that don't actually exist in the route data.

tests whether bristol can "reach" US regional airports like
LAF, CMI, DBQ, MSN etc via direct flights (spoiler: it can't)
"""

import json
from math import radians, cos, sin, asin, sqrt

# load data
with open('data/routes.json') as f:
    routes = json.load(f)

with open('data/airports.json') as f:
    airports = json.load(f)

def haversine(lng1, lat1, lng2, lat2):
    """distance in km between two points"""
    lng1, lat1, lng2, lat2 = map(radians, [lng1, lat1, lng2, lat2])
    dlng = lng2 - lng1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
    return 2 * 6371 * asin(sqrt(a))

def has_route(from_code, to_code):
    """check if direct route exists (either direction)"""
    if from_code in routes and to_code in routes[from_code]:
        return True
    if to_code in routes and from_code in routes[to_code]:
        return True
    return False

def estimate_flight_minutes(dist_km):
    """mimic the UI's estimateFlightMinutes function"""
    if dist_km < 500:
        return round(dist_km / 400 * 60 + 30)
    if dist_km < 1500:
        return round(dist_km / 550 * 60 + 25)
    if dist_km < 4000:
        return round(dist_km / 700 * 60 + 25)
    if dist_km < 8000:
        return round(dist_km / 800 * 60 + 25)
    return round(dist_km / 850 * 60 + 30)

# bristol origin airports (from ORIGINS config)
bristol_airports = [
    {'code': 'BRS', 'ground_time': 25},
    {'code': 'LHR', 'ground_time': 120},
    {'code': 'LGW', 'ground_time': 150},
    {'code': 'BHX', 'ground_time': 90},
]

# problematic US regional airports to test
test_dest_airports = [
    'LAF',  # lafayette IN
    'CMI',  # champaign IL
    'BMI',  # bloomington IL
    'DBQ',  # dubuque IA
    'MSN',  # madison WI
    'SPI',  # springfield IL
    'PIA',  # peoria IL
    'MLI',  # moline IL
    'CID',  # cedar rapids IA
    'ALO',  # waterloo IA
    'SUX',  # sioux city IA
]

print("=" * 70)
print("ROUTE SANITY CHECK: bristol -> US regional airports")
print("=" * 70)
print()

for dest_code in test_dest_airports:
    if dest_code not in airports:
        print(f"{dest_code}: not in airports.json")
        continue

    dest_apt = airports[dest_code]
    dest_coords = (dest_apt['lng'], dest_apt['lat'])

    print(f"\n{dest_code} ({dest_apt['name'][:40]})")
    print("-" * 50)

    # check each origin airport (mimics UI loop)
    for origin in bristol_airports:
        origin_code = origin['code']
        if origin_code not in airports:
            continue

        origin_apt = airports[origin_code]
        origin_coords = (origin_apt['lng'], origin_apt['lat'])

        dist = haversine(origin_coords[0], origin_coords[1],
                        dest_coords[0], dest_coords[1])

        route_exists = has_route(origin_code, dest_code)

        # mimic getFlightTime behavior
        if route_exists:
            flight_time = estimate_flight_minutes(dist)
            status = "REAL ROUTE"
        else:
            # UI bug: estimates flight anyway!
            flight_time = estimate_flight_minutes(dist)
            status = "NO ROUTE (but UI would calc anyway)"

        # total time calc (simplified)
        ground_to = origin['ground_time']
        overhead = 90
        arrival = 60  # international
        ground_from = round(dist / 40 * 60 * 0.1)  # rough estimate

        total = ground_to + overhead + flight_time + arrival + ground_from

        print(f"  {origin_code}: {status}")
        print(f"       distance: {dist:.0f}km, flight: {flight_time}min")
        if not route_exists:
            print(f"       total (if calculated): {total}min = {total//60}h {total%60}m")

print()
print("=" * 70)
print("CONCLUSION")
print("=" * 70)
print("""
the bug is in calculateTotalTravelTime() around line 1361-1368:

    let flight = getFlightTime(originAirport.code, destAirport.code);

    // If no direct flight, estimate based on distance
    if (flight === null) {
      flight = estimateFlightFromDistance(originCoords, destAirport.coordinates);
    }

when getFlightTime returns null (no route exists), the code ESTIMATES
the flight time from distance instead of SKIPPING that airport pair.

FIX: change the fallback to 'continue' instead of estimating:

    if (flight === null) {
      continue;  // skip - no route exists
    }
""")
