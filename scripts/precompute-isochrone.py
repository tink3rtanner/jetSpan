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

# base resolutions go in main JSON file (loaded on page init)
BASE_RESOLUTIONS = [1, 2, 3, 4]

# chunked resolutions: split into separate files grouped by parent cell
CHUNKED_RESOLUTIONS = [5, 6]

# which parent resolution to group chunks by
CHUNK_PARENT_RES = {5: 1, 6: 2}

# max ground distance from airport to cell (km)
MAX_GROUND_KM = 400

# ground speed estimate (where no OSRM data)
DEFAULT_GROUND_KPH = 40

# water cell detection: if OSRM time > haversine time * this ratio,
# the cell center is probably over water (OSRM routes around)
WATER_DETOUR_RATIO = 1.4


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

def load_osrm_ground_data():
    """load all OSRM ground time files from data/ground/*.json.
    returns {airport_code: {h3_res6_cell: minutes}}."""
    ground_dir = Path(__file__).parent.parent / "data" / "ground"
    osrm = {}
    if not ground_dir.exists():
        return osrm
    for f in ground_dir.glob("*.json"):
        if f.name.startswith("."):
            continue
        try:
            with open(f) as fh:
                data = json.load(fh)
            # each file is {airport_code: {h3_cell: minutes}}
            for code, cells in data.items():
                if code not in osrm:
                    osrm[code] = {}
                osrm[code].update(cells)
        except Exception as e:
            print(f"  warning: couldn't load {f.name}: {e}")
    if osrm:
        print(f"  OSRM ground data: {len(osrm)} airports ({', '.join(sorted(osrm.keys()))})")
    return osrm


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


def osrm_ground_time(osrm_data, airport_code, lat, lng):
    """look up OSRM driving time from airport to (lat, lng).
    returns minutes if found, None if airport has OSRM data but cell
    is unreachable (water/no road), or -1 if no OSRM data for airport."""
    apt_data = osrm_data.get(airport_code)
    if apt_data is None:
        return -1  # no OSRM data for this airport — caller should fallback
    # convert query point to h3 res 6 (matches OSRM crawl resolution)
    try:
        cell6 = h3.latlng_to_cell(lat, lng, 6)
    except Exception:
        return None
    minutes = apt_data.get(cell6)
    return minutes  # int if reachable, None if water/unreachable


def query_cell_fast(lat, lng, spatial_index, airports, origin_cfg,
                    osrm_data=None, index_res=2, k_rings=3):
    """
    find best route to cell at (lat, lng) using spatial index.
    uses OSRM ground data when available; falls back to haversine.
    returns (total_minutes, route_info) or (None, None).
    """
    if osrm_data is None:
        osrm_data = {}

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

            # ground_from: prefer OSRM, fall back to haversine
            osrm_time = osrm_ground_time(osrm_data, code, lat, lng)
            used_osrm = False
            if osrm_time is None or osrm_time == -1:
                # no OSRM data for this airport — haversine fallback
                ground_from = estimate_ground_minutes(dist_km)
            else:
                ground_from = osrm_time
                used_osrm = True

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
                    "osrm": used_osrm,
                }

    if best_total == float('inf'):
        return None, None

    # also check drive-only for nearby destinations
    # only use NEAREST origin airport OSRM (index 0) — using distant airports
    # like LHR would give wrong drive times (distance from LHR, not Bristol)
    origin_coords = origin_cfg['coords']  # (lng, lat) tuple
    drive_dist = haversine_km(lat, lng, origin_coords[1], origin_coords[0])
    if drive_dist < MAX_GROUND_KM:
        nearest_apt = origin_cfg['airports'][0]['code']  # e.g. BRS for Bristol
        osrm_time = osrm_ground_time(osrm_data, nearest_apt, lat, lng)

        if osrm_time == -1 or osrm_time is None:
            # no OSRM data for this airport, or cell has no OSRM entry
            # (OSRM crawl is sparse — missing entry != water)
            # fall back to haversine
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
                    "osrm": False,
                }
        else:
            # have OSRM time from nearest airport — use it
            # water filter: if OSRM >> haversine, routing around water
            hav_estimate = estimate_ground_minutes(drive_dist)
            if hav_estimate > 0 and osrm_time > hav_estimate * WATER_DETOUR_RATIO:
                pass  # skip — probable water cell
            elif osrm_time < best_total:
                return osrm_time, {
                    "origin_airport": "drive",
                    "dest_airport": "drive",
                    "is_direct": True,
                    "stops": -1,
                    "path": ["drive"],
                    "ground_to": osrm_time,
                    "overhead": 0,
                    "flight": 0,
                    "connections": 0,
                    "arrival": 0,
                    "ground_from": 0,
                    "osrm": True,
                }

    return best_total, best_info


