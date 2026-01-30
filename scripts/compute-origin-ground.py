#!/usr/bin/env python3
"""
compute-origin-ground.py - compute driving times from origin city center to surrounding H3 cells

queries OSRM table API from the actual origin coordinates (e.g. bristol city center)
to all res-6 cells within MAX_DRIVE_KM. this is used by precompute for the drive-only
check — "is driving from home faster than flying?"

outputs: data/ground/origin-{name}.json
format:  {h3_cell: minutes, ...}

usage:
  python scripts/compute-origin-ground.py                    # default: bristol
  python scripts/compute-origin-ground.py --origin london
  python scripts/compute-origin-ground.py --origin bristol --backend demo
  OSRM_BACKEND=local python scripts/compute-origin-ground.py  # local OSRM instance
"""

import json
import math
import os
import sys
import time
import subprocess
from pathlib import Path

try:
    import h3
except ImportError:
    print("ERROR: h3 not installed. run: pip install h3")
    sys.exit(1)

# add scripts dir so we can import ORIGINS
sys.path.insert(0, str(Path(__file__).parent))
from dijkstra_router import ORIGINS

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "ground"

# config
OSRM_BACKEND = os.environ.get("OSRM_BACKEND", "demo")
OSRM_LOCAL_PORT = int(os.environ.get("OSRM_LOCAL_PORT", "5000"))

# params
H3_RESOLUTION = 6       # ~36 km² cells (matches airport ground data)
MAX_DRIVE_KM = 400       # max radius from origin (covers drive-only zone)
MAX_DRIVE_HOURS = 8      # cap — anything over 8h drive, flying wins anyway
BATCH_SIZE = 100         # OSRM table API limit per request
DEMO_SLEEP = 1.5         # rate limit for demo server
LOCAL_SLEEP = 0.05


def haversine(lng1, lat1, lng2, lat2):
    """distance in km"""
    lng1, lat1, lng2, lat2 = map(math.radians, [lng1, lat1, lng2, lat2])
    dlng = lng2 - lng1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    return 2 * 6371 * math.asin(math.sqrt(a))


def get_osrm_url():
    if OSRM_BACKEND == "demo":
        return "https://router.project-osrm.org"
    else:
        return f"http://localhost:{OSRM_LOCAL_PORT}"


def query_osrm_table(origin_lng, origin_lat, dest_coords, max_retries=8):
    """query OSRM table API: one origin to many destinations.
    returns list of durations in minutes (None for unreachable).
    patient with the demo server — it queues requests and can be slow."""
    if not dest_coords:
        return []

    coords = f"{origin_lng},{origin_lat}"
    for lng, lat in dest_coords:
        coords += f";{lng},{lat}"

    url = f"{get_osrm_url()}/table/v1/driving/{coords}?sources=0"

    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "120", url],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                # curl timeout or network error — wait and retry
                wait = min(10 * (attempt + 1), 60)
                print(f"curl err (code {result.returncode}), wait {wait}s...", end=" ", flush=True)
                time.sleep(wait)
                continue

            if not result.stdout.strip():
                # empty response — server busy, back off
                wait = min(10 * (attempt + 1), 60)
                print(f"empty response, wait {wait}s...", end=" ", flush=True)
                time.sleep(wait)
                continue

            data = json.loads(result.stdout)

            if data.get("code") == "Ok":
                durations = data.get("durations", [[]])[0][1:]
                return [round(d / 60) if d is not None else None for d in durations]
            else:
                return [None] * len(dest_coords)

        except json.JSONDecodeError:
            wait = min(10 * (attempt + 1), 60)
            print(f"bad json, wait {wait}s...", end=" ", flush=True)
            time.sleep(wait)
        except Exception as e:
            wait = min(15 * (attempt + 1), 90)
            print(f"err: {e}, wait {wait}s...", end=" ", flush=True)
            time.sleep(wait)

    return [None] * len(dest_coords)


def get_cells_in_radius(origin_lng, origin_lat, max_km):
    """get all H3 res-6 cells within max_km of origin."""
    center = h3.latlng_to_cell(origin_lat, origin_lng, H3_RESOLUTION)

    # estimate grid_disk k from radius (~10km per ring at res 6)
    k = int(max_km / 10) + 2
    cells = list(h3.grid_disk(center, k))

    # filter to those actually within radius
    result = []
    for cell in cells:
        cell_lat, cell_lng = h3.cell_to_latlng(cell)
        dist = haversine(origin_lng, origin_lat, cell_lng, cell_lat)
        if dist <= max_km:
            result.append((cell, cell_lng, cell_lat, dist))

    return result


def compute_origin_ground(origin_key):
    """compute driving times from origin city center to all nearby cells."""
    origin = ORIGINS[origin_key]
    origin_lng, origin_lat = origin['coords']
    origin_name = origin['name']

    print(f"origin: {origin_name} ({origin_lng}, {origin_lat})")
    print(f"backend: {OSRM_BACKEND} ({get_osrm_url()})")
    print(f"radius: {MAX_DRIVE_KM}km, res: {H3_RESOLUTION}")
    print()

    # enumerate cells
    print("enumerating cells...")
    cells = get_cells_in_radius(origin_lng, origin_lat, MAX_DRIVE_KM)
    print(f"  {len(cells)} res-{H3_RESOLUTION} cells within {MAX_DRIVE_KM}km")
    print()

    # batch query OSRM
    results = {}
    total_batches = math.ceil(len(cells) / BATCH_SIZE)
    sleep_time = DEMO_SLEEP if OSRM_BACKEND == "demo" else LOCAL_SLEEP
    failed_batches = 0

    for i in range(0, len(cells), BATCH_SIZE):
        batch_num = i // BATCH_SIZE + 1
        batch = cells[i:i + BATCH_SIZE]
        dest_coords = [[lng, lat] for _, lng, lat, _ in batch]

        print(f"  batch {batch_num}/{total_batches} ({len(batch)} cells)...", end=" ", flush=True)
        times = query_osrm_table(origin_lng, origin_lat, dest_coords)

        got = 0
        for (cell, lng, lat, dist), time_min in zip(batch, times):
            if time_min is not None and time_min <= MAX_DRIVE_HOURS * 60:
                results[cell] = time_min
                got += 1
            # no fallback — if OSRM can't route it, it's water or unreachable

        if got == 0 and len(batch) > 0:
            failed_batches += 1
            print(f"FAILED (0/{len(batch)}) [{failed_batches} consecutive]")
        else:
            failed_batches = 0
            print(f"ok ({got}/{len(batch)} reachable)")

        time.sleep(sleep_time)

    print(f"\ndone: {len(results)} reachable cells out of {len(cells)} total")
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="compute origin ground times via OSRM")
    parser.add_argument('--origin', default='bristol', choices=list(ORIGINS.keys()))
    parser.add_argument('--backend', choices=['demo', 'local'], help='override OSRM_BACKEND env var')
    args = parser.parse_args()

    if args.backend:
        global OSRM_BACKEND
        OSRM_BACKEND = args.backend

    results = compute_origin_ground(args.origin)
    if results is None:
        print("aborted — no output written.")
        sys.exit(1)

    # save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outfile = OUTPUT_DIR / f"origin-{args.origin}.json"
    with open(outfile, "w") as f:
        json.dump(results, f)

    size_kb = outfile.stat().st_size / 1024
    print(f"saved: {outfile} ({size_kb:.1f} KB, {len(results)} cells)")


if __name__ == '__main__':
    main()
