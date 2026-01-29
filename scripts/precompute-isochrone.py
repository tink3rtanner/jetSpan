#!/usr/bin/env python3
"""
Pre-compute isochrone data for a specific origin city.

Uses dijkstra_router for multi-stop routing (run once, O(1) per airport),
then iterates all H3 cells globally at each resolution and finds the
best reachable airport for each cell.

Usage:
    python scripts/precompute-isochrone.py bristol
    python scripts/precompute-isochrone.py --all

Output:
    data/isochrones/{origin}.json
"""

import json
import sys
import os
import time
import math
import argparse
from pathlib import Path
from datetime import datetime

# add scripts dir to path so we can import dijkstra_router
sys.path.insert(0, os.path.dirname(__file__))
from dijkstra_router import FlightGraph, DijkstraRouter, ORIGINS as DJ_ORIGINS

try:
    import h3
except ImportError:
    print("h3 not installed. run: pip install h3")
    exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

# resolutions to pre-compute
# res 5+ = 2M+ cells, too slow, diminishing returns
RESOLUTIONS = [1, 2, 3, 4]

# max ground distance from airport to cell (km)
MAX_GROUND_KM = 400

# ground speed estimate (where no OSRM data)
DEFAULT_GROUND_KPH = 40


# =============================================================================
# DATA LOADING
# =============================================================================

def load_airports():
    path = Path(__file__).parent.parent / "data" / "airports.json"
    with open(path) as f:
        return json.load(f)

def load_routes():
    path = Path(__file__).parent.parent / "data" / "routes.json"
    with open(path) as f:
        return json.load(f)


# =============================================================================
# UTILITIES
# =============================================================================

def haversine_km(lat1, lon1, lat2, lon2):
    """great-circle distance in km"""
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def estimate_ground_minutes(dist_km, speed_kph=DEFAULT_GROUND_KPH):
    return round((dist_km / speed_kph) * 60)


# =============================================================================
# H3 CELL ITERATION
# =============================================================================

def get_h3_cells_global(res):
    """all H3 cells at a given resolution"""
    base_cells = h3.get_res0_cells()
    if res == 0:
        return list(base_cells)
    all_cells = []
    for base in base_cells:
        all_cells.extend(h3.cell_to_children(base, res))
    return all_cells


# =============================================================================
# SPATIAL INDEX
# =============================================================================

def build_airport_spatial_index(best_times, airports, index_res=2):
    """
    bucket reachable airports into h3 res-2 cells for fast lookup.
    instead of checking all ~3k airports per cell, we only check
    airports in nearby h3-res2 buckets (~50-100 per cell).
    """
    index = {}  # h3_res2_cell -> [(code, lat, lng, airport_result)]
    for code, result in best_times.items():
        apt = airports.get(code)
        if not apt:
            continue
        try:
            bucket = h3.latlng_to_cell(apt['lat'], apt['lng'], index_res)
        except Exception:
            continue
        if bucket not in index:
            index[bucket] = []
        index[bucket].append((code, apt['lat'], apt['lng'], result))

    print(f"  spatial index: {len(index)} buckets, {sum(len(v) for v in index.values())} entries")
    return index


def query_cell_fast(lat, lng, spatial_index, airports, origin_cfg,
                    index_res=2, k_rings=3):
    """
    find best route to cell at (lat, lng) using spatial index.
    returns (total_minutes, route_info) or (None, None).
    """
    # check nearby buckets
    try:
        center_bucket = h3.latlng_to_cell(lat, lng, index_res)
    except Exception:
        return None, None

    nearby_buckets = h3.grid_disk(center_bucket, k_rings)

    # collect candidate airports from nearby buckets
    best_total = float('inf')
    best_info = None

    for bucket in nearby_buckets:
        for code, apt_lat, apt_lng, result in spatial_index.get(bucket, []):
            dist_km = haversine_km(lat, lng, apt_lat, apt_lng)
            if dist_km > MAX_GROUND_KM:
                continue

            ground_from = estimate_ground_minutes(dist_km)

            # arrival overhead (international vs domestic)
            origin_country = airports.get(result.origin_airport, {}).get('country', '')
            dest_country = airports.get(code, {}).get('country', '')
            arrival = 60 if origin_country != dest_country else 30

            total = result.total_time + ground_from + arrival

            if total < best_total:
                best_total = total

                # decompose the dijkstra result for tooltip breakdown
                # result.total_time = ground_to + overhead(90) + flights + stops*(90+30)
                origin_ground = next(
                    (a['ground_time'] for a in origin_cfg['airports']
                     if a['code'] == result.origin_airport), 0
                )
                overhead = 90
                connection_cost = result.stops * (90 + 30)
                flights_only = result.total_time - origin_ground - overhead - connection_cost

                best_info = {
                    "origin_airport": result.origin_airport,
                    "dest_airport": code,
                    "is_direct": result.stops == 0,
                    "stops": result.stops,
                    "path": result.path,
                    "ground_to": origin_ground,
                    "overhead": overhead,
                    "flight": max(0, flights_only),  # guard against rounding
                    "connections": connection_cost,
                    "arrival": arrival,
                    "ground_from": ground_from,
                }

    if best_total == float('inf'):
        return None, None

    # also check drive-only for nearby destinations
    origin_coords = origin_cfg['coords']  # (lng, lat) tuple
    drive_dist = haversine_km(lat, lng, origin_coords[1], origin_coords[0])
    if drive_dist < MAX_GROUND_KM:
        drive_time = estimate_ground_minutes(drive_dist)
        if drive_time < best_total:
            return drive_time, {
                "origin_airport": "drive",
                "dest_airport": "drive",
                "is_direct": True,
                "stops": -1,
                "path": ["drive"],
                "ground_to": drive_time,
                "overhead": 0,
                "flight": 0,
                "connections": 0,
                "arrival": 0,
                "ground_from": 0,
            }

    return best_total, best_info


