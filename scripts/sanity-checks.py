#!/usr/bin/env python3
"""
sanity-checks.py - comprehensive validation of all jetspan data

runs checks based on what data exists:
  - airports.json: airport data validation
  - routes.json (amadeus): route network validation + flight time estimates
  - openflights-routes.json: comparison with amadeus
  - ground/*.json: ground transport data validation

usage:
  python scripts/sanity-checks.py           # run all available checks
  python scripts/sanity-checks.py airports  # run only airport checks
  python scripts/sanity-checks.py routes    # run only route checks
  python scripts/sanity-checks.py ground    # run only ground checks
"""

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = REPO_ROOT / "raw"


def haversine(coord1, coord2):
    """distance in km between two [lng, lat] points"""
    R = 6371
    lat1, lat2 = math.radians(coord1[1]), math.radians(coord2[1])
    dlat = math.radians(coord2[1] - coord1[1])
    dlng = math.radians(coord2[0] - coord1[0])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_flight_minutes(dist_km):
    """estimate flight time based on distance"""
    if dist_km < 500:
        return dist_km / 400 * 60 + 30  # regional
    if dist_km < 1500:
        return dist_km / 550 * 60 + 25  # short-haul
    if dist_km < 4000:
        return dist_km / 700 * 60 + 25  # medium-haul
    if dist_km < 8000:
        return dist_km / 800 * 60 + 25  # long-haul
    return dist_km / 850 * 60 + 30  # ultra-long


def load_json(path):
    """load json file, return None if doesn't exist"""
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


# ============================================================
# AIRPORT CHECKS
# ============================================================

def check_airports():
    """validate airports.json"""
    print("\n" + "=" * 50)
    print("AIRPORT CHECKS")
    print("=" * 50)

    airports = load_json(DATA_DIR / "airports.json")
    if airports is None:
        print("[skip] airports.json not found")
        return None

    errors = []

    # count check
    print(f"\nairports: {len(airports)}")
    if len(airports) < 800:
        errors.append(f"only {len(airports)} airports (expected 800+)")

    # required airports
    required = ["LHR", "JFK", "BRS", "NRT", "SYD", "DXB", "CDG", "LAX", "CVG", "GRU", "CPT"]
    missing = [code for code in required if code not in airports]
    if missing:
        errors.append(f"missing airports: {missing}")
    else:
        print(f"[ok] all {len(required)} required airports present")

    # coordinate sanity
    bad_coords = []
    for code, apt in airports.items():
        lat, lng = apt.get("lat", 0), apt.get("lng", 0)
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            bad_coords.append(code)
    if bad_coords:
        errors.append(f"bad coordinates: {bad_coords[:5]}...")
    else:
        print("[ok] all coordinates valid")

    # spot check distances
    spot_checks = [
        ("LHR", "CDG", 350, 50),   # london-paris ~340km
        ("JFK", "LAX", 3980, 100), # ny-la ~3980km
        ("LHR", "JFK", 5550, 100), # london-ny ~5550km
    ]
    for src, dst, expected_km, tolerance in spot_checks:
        if src in airports and dst in airports:
            src_coord = [airports[src]["lng"], airports[src]["lat"]]
            dst_coord = [airports[dst]["lng"], airports[dst]["lat"]]
            dist = haversine(src_coord, dst_coord)
            if abs(dist - expected_km) > tolerance:
                errors.append(f"{src}-{dst} distance {dist:.0f}km, expected ~{expected_km}km")
    print(f"[ok] distance spot checks passed")

    # type distribution
    large = sum(1 for a in airports.values() if a.get("type") == "large")
    medium = sum(1 for a in airports.values() if a.get("type") == "medium")
    print(f"\ntype distribution: {large} large, {medium} medium")

    # country distribution (top 10)
    countries = {}
    for apt in airports.values():
        c = apt.get("country", "??")
        countries[c] = countries.get(c, 0) + 1
    top_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)[:10]
    print(f"\ntop 10 countries:")
    for country, count in top_countries:
        print(f"  {country}: {count}")

    return errors


# ============================================================
# ROUTE CHECKS
# ============================================================

def check_routes():
    """validate routes.json (amadeus data)"""
    print("\n" + "=" * 50)
    print("ROUTE CHECKS")
    print("=" * 50)

    routes = load_json(DATA_DIR / "routes.json")
    if routes is None:
        print("[skip] routes.json not found (run crawl-amadeus.py first)")
        return None

    airports = load_json(DATA_DIR / "airports.json")
    errors = []

    total_routes = sum(len(dests) for dests in routes.values())
    print(f"\nroutes: {len(routes)} airports, {total_routes} route pairs")

    if total_routes < 40000:
        errors.append(f"only {total_routes} routes (expected 40000+)")

    # check major hubs have lots of routes
    major_hubs = [
        ("LHR", 150),
        ("JFK", 100),
        ("CDG", 150),
        ("DXB", 150),
        ("SIN", 100),
    ]
    for hub, min_dests in major_hubs:
        dests = len(routes.get(hub, []))
        if dests < min_dests:
            errors.append(f"{hub} only has {dests} destinations (expected {min_dests}+)")
        else:
            print(f"[ok] {hub}: {dests} destinations")

    # check expected routes exist
    expected = [
        ("LHR", "JFK"),
        ("LHR", "CDG"),
        ("JFK", "LAX"),
        ("SYD", "SIN"),
        ("DXB", "LHR"),
    ]
    for src, dst in expected:
        if dst not in routes.get(src, []) and src not in routes.get(dst, []):
            errors.append(f"expected route {src}<->{dst} not found")
    print(f"[ok] expected routes present")

    # flight time estimation checks
    if airports:
        print("\nflight time estimates:")
        time_checks = [
            ("LHR", "CDG", 75, 20),    # ~75min actual
            ("LHR", "JFK", 480, 60),   # ~8h actual
            ("JFK", "LAX", 330, 40),   # ~5.5h actual
            ("SIN", "SYD", 480, 60),   # ~8h actual
        ]
        for src, dst, expected_min, tolerance in time_checks:
            if src in airports and dst in airports:
                src_coord = [airports[src]["lng"], airports[src]["lat"]]
                dst_coord = [airports[dst]["lng"], airports[dst]["lat"]]
                dist = haversine(src_coord, dst_coord)
                est = estimate_flight_minutes(dist)
                diff = abs(est - expected_min)
                status = "ok" if diff <= tolerance else "WARN"
                print(f"  [{status}] {src}-{dst}: {dist:.0f}km, est {est:.0f}min (expected ~{expected_min})")
                if diff > tolerance:
                    errors.append(f"{src}-{dst} flight estimate off by {diff:.0f}min")

    return errors


