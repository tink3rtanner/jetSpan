#!/usr/bin/env python3
"""
compute-ground-times.py - compute driving times from airports to surrounding H3 cells

uses OSRM table API for efficient batch queries.

backends:
  - demo: router.project-osrm.org (free, rate-limited, testing only)
  - local: localhost:5000 (requires local OSRM setup)

env vars:
  OSRM_BACKEND: "demo" or "local" (default: demo)
  OSRM_LOCAL_PORT: port for local backend (default: 5000)

outputs:
  - raw/ground-checkpoint.json (progress)
  - data/ground/{region}.json (final data by region)
"""

import json
import math
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

# optional h3 import - install with: pip install h3
try:
    import h3
    HAS_H3 = True
except ImportError:
    HAS_H3 = False
    print("WARNING: h3 not installed. run: pip install h3")

REPO_ROOT = Path(__file__).parent.parent
AIRPORTS_FILE = REPO_ROOT / "data" / "airports.json"
CHECKPOINT_FILE = REPO_ROOT / "raw" / "ground-checkpoint.json"
OUTPUT_DIR = REPO_ROOT / "data" / "ground"

# config
OSRM_BACKEND = os.environ.get("OSRM_BACKEND", "demo")
OSRM_LOCAL_PORT = int(os.environ.get("OSRM_LOCAL_PORT", "5000"))

# computation params
H3_RESOLUTION = 6       # ~10km cells
MAX_DRIVE_HOURS = 4     # max driving time to compute
MAX_DRIVE_KM = 200      # max distance from airport (200km = ~2-3hr drive)
FALLBACK_SPEED_KMH = 30 # for unreachable cells (water, etc)

# rate limiting
DEMO_SLEEP = 1.5        # seconds between requests on demo server (conservative)
LOCAL_SLEEP = 0.05      # seconds between requests on local
CHECKPOINT_EVERY = 20   # airports

# region mapping
REGION_MAP = {
    "europe": [
        "GB", "FR", "DE", "ES", "IT", "NL", "BE", "AT", "CH", "PT", "IE", "NO", "SE", "DK", "FI",
        "PL", "CZ", "HU", "GR", "RO", "BG", "HR", "SK", "SI", "LT", "LV", "EE", "CY", "MT", "LU",
        "IS", "RS", "UA", "BY", "MD", "AL", "MK", "BA", "ME", "XK",
    ],
    "north-america": [
        "US", "CA", "MX", "GT", "BZ", "HN", "SV", "NI", "CR", "PA",
        "CU", "JM", "HT", "DO", "PR", "BS", "BB", "TT", "VI", "AG", "LC", "GD", "VC", "KY",
    ],
    "asia": [
        "JP", "CN", "KR", "IN", "TH", "SG", "MY", "ID", "PH", "VN", "HK", "TW", "MO",
        "MM", "KH", "LA", "BD", "LK", "NP", "PK", "MN", "KZ", "UZ", "KG", "TJ", "AF",
    ],
    "middle-east": [
        "AE", "QA", "SA", "IL", "TR", "EG", "JO", "KW", "BH", "OM",
        "LB", "IQ", "IR", "SY", "YE", "PS", "CY",
    ],
    "oceania": ["AU", "NZ", "FJ", "PG", "NC", "PF", "GU", "WS", "TO", "VU", "SB"],
    "south-america": ["BR", "AR", "CL", "CO", "PE", "EC", "VE", "BO", "PY", "UY", "GY", "SR", "GF"],
    "africa": [
        "ZA", "KE", "NG", "EG", "MA", "ET", "GH", "TZ", "UG", "RW", "SN", "CI", "CM",
        "AO", "MZ", "ZW", "BW", "NA", "MU", "TN", "DZ", "LY", "SD", "MW", "ZM", "MG",
    ],
}


def get_region(country_code):
    """map country to region"""
    for region, countries in REGION_MAP.items():
        if country_code in countries:
            return region
    return "other"


def haversine(lng1, lat1, lng2, lat2):
    """distance in km between two points"""
    R = 6371
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_osrm_url():
    """get OSRM base URL based on backend"""
    if OSRM_BACKEND == "demo":
        return "https://router.project-osrm.org"
    else:
        return f"http://localhost:{OSRM_LOCAL_PORT}"