# =============================================================================
# ROUTE TABLE
# =============================================================================

def build_route_table(best_times, graph):
    """
    build per-airport route table with full paths and per-leg flight times.
    this is the data the client needs for tooltips / route display.
    keyed by destination airport code.
    """
    routes = {}
    for code, result in best_times.items():
        # extract per-leg flight times from the graph edges
        legs = []
        for i in range(len(result.path) - 1):
            from_apt = result.path[i]
            to_apt = result.path[i + 1]
            ft = graph.edges.get((from_apt, to_apt), 0)
            legs.append(ft)
        routes[code] = {
            'p': result.path,   # full airport sequence
            'l': legs,          # per-leg flight minutes
            't': result.total_time,  # dijkstra total (ground_to + overhead + flights + connections)
            's': result.stops   # number of stops
        }
    return routes


# =============================================================================
# MAIN PRECOMPUTE
# =============================================================================

def compact_cell(travel_time, route):
    """convert query result to compact cell format {t, o, a, s, g?} or {t, d, g?}.
    g=1 means ground time used OSRM road data (vs haversine estimate)."""
    cell = {}
    if route and route.get("stops", 0) == -1:
        cell = {"t": travel_time, "d": 1}
    else:
        cell = {
            "t": travel_time,
            "o": route["origin_airport"],
            "a": route["dest_airport"],
            "s": route["stops"],
        }
    # only add g flag when OSRM was used (saves space — absence = haversine)
    if route and route.get("osrm"):
        cell["g"] = 1
    return cell


def iterate_resolution(res, spatial_index, airports, origin_cfg, osrm_data=None):
    """iterate all h3 cells at a resolution, return dict of cell -> compact data."""
    start = time.time()
    cells = get_h3_cells_global(res)
    print(f"  {len(cells):,} cells to process")

    res_data = {}
    computed = 0
    skipped = 0

    for i, cell in enumerate(cells):
        # progress every 50k cells (res 5-6 have millions)
        if i % 50000 == 0 and i > 0:
            pct = i / len(cells) * 100
            elapsed = time.time() - start
            rate = i / elapsed
            eta = (len(cells) - i) / rate
            print(f"  {pct:.1f}% ({i:,}/{len(cells):,}) - {rate:.0f} cells/s - eta {eta:.0f}s")

        lat, lng = h3.cell_to_latlng(cell)
        travel_time, route = query_cell_fast(
            lat, lng, spatial_index, airports, origin_cfg, osrm_data=osrm_data
        )

        if travel_time is not None:
            res_data[cell] = compact_cell(travel_time, route)
            computed += 1
        else:
            skipped += 1

    elapsed = time.time() - start
    print(f"  done in {elapsed:.1f}s: {computed:,} computed, {skipped:,} skipped")
    return res_data, computed, skipped, elapsed


def precompute_origin(origin_name, airports, routes):
    """pre-compute isochrone data using dijkstra routing."""

    if origin_name not in DJ_ORIGINS:
        print(f"unknown origin: {origin_name}")
        print(f"available: {list(DJ_ORIGINS.keys())}")
        return None, None, None

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

    # step 2: build route table (full paths + per-leg times for tooltips)
    print("\nbuilding route table...")
    route_table = build_route_table(best_times, graph)
    print(f"  {len(route_table)} airport routes")

    # step 3: load OSRM ground data (road-network driving times)
    print("\nloading OSRM ground data...")
    osrm_data = load_osrm_ground_data()

    # step 4: build spatial index of reachable airports
    print("\nbuilding spatial index...")
    spatial_index = build_airport_spatial_index(best_times, airports)

    # step 5: iterate cells at each resolution
    base_result = {
        "origin": origin_name,
        "origin_name": origin_cfg["name"],
        "origin_coords": list(origin_cfg["coords"]),
        "computed": datetime.now().isoformat(),
        "routing": "dijkstra",
        "airports_reachable": len(best_times),
        "resolutions": {}
    }

    # chunk_data: {res -> {parent_cell -> {cell -> data}}}
    chunk_data = {}

    total_computed = 0
    total_skipped = 0
    total_time_all = time.time()

    for res in BASE_RESOLUTIONS + CHUNKED_RESOLUTIONS:
        print(f"\nresolution {res}...")
        res_data, computed, skipped, elapsed = iterate_resolution(
            res, spatial_index, airports, origin_cfg, osrm_data=osrm_data
        )

        if res in BASE_RESOLUTIONS:
            # store in main JSON file
            base_result["resolutions"][str(res)] = res_data
        else:
            # group by parent cell for chunked output
            parent_res = CHUNK_PARENT_RES[res]
            chunks = {}
            for cell, data in res_data.items():
                parent = h3.cell_to_parent(cell, parent_res)
                if parent not in chunks:
                    chunks[parent] = {}
                chunks[parent][cell] = data
            chunk_data[res] = chunks
            print(f"  grouped into {len(chunks)} chunks (by res {parent_res} parent)")

        total_computed += computed
        total_skipped += skipped

    total_elapsed = time.time() - total_time_all
    print(f"\ntotal: {total_computed:,} cells in {total_elapsed:.1f}s ({total_skipped:,} skipped)")
    print(f"  dijkstra: {dijkstra_time:.1f}s")
    print(f"  cell iteration: {total_elapsed - dijkstra_time:.1f}s")

    return base_result, route_table, chunk_data


