#!/usr/bin/env python3
"""
osrm-crawler.py - long-running OSRM ground times crawler for raspberry pi

designed to run for days with:
- crash-safe checkpointing
- region-priority ordering (europe first for bristol)
- adaptive rate limiting
- verbose progress logging

usage:
  python scripts/osrm-crawler.py              # resume or start from scratch
  python scripts/osrm-crawler.py --region europe  # only process europe
  python scripts/osrm-crawler.py --status     # show progress without running
"""

import json
import math
import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# h3 import
try:
    import h3
except ImportError:
    print("ERROR: h3 not installed. run: pip install h3")
    sys.exit(1)

# paths
REPO_ROOT = Path(__file__).parent.parent
AIRPORTS_FILE = REPO_ROOT / "data" / "airports.json"
CHECKPOINT_FILE = REPO_ROOT / "raw" / "ground-checkpoint.json"
OUTPUT_DIR = REPO_ROOT / "data" / "ground"
LOG_FILE = REPO_ROOT / "raw" / "osrm-crawler.log"

# config
OSRM_URL = "https://router.project-osrm.org"
H3_RESOLUTION = 6       # ~10km cells
MAX_DRIVE_HOURS = 4     # max driving time to compute
MAX_DRIVE_KM = 200      # max distance from airport
FALLBACK_SPEED_KMH = 30 # for unreachable cells
BATCH_SIZE = 100        # osrm limit per request
REQUEST_DELAY = 0.1     # seconds between requests (server queues anyway, no point waiting)
CHECKPOINT_EVERY = 1    # checkpoint after every airport (safer for long runs)

# region ordering (bristol-focused: europe first, then nearby)
REGION_PRIORITY = ["europe", "north-america", "middle-east", "asia", "africa", "oceania", "south-america"]