# =============================================================================
# MAIN PRECOMPUTE
# =============================================================================

def precompute_origin(origin_name, airports, routes):
    """pre-compute isochrone data using dijkstra routing."""

    if origin_name not in DJ_ORIGINS:
        print(f"unknown origin: {origin_name}")
        print(f"available: {list(DJ_ORIGINS.keys())}")
        return None

    origin_cfg = DJ_ORIGINS[origin_name]
    print(f"\n{'='*60}")
    print(f"pre-computing isochrone for {origin_cfg['name']}")
    print(f"{'='*60}")

    # step 1: run dijkstra (once)
    print("\nrunning dijkstra...")
    t0 = time.time()
    graph = FlightGraph(routes, airports)
    router = DijkstraRouter(graph, airports, origin_name)
    best_times = router.run()
    dijkstra_time = time.time() - t0

    # stats
    by_stops = {}
    for r in best_times.values():
        by_stops[r.stops] = by_stops.get(r.stops, 0) + 1
    print(f"  dijkstra done in {dijkstra_time:.1f}s: {len(best_times)} airports reachable")
    print(f"  direct={by_stops.get(0,0)}, 1-stop={by_stops.get(1,0)}, 2-stop={by_stops.get(2,0)}")

    # step 2: build spatial index of reachable airports
    print("\nbuilding spatial index...")
    spatial_index = build_airport_spatial_index(best_times, airports)

    # step 3: iterate cells at each resolution
    result = {
        "origin": origin_name,
        "origin_name": origin_cfg["name"],
        "origin_coords": list(origin_cfg["coords"]),
        "computed": datetime.now().isoformat(),
        "routing": "dijkstra",
        "airports_reachable": len(best_times),
        "resolutions": {}
    }

    total_computed = 0
    total_skipped = 0
    total_time_all = time.time()

    for res in RESOLUTIONS:
        print(f"\nresolution {res}...")
        start = time.time()

        cells = get_h3_cells_global(res)
        print(f"  {len(cells):,} cells to process")

        res_data = {}
        computed = 0
        skipped = 0

        for i, cell in enumerate(cells):
            # progress
            if i % 10000 == 0 and i > 0:
                pct = i / len(cells) * 100
                elapsed = time.time() - start
                rate = i / elapsed
                eta = (len(cells) - i) / rate
                print(f"  {pct:.1f}% ({i:,}/{len(cells):,}) - {rate:.0f} cells/s - eta {eta:.0f}s")

            lat, lng = h3.cell_to_latlng(cell)

            travel_time, route = query_cell_fast(
                lat, lng, spatial_index, airports, origin_cfg
            )

            if travel_time is not None:
                # compact format to keep file <10 MB:
                # t=time, o=origin airport, a=dest airport, s=stops
                # breakdown is derived client-side from airport data
                if route and route.get("stops", 0) == -1:
                    # drive-only cell
                    res_data[cell] = {"t": travel_time, "d": 1}
                else:
                    res_data[cell] = {
                        "t": travel_time,
                        "o": route["origin_airport"],
                        "a": route["dest_airport"],
                        "s": route["stops"],
                    }
                computed += 1
            else:
                skipped += 1

        elapsed = time.time() - start
        print(f"  done in {elapsed:.1f}s: {computed:,} computed, {skipped:,} skipped")

        result["resolutions"][str(res)] = res_data
        total_computed += computed
        total_skipped += skipped

    total_elapsed = time.time() - total_time_all
    print(f"\ntotal: {total_computed:,} cells in {total_elapsed:.1f}s ({total_skipped:,} skipped)")
    print(f"  dijkstra: {dijkstra_time:.1f}s")
    print(f"  cell iteration: {total_elapsed - dijkstra_time:.1f}s")

    return result


def save_result(origin_name, data):
    """save precomputed data to JSON."""
    out_dir = Path(__file__).parent.parent / "data" / "isochrones"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{origin_name}.json"

    print(f"\nsaving to {out_path}...")
    with open(out_path, "w") as f:
        json.dump(data, f)

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"saved {size_mb:.1f} MB")
    return out_path


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Pre-compute isochrone data (dijkstra)")
    parser.add_argument("origin", nargs="?", default="bristol",
                        help="Origin city to compute (default: bristol)")
    parser.add_argument("--all", action="store_true",
                        help="Compute all configured origins")
    args = parser.parse_args()

    print("loading data...")
    airports = load_airports()
    routes = load_routes()
    print(f"  {len(airports):,} airports, {sum(len(v) for v in routes.values()):,} routes")

    origins_to_compute = list(DJ_ORIGINS.keys()) if args.all else [args.origin]

    for origin in origins_to_compute:
        data = precompute_origin(origin, airports, routes)
        if data:
            save_result(origin, data)

    print("\ndone!")


if __name__ == "__main__":
    main()