# ============================================================
# OPENFLIGHTS COMPARISON
# ============================================================

def check_openflights_comparison():
    """compare amadeus routes vs openflights (sanity check)"""
    print("\n" + "=" * 50)
    print("OPENFLIGHTS COMPARISON")
    print("=" * 50)

    amadeus = load_json(DATA_DIR / "routes.json")
    openflights = load_json(RAW_DIR / "openflights-routes.json")

    if amadeus is None:
        print("[skip] routes.json not found")
        return None
    if openflights is None:
        print("[skip] openflights-routes.json not found")
        return None

    errors = []

    # compare coverage
    amadeus_pairs = set()
    for src, dests in amadeus.items():
        for dst in dests:
            amadeus_pairs.add((src, dst))

    openflights_pairs = set()
    for src, dests in openflights.items():
        for dst in dests:
            openflights_pairs.add((src, dst))

    both = amadeus_pairs & openflights_pairs
    amadeus_only = amadeus_pairs - openflights_pairs
    openflights_only = openflights_pairs - amadeus_pairs

    print(f"\nboth sources: {len(both)} routes")
    print(f"amadeus only: {len(amadeus_only)} routes")
    print(f"openflights only: {len(openflights_only)} routes (stale data)")

    # openflights-only routes are expected (stale data, discontinued routes)
    # but if amadeus is missing LOTS of routes openflights has, might be a problem
    overlap_pct = len(both) / len(openflights_pairs) * 100 if openflights_pairs else 0
    print(f"\noverlap: {overlap_pct:.1f}% of openflights routes in amadeus")

    if overlap_pct < 50:
        errors.append(f"only {overlap_pct:.1f}% overlap with openflights (expected 50%+)")

    # sample openflights-only routes (might be discontinued)
    if openflights_only:
        print(f"\nsample openflights-only routes (likely discontinued):")
        for src, dst in list(openflights_only)[:5]:
            print(f"  {src}->{dst}")

    return errors


# ============================================================
# GROUND DATA CHECKS
# ============================================================

def check_ground():
    """validate ground transport data"""
    print("\n" + "=" * 50)
    print("GROUND DATA CHECKS")
    print("=" * 50)

    ground_dir = DATA_DIR / "ground"
    if not ground_dir.exists():
        print("[skip] data/ground/ not found (run compute-ground-times.py first)")
        return None

    airports = load_json(DATA_DIR / "airports.json")
    errors = []

    # check each region file
    regions = ["europe", "north-america", "asia", "middle-east", "oceania", "south-america", "africa"]
    total_airports = 0
    total_cells = 0

    for region in regions:
        path = ground_dir / f"{region}.json"
        if not path.exists():
            print(f"[skip] {region}.json not found")
            continue

        data = load_json(path)
        airports_in_region = len(data)
        cells_in_region = sum(len(cells) for cells in data.values())
        size_mb = path.stat().st_size / 1024 / 1024

        print(f"[ok] {region}: {airports_in_region} airports, {cells_in_region} cells ({size_mb:.1f} MB)")

        total_airports += airports_in_region
        total_cells += cells_in_region

        # spot check: major airports should have lots of cells
        if region == "europe":
            for hub in ["LHR", "CDG", "FRA"]:
                if hub in data and len(data[hub]) < 500:
                    errors.append(f"{hub} only has {len(data[hub])} ground cells (expected 500+)")

    print(f"\ntotal: {total_airports} airports, {total_cells} cells")

    # only fail if we have SOME ground data but it's incomplete
    if total_airports > 0 and total_airports < 500:
        errors.append(f"only {total_airports} airports have ground data (expected 500+)")

    if total_airports == 0:
        return None  # skip, no ground data yet

    return errors


# ============================================================
# MAIN
# ============================================================

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    print("=" * 50)
    print("JETSPAN SANITY CHECKS")
    print("=" * 50)

    all_errors = []

    if mode in ["all", "airports"]:
        errs = check_airports()
        if errs:
            all_errors.extend(errs)

    if mode in ["all", "routes"]:
        errs = check_routes()
        if errs:
            all_errors.extend(errs)

        errs = check_openflights_comparison()
        if errs:
            all_errors.extend(errs)

    if mode in ["all", "ground"]:
        errs = check_ground()
        if errs:
            all_errors.extend(errs)

    # summary
    print("\n" + "=" * 50)
    if all_errors:
        print(f"FAILED: {len(all_errors)} errors")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    else:
        print("ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    exit(main())