# country -> region mapping
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
        "LB", "IQ", "IR", "SY", "YE", "PS",
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
    """distance in km"""
    R = 6371
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def log(msg):
    """log to stdout and file"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def query_osrm_table(origin_lng, origin_lat, dest_coords, retries=3):
    """
    query OSRM table API
    returns: list of durations in minutes (None for unreachable)
    """
    if not dest_coords:
        return []

    # build coords string
    coords = f"{origin_lng},{origin_lat}"
    for lng, lat in dest_coords:
        coords += f";{lng},{lat}"

    url = f"{OSRM_URL}/table/v1/driving/{coords}?sources=0"

    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "60", url],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise Exception(f"curl failed: {result.stderr}")

            data = json.loads(result.stdout)

            if data.get("code") == "Ok":
                durations = data.get("durations", [[]])[0][1:]
                return [round(d / 60) if d is not None else None for d in durations]
            else:
                # osrm error (no route, etc)
                return [None] * len(dest_coords)

        except json.JSONDecodeError:
            log(f"  json error, retry {attempt+1}/{retries}")
            time.sleep(5)

        except Exception as e:
            log(f"  error: {e}, retry {attempt+1}/{retries}")
            time.sleep(10 * (attempt + 1))

    return [None] * len(dest_coords)


def get_cells_around_airport(lng, lat):
    """get H3 cells within MAX_DRIVE_KM of airport"""
    center = h3.latlng_to_cell(lat, lng, H3_RESOLUTION)
    cell_size_km = 10
    k = int(MAX_DRIVE_KM / cell_size_km) + 2

    cells = list(h3.grid_disk(center, k))

    result = []
    for cell in cells:
        cell_lat, cell_lng = h3.cell_to_latlng(cell)
        dist = haversine(lng, lat, cell_lng, cell_lat)
        if dist <= MAX_DRIVE_KM:
            result.append((cell, cell_lng, cell_lat, dist))

    return result


def compute_airport_ground_times(airport_code, airport_lng, airport_lat):
    """compute ground times for one airport"""
    cells = get_cells_around_airport(airport_lng, airport_lat)
    if not cells:
        return {}

    results = {}
    total_batches = (len(cells) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(0, len(cells), BATCH_SIZE):
        batch = cells[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1

        dest_coords = [[lng, lat] for _, lng, lat, _ in batch]
        times = query_osrm_table(airport_lng, airport_lat, dest_coords)

        for (cell, lng, lat, dist), time_min in zip(batch, times):
            if time_min is not None and time_min <= MAX_DRIVE_HOURS * 60:
                results[cell] = time_min
            elif time_min is None:
                fallback = round(dist / FALLBACK_SPEED_KMH * 60)
                if fallback <= MAX_DRIVE_HOURS * 60:
                    results[cell] = fallback

        time.sleep(REQUEST_DELAY)

    return results


def load_checkpoint():
    """load or create checkpoint"""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE) as f:
                data = json.load(f)
                return data.get("ground_data", {}), set(data.get("completed", []))
        except json.JSONDecodeError:
            log("WARNING: corrupt checkpoint, starting fresh")

    # check if we have existing region files to import
    existing = {}
    for region_file in OUTPUT_DIR.glob("*.json"):
        if region_file.stem == "test":
            continue
        try:
            with open(region_file) as f:
                existing.update(json.load(f))
            log(f"  imported {region_file.stem}.json")
        except:
            pass

    if existing:
        log(f"  found {len(existing)} pre-existing airports in region files")
        return existing, set(existing.keys())

    return {}, set()


def save_checkpoint(ground_data, completed):
    """atomic checkpoint save"""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump({"ground_data": ground_data, "completed": list(completed)}, f)
    tmp.rename(CHECKPOINT_FILE)


def save_by_region(ground_data, airports):
    """save ground data split by region"""
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

        size_kb = path.stat().st_size / 1024
        total_cells = sum(len(c) for c in data.values())
        log(f"  {region}: {len(data)} airports, {total_cells} cells ({size_kb:.0f} KB)")


def show_status(airports, ground_data, completed):
    """show progress summary"""
    print("\n=== OSRM CRAWLER STATUS ===\n")

    # by region
    by_region = {}
    for code, apt in airports.items():
        region = get_region(apt.get("country", ""))
        if region not in by_region:
            by_region[region] = {"total": 0, "done": 0}
        by_region[region]["total"] += 1
        if code in completed:
            by_region[region]["done"] += 1

    print(f"{'region':<15} {'done':>6} / {'total':>6}  {'progress':>8}")
    print("-" * 45)

    total_done = 0
    total_airports = 0
    for region in REGION_PRIORITY + ["other"]:
        if region in by_region:
            r = by_region[region]
            pct = r["done"] / r["total"] * 100 if r["total"] > 0 else 0
            print(f"{region:<15} {r['done']:>6} / {r['total']:>6}  {pct:>7.1f}%")
            total_done += r["done"]
            total_airports += r["total"]

    print("-" * 45)
    pct = total_done / total_airports * 100 if total_airports > 0 else 0
    print(f"{'TOTAL':<15} {total_done:>6} / {total_airports:>6}  {pct:>7.1f}%")

    total_cells = sum(len(c) for c in ground_data.values())
    print(f"\ntotal cells computed: {total_cells:,}")

    # eta
    remaining = total_airports - total_done
    if remaining > 0:
        min_per_airport = 3  # rough estimate
        eta_hours = remaining * min_per_airport / 60
        print(f"estimated time remaining: ~{eta_hours:.0f} hours")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="OSRM ground times crawler")
    parser.add_argument("--region", help="only process this region")
    parser.add_argument("--status", action="store_true", help="show status only")
    args = parser.parse_args()

    # load data
    with open(AIRPORTS_FILE) as f:
        all_airports = json.load(f)

    airports = {k: v for k, v in all_airports.items() if v.get("type") == "large"}
    log(f"loaded {len(airports)} large airports")

    ground_data, completed = load_checkpoint()
    log(f"checkpoint: {len(completed)} airports done")

    if args.status:
        show_status(airports, ground_data, completed)
        return

    # build work queue in region priority order
    # within europe, UK airports first (bristol focus)
    work_queue = []
    for region in REGION_PRIORITY + ["other"]:
        region_airports = [
            code for code, apt in airports.items()
            if get_region(apt.get("country", "")) == region and code not in completed
        ]
        if args.region and region != args.region:
            continue
        # sort UK airports first within europe
        if region == "europe":
            region_airports.sort(key=lambda c: (0 if airports[c].get("country") == "GB" else 1, c))
        work_queue.extend(region_airports)

    if not work_queue:
        log("nothing to do!")
        show_status(airports, ground_data, completed)
        return

    log(f"work queue: {len(work_queue)} airports remaining")
    log(f"starting crawl (Ctrl+C to pause, will resume from checkpoint)")
    print()

    start_time = time.time()
    processed = 0

    try:
        for i, code in enumerate(work_queue):
            apt = airports[code]
            region = get_region(apt.get("country", ""))

            # progress
            elapsed = time.time() - start_time
            if processed > 0:
                rate = processed / elapsed * 3600  # airports per hour
                remaining = len(work_queue) - i
                eta_hours = remaining / rate if rate > 0 else 0
                eta_str = f"ETA: {eta_hours:.1f}h"
            else:
                eta_str = "ETA: calculating..."

            log(f"[{len(completed)+1}/{len(airports)}] {code} ({apt['name'][:30]}) [{region}] ", )

            cells = compute_airport_ground_times(code, apt["lng"], apt["lat"])

            if cells:
                ground_data[code] = cells
                log(f"  -> {len(cells)} cells")
            else:
                log(f"  -> no cells (island?)")

            completed.add(code)
            processed += 1

            # checkpoint
            if processed % CHECKPOINT_EVERY == 0:
                save_checkpoint(ground_data, completed)
                log(f"  [checkpoint saved] {eta_str}")

    except KeyboardInterrupt:
        log("\ninterrupted by user")

    # final save
    log("saving final checkpoint and region files...")
    save_checkpoint(ground_data, completed)
    save_by_region(ground_data, airports)

    show_status(airports, ground_data, completed)


if __name__ == "__main__":
    main()