def save_result(origin_name, base_data, route_table, chunk_data):
    """save all precomputed data: base JSON + route table + chunk files."""
    base_dir = Path(__file__).parent.parent / "data" / "isochrones"
    base_dir.mkdir(exist_ok=True)

    # 1. save base file (res 1-4)
    base_path = base_dir / f"{origin_name}.json"
    print(f"\nsaving base file to {base_path}...")
    with open(base_path, "w") as f:
        json.dump(base_data, f)
    size_mb = base_path.stat().st_size / 1024 / 1024
    print(f"  base: {size_mb:.1f} MB")

    # 2. save route table
    origin_dir = base_dir / origin_name
    origin_dir.mkdir(exist_ok=True)
    routes_path = origin_dir / "routes.json"
    print(f"saving route table to {routes_path}...")
    with open(routes_path, "w") as f:
        json.dump(route_table, f)
    size_kb = routes_path.stat().st_size / 1024
    print(f"  routes: {size_kb:.0f} KB ({len(route_table)} airports)")

    # 3. save chunk files (res 5-6) as gzipped JSON
    # client uses DecompressionStream to decompress — keeps repo ~6x smaller
    import gzip
    import shutil
    total_chunk_bytes = 0
    total_raw_bytes = 0
    for res, chunks in chunk_data.items():
        chunk_dir = origin_dir / f"r{res}"
        if chunk_dir.exists():
            shutil.rmtree(chunk_dir)
        chunk_dir.mkdir(exist_ok=True)
        total_cells = 0
        for parent, cells in chunks.items():
            chunk_path = chunk_dir / f"{parent}.json.gz"
            raw = json.dumps(cells).encode('utf-8')
            total_raw_bytes += len(raw)
            with gzip.open(chunk_path, 'wb', compresslevel=9) as f:
                f.write(raw)
            total_chunk_bytes += chunk_path.stat().st_size
            total_cells += len(cells)
        raw_mb = total_raw_bytes / 1024 / 1024
        gz_mb = total_chunk_bytes / 1024 / 1024
        print(f"  r{res}: {len(chunks)} chunks, {total_cells:,} cells, {raw_mb:.1f} MB raw → {gz_mb:.1f} MB gzipped")

    total_mb = (base_path.stat().st_size + routes_path.stat().st_size + total_chunk_bytes) / 1024 / 1024
    print(f"\ntotal output: {total_mb:.1f} MB")
    return base_path


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Pre-compute isochrone data (dijkstra)")
    parser.add_argument("origin", nargs="?", default="bristol",
                        help="Origin city to compute (default: bristol)")
    parser.add_argument("--all", action="store_true",
                        help="Compute all configured origins")
    parser.add_argument("--base-only", action="store_true",
                        help="Only compute base resolutions (1-4), skip chunks")
    args = parser.parse_args()

    print("loading data...")
    airports = load_airports()
    routes = load_routes()
    print(f"  {len(airports):,} airports, {sum(len(v) for v in routes.values()):,} routes")

    # allow skipping chunked resolutions for quick iteration
    if args.base_only:
        global CHUNKED_RESOLUTIONS
        CHUNKED_RESOLUTIONS = []
        print("  (base-only mode: skipping res 5-6)")

    origins_to_compute = list(DJ_ORIGINS.keys()) if args.all else [args.origin]

    for origin in origins_to_compute:
        base_data, route_table, chunk_data = precompute_origin(origin, airports, routes)
        if base_data:
            save_result(origin, base_data, route_table, chunk_data)

    print("\ndone!")


if __name__ == "__main__":
    main()
