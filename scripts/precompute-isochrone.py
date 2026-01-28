#!/usr/bin/env python3
"""
Pre-compute isochrone data for a specific origin city.

This script pre-computes travel times from a given origin to all H3 cells
at multiple resolutions, storing results as JSON for instant lookup.

Usage:
    python scripts/precompute-isochrone.py bristol
    python scripts/precompute-isochrone.py --all  # all configured origins

Output:
    data/isochrones/{origin}.json

Structure:
    {
        "origin": "bristol",
        "computed": "2024-01-28T...",
        "resolutions": {
            "1": { "h3index": {"time": 180, "route": {...}}, ... },
            "2": { ... },
            ...
        }
    }
"""

import json
import time
import math
import argparse
from pathlib import Path
from datetime import datetime

# try to import h3, install hint if missing
try:
    import h3
except ImportError:
    print("h3 not installed. run: pip install h3")
    exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

ORIGINS = {
    "bristol": {
        "name": "Bristol, UK",
        "coords": [-2.587, 51.454],  # [lng, lat]
        "airports": [
            {"code": "BRS", "coords": [-2.719, 51.382], "ground_min": 25},
            {"code": "LHR", "coords": [-0.461, 51.470], "ground_min": 120},
            {"code": "LGW", "coords": [-0.190, 51.148], "ground_min": 150},
            {"code": "BHX", "coords": [-1.748, 52.454], "ground_min": 90},
        ]
    }
}

# resolutions to pre-compute
# - res 1-4: compute ALL cells globally
# - res 5+: skip (2M+ cells, too slow, diminishing returns)
RESOLUTIONS = [1, 2, 3, 4]

# skip cells >300km from any airport (water/remote)
WATER_SKIP_DISTANCE_KM = 300

# airport overhead times (minutes)
DEPARTURE_OVERHEAD = 90  # check-in, security, boarding
ARRIVAL_OVERHEAD_DOMESTIC = 30
ARRIVAL_OVERHEAD_INTL = 60


# =============================================================================
# DATA LOADING
# =============================================================================

def load_airports():
    """load airports.json"""
    path = Path(__file__).parent.parent / "data" / "airports.json"
    with open(path) as f:
        return json.load(f)


def load_routes():
    """load routes.json"""
    path = Path(__file__).parent.parent / "data" / "routes.json"
    with open(path) as f:
        return json.load(f)


# =============================================================================
# DISTANCE & FLIGHT TIME CALCULATIONS
# =============================================================================

def haversine_km(lat1, lon1, lat2, lon2):
    """calculate great-circle distance in km"""
    R = 6371  # earth radius km
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def estimate_flight_time(dist_km):
    """estimate flight time in minutes based on distance"""
    if dist_km < 500:
        return round(dist_km / 400 * 60 + 20)  # short haul
    elif dist_km < 1500:
        return round(dist_km / 550 * 60 + 25)
    elif dist_km < 4000:
        return round(dist_km / 700 * 60 + 25)
    elif dist_km < 8000:
        return round(dist_km / 800 * 60 + 25)
    else:
        return round(dist_km / 850 * 60 + 30)  # ultra long haul


def estimate_ground_time(dist_km):
    """estimate ground travel time from airport to destination"""
    # assume ~60 km/h average speed
    return round(dist_km / 60 * 60)


# =============================================================================
# TRAVEL TIME CALCULATION
# =============================================================================

def calculate_travel_time(origin_cfg, dest_lat, dest_lng, airports, routes):
    """
    Calculate total travel time from origin to destination.

    Returns: (total_minutes, route_info) or (None, None) if unreachable
    """
    best_time = float('inf')
    best_route = None

    # find nearest airports to destination
    dest_airports = []
    for code, airport in airports.items():
        dist = haversine_km(dest_lat, dest_lng, airport["lat"], airport["lng"])
        if dist < WATER_SKIP_DISTANCE_KM:
            dest_airports.append((code, airport, dist))

    # sort by distance, take top 5
    dest_airports.sort(key=lambda x: x[2])
    dest_airports = dest_airports[:5]

    if not dest_airports:
        return None, None  # no nearby airports = water/remote

    # try each origin airport -> dest airport combination
    for origin_apt in origin_cfg["airports"]:
        origin_code = origin_apt["code"]
        ground_to_origin = origin_apt["ground_min"]

        # get routes from this origin
        origin_routes = routes.get(origin_code, [])

        for dest_code, dest_apt, ground_from_dest_km in dest_airports:
            # check if direct route exists
            if dest_code in origin_routes:
                # calculate flight time
                flight_dist = haversine_km(
                    airports[origin_code]["lat"], airports[origin_code]["lng"],
                    dest_apt["lat"], dest_apt["lng"]
                )
                flight_time = estimate_flight_time(flight_dist)

                # determine if international
                origin_country = airports.get(origin_code, {}).get("country", "")
                dest_country = dest_apt.get("country", "")
                arrival_overhead = ARRIVAL_OVERHEAD_INTL if origin_country != dest_country else ARRIVAL_OVERHEAD_DOMESTIC

                # ground time from dest airport to final destination
                ground_from_dest = estimate_ground_time(ground_from_dest_km)

                # total time
                total = ground_to_origin + DEPARTURE_OVERHEAD + flight_time + arrival_overhead + ground_from_dest

                if total < best_time:
                    best_time = total
                    best_route = {
                        "origin_airport": origin_code,
                        "dest_airport": dest_code,
                        "is_direct": True,
                        "ground_to": ground_to_origin,
                        "overhead": DEPARTURE_OVERHEAD,
                        "flight": flight_time,
                        "arrival": arrival_overhead,
                        "ground_from": ground_from_dest,
                    }

    if best_time == float('inf'):
        return None, None

    return best_time, best_route