def query_osrm_table(origin_lng, origin_lat, dest_coords, max_retries=3):
    """
    query OSRM table API: one origin to many destinations

    dest_coords: list of [lng, lat] pairs
    returns: list of durations in minutes (None for unreachable)
    """
    if not dest_coords:
        return []

    # build coordinate string: origin first, then destinations
    coords = f"{origin_lng},{origin_lat}"
    for lng, lat in dest_coords:
        coords += f";{lng},{lat}"

    url = f"{get_osrm_url()}/table/v1/driving/{coords}?sources=0"

    for attempt in range(max_retries):
        try:
            # use curl to avoid python SSL issues with demo server
            import subprocess
            result = subprocess.run(
                ["curl", "-s", "--max-time", "30", url],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise Exception(f"curl failed: {result.stderr}")

            data = json.loads(result.stdout)

            if data.get("code") == "Ok":
                # durations[0] is from source 0 to all destinations
                # first value is 0 (source to itself), skip it
                durations = data.get("durations", [[]])[0][1:]
                # convert seconds to minutes, None for unreachable
                return [round(d / 60) if d is not None else None for d in durations]
            else:
                return [None] * len(dest_coords)

        except json.JSONDecodeError:
            print(f"    invalid json response, retrying...")
            time.sleep(5)

        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                wait = (attempt + 1) * 30
                print(f"    rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    error: {e}, retrying...")
                time.sleep(5)

    return [None] * len(dest_coords)


def get_cells_around_airport(lng, lat, max_km):
    """get H3 cells within max_km of airport"""
    if not HAS_H3:
        return []

    center = h3.latlng_to_cell(lat, lng, H3_RESOLUTION)

    # estimate k rings needed (res 6 cells are ~10km edge)
    cell_size_km = 10
    k = int(max_km / cell_size_km) + 2

    # get all cells in disk
    cells = list(h3.grid_disk(center, k))

    # filter to those within max_km
    result = []
    for cell in cells:
        cell_lat, cell_lng = h3.cell_to_latlng(cell)
        dist = haversine(lng, lat, cell_lng, cell_lat)
        if dist <= max_km:
            result.append((cell, cell_lng, cell_lat, dist))

    return result


def compute_airport_ground_times(airport_code, airport_lng, airport_lat):
    """compute ground times from one airport to surrounding cells"""
    cells = get_cells_around_airport(airport_lng, airport_lat, MAX_DRIVE_KM)
    if not cells:
        return {}

    results = {}
    batch_size = 100  # OSRM can handle ~100 destinations per request

    for i in range(0, len(cells), batch_size):
        batch = cells[i:i + batch_size]
        dest_coords = [[lng, lat] for _, lng, lat, _ in batch]

        times = query_osrm_table(airport_lng, airport_lat, dest_coords)

        for (cell, lng, lat, dist), time_min in zip(batch, times):
            if time_min is not None and time_min <= MAX_DRIVE_HOURS * 60:
                results[cell] = time_min
            elif time_min is None:
                # fallback for unreachable (water, etc): straight line at slow speed
                fallback = round(dist / FALLBACK_SPEED_KMH * 60)
                if fallback <= MAX_DRIVE_HOURS * 60:
                    results[cell] = fallback

        # rate limiting
        sleep_time = DEMO_SLEEP if OSRM_BACKEND == "demo" else LOCAL_SLEEP
        time.sleep(sleep_time)

    return results


def load_checkpoint():
    """load checkpoint if exists"""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"data": {}, "completed": []}


def save_checkpoint(data, completed):
    """save checkpoint"""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"data": data, "completed": completed}, f)


def save_by_region(ground_data, airports):
    """split ground data by region and save"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    by_region = {}
    for code, cells in ground_data.items():
        country = airports.get(code, {}).get("country", "")
        region = get_region(country)
        if region not in by_region:
            by_region[region] = {}
        by_region[region][code] = cells

    for region, data in by_region.items():
        path = OUTPUT_DIR / f"{region}.json"
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))

        size_mb = path.stat().st_size / 1024 / 1024
        total_cells = sum(len(c) for c in data.values())
        print(f"  {region}: {len(data)} airports, {total_cells} cells ({size_mb:.2f} MB)")


def main():
    print("=== COMPUTE GROUND TIMES ===\n")

    if not HAS_H3:
        print("ERROR: h3 library required. run: pip install h3")
        return 1

    print(f"backend: {OSRM_BACKEND}")
    print(f"resolution: H3 res {H3_RESOLUTION}")
    print(f"max distance: {MAX_DRIVE_KM} km")
    print(f"max drive time: {MAX_DRIVE_HOURS} hours\n")

    # load airports - only process large airports to save API calls
    with open(AIRPORTS_FILE) as f:
        all_airports = json.load(f)

    airports = {k: v for k, v in all_airports.items() if v.get("type") == "large"}
    print(f"processing {len(airports)} large airports\n")

    # load checkpoint
    checkpoint = load_checkpoint()
    ground_data = checkpoint["data"]
    completed = set(checkpoint["completed"])
    print(f"checkpoint: {len(completed)} already done\n")

    # process airports
    to_process = [code for code in airports.keys() if code not in completed]
    total = len(to_process) + len(completed)
    start_time = time.time()
    processed_this_run = 0

    for i, code in enumerate(to_process):
        apt = airports[code]
        progress = len(completed) + 1

        # estimate time remaining
        if processed_this_run > 0:
            elapsed = time.time() - start_time
            rate = processed_this_run / elapsed  # airports per second
            remaining = len(to_process) - processed_this_run
            eta_sec = remaining / rate if rate > 0 else 0
            eta_str = f"ETA: {eta_sec/3600:.1f}h" if eta_sec > 3600 else f"ETA: {eta_sec/60:.0f}m"
        else:
            eta_str = "ETA: calculating..."

        print(f"[{progress}/{total}] {code} ({apt['name'][:25]}...) ", end="", flush=True)

        cells = compute_airport_ground_times(code, apt["lng"], apt["lat"])

        if cells:
            ground_data[code] = cells
            print(f"{len(cells)} cells [{eta_str}]")
        else:
            print(f"no cells [{eta_str}]")

        completed.add(code)
        processed_this_run += 1

        # checkpoint
        if len(completed) % CHECKPOINT_EVERY == 0:
            print("  checkpointing...")
            save_checkpoint(ground_data, list(completed))

    # final save
    save_checkpoint(ground_data, list(completed))

    print(f"\nsaving by region:")
    save_by_region(ground_data, airports)

    # summary
    total_cells = sum(len(c) for c in ground_data.values())
    print(f"\ndone: {len(ground_data)} airports, {total_cells} cells total")


if __name__ == "__main__":
    exit(main() or 0)