# =============================================================================
# H3 CELL ITERATION
# =============================================================================

def get_h3_cells_global(res):
    """Get ALL H3 cells at a given resolution (for low res only)."""
    base_cells = h3.get_res0_cells()

    if res == 0:
        return list(base_cells)

    all_cells = []
    for base in base_cells:
        children = h3.cell_to_children(base, res)
        all_cells.extend(children)

    return all_cells


def get_h3_cells_bounded(res, center_lat, center_lng, radius_km):
    """
    Get H3 cells within radius_km of center point.
    Uses h3.grid_disk to expand from center.
    """
    # get center cell at target resolution
    center_cell = h3.latlng_to_cell(center_lat, center_lng, res)

    # estimate number of rings needed
    # cell edge length varies by resolution
    edge_lengths_km = {
        0: 1107.71, 1: 418.68, 2: 158.24, 3: 59.81,
        4: 22.61, 5: 8.54, 6: 3.23
    }
    edge_km = edge_lengths_km.get(res, 10)
    rings = int(radius_km / edge_km) + 1

    # get disk of cells
    cells = h3.grid_disk(center_cell, rings)
    return list(cells)


def cell_to_lat_lng(cell):
    """convert h3 cell to lat/lng"""
    lat, lng = h3.cell_to_latlng(cell)
    return lat, lng


# =============================================================================
# MAIN PRECOMPUTE
# =============================================================================

def precompute_origin(origin_name, airports, routes):
    """Pre-compute isochrone data for a single origin."""

    if origin_name not in ORIGINS:
        print(f"unknown origin: {origin_name}")
        print(f"available: {list(ORIGINS.keys())}")
        return None

    origin_cfg = ORIGINS[origin_name]
    print(f"\n{'='*60}")
    print(f"pre-computing isochrone for {origin_cfg['name']}")
    print(f"{'='*60}\n")

    result = {
        "origin": origin_name,
        "origin_name": origin_cfg["name"],
        "origin_coords": origin_cfg["coords"],
        "computed": datetime.now().isoformat(),
        "resolutions": {}
    }

    for res in RESOLUTIONS:
        print(f"\nresolution {res}...")
        start = time.time()

        cells = get_h3_cells_global(res)
        print(f"  {len(cells):,} cells to process")

        res_data = {}
        computed = 0
        skipped = 0

        for i, cell in enumerate(cells):
            if i % 10000 == 0 and i > 0:
                pct = i / len(cells) * 100
                elapsed = time.time() - start
                rate = i / elapsed
                eta = (len(cells) - i) / rate
                print(f"  {pct:.1f}% ({i:,}/{len(cells):,}) - {rate:.0f} cells/s - eta {eta:.0f}s")

            lat, lng = cell_to_lat_lng(cell)

            travel_time, route = calculate_travel_time(
                origin_cfg, lat, lng, airports, routes
            )

            if travel_time is not None:
                res_data[cell] = {
                    "time": travel_time,
                    "route": route
                }
                computed += 1
            else:
                skipped += 1

        elapsed = time.time() - start
        print(f"  done in {elapsed:.1f}s: {computed:,} computed, {skipped:,} skipped")

        result["resolutions"][str(res)] = res_data

    return result


def save_result(origin_name, data):
    """Save precomputed data to JSON file."""
    out_dir = Path(__file__).parent.parent / "data" / "isochrones"
    out_dir.mkdir(exist_ok=True)

    out_path = out_dir / f"{origin_name}.json"

    print(f"\nsaving to {out_path}...")
    with open(out_path, "w") as f:
        json.dump(data, f)  # no indent for smaller file

    # get file size
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"saved {size_mb:.1f} MB")

    return out_path


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Pre-compute isochrone data")
    parser.add_argument("origin", nargs="?", default="bristol",
                        help="Origin city to compute (default: bristol)")
    parser.add_argument("--all", action="store_true",
                        help="Compute all configured origins")
    args = parser.parse_args()

    print("loading data...")
    airports = load_airports()
    routes = load_routes()
    print(f"  {len(airports):,} airports, {sum(len(v) for v in routes.values()):,} routes")

    origins_to_compute = list(ORIGINS.keys()) if args.all else [args.origin]

    for origin in origins_to_compute:
        data = precompute_origin(origin, airports, routes)
        if data:
            save_result(origin, data)

    print("\ndone!")


if __name__ == "__main__":
    main()
