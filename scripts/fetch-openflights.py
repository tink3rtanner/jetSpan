#!/usr/bin/env python3
"""
fetch-openflights.py - download OpenFlights route data

note: this data is STALE (~2014) - use for sanity checks only, NOT as primary source

outputs:
  - raw/openflights-routes.dat (raw download)
  - raw/openflights-routes.json (parsed: {airport: [destinations]})

sanity checks:
  - 3000+ source airports
  - 60000+ route pairs
  - LHR has 100+ destinations
"""

import json
import os
import urllib.request
from collections import defaultdict
from pathlib import Path

# paths relative to repo root
REPO_ROOT = Path(__file__).parent.parent
RAW_DAT = REPO_ROOT / "raw" / "openflights-routes.dat"
OUTPUT_JSON = REPO_ROOT / "raw" / "openflights-routes.json"

# openflights routes url (warning: data is old, ~2014)
OPENFLIGHTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"

# sanity check constants
MIN_AIRPORTS = 3000
MIN_ROUTES = 30000  # data is ~2014, fewer routes than expected
MIN_LHR_DESTINATIONS = 100


def download_routes():
    """download raw routes.dat from openflights"""
    print(f"downloading from {OPENFLIGHTS_URL}...")
    RAW_DAT.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(OPENFLIGHTS_URL, RAW_DAT)

    with open(RAW_DAT) as f:
        line_count = sum(1 for _ in f)
    print(f"downloaded {line_count} lines to {RAW_DAT}")
    return line_count


def parse_routes():
    """
    parse routes.dat format:
    airline,airline_id,src,src_id,dst,dst_id,codeshare,stops,equipment

    we only care about src and dst (columns 2 and 4, 0-indexed)
    """
    routes = defaultdict(set)  # use set to dedupe
    invalid = 0

    with open(RAW_DAT, encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 5:
                invalid += 1
                continue

            src = parts[2].strip()
            dst = parts[4].strip()

            # validate IATA codes (3 uppercase letters)
            if len(src) != 3 or len(dst) != 3:
                invalid += 1
                continue
            if not src.isalpha() or not dst.isalpha():
                invalid += 1
                continue

            routes[src].add(dst)

    # convert sets to sorted lists
    routes_dict = {k: sorted(v) for k, v in routes.items()}

    total_pairs = sum(len(v) for v in routes_dict.values())
    print(f"parsed: {len(routes_dict)} airports, {total_pairs} route pairs")
    print(f"skipped: {invalid} invalid lines")
    return routes_dict


def save_routes(routes):
    """save parsed routes to json"""
    with open(OUTPUT_JSON, "w") as f:
        json.dump(routes, f, separators=(",", ":"))

    size_kb = OUTPUT_JSON.stat().st_size / 1024
    print(f"saved to {OUTPUT_JSON} ({size_kb:.1f} KB)")


def run_sanity_checks(routes):
    """verify data quality"""
    print("\n=== SANITY CHECKS ===")
    errors = []

    total_pairs = sum(len(v) for v in routes.values())

    # check airport count
    if len(routes) < MIN_AIRPORTS:
        errors.append(f"only {len(routes)} airports (expected {MIN_AIRPORTS}+)")
    else:
        print(f"[ok] {len(routes)} source airports")

    # check route count
    if total_pairs < MIN_ROUTES:
        errors.append(f"only {total_pairs} route pairs (expected {MIN_ROUTES}+)")
    else:
        print(f"[ok] {total_pairs} route pairs")

    # check LHR has lots of destinations
    lhr_dests = len(routes.get("LHR", []))
    if lhr_dests < MIN_LHR_DESTINATIONS:
        errors.append(f"LHR only has {lhr_dests} destinations (expected {MIN_LHR_DESTINATIONS}+)")
    else:
        print(f"[ok] LHR has {lhr_dests} destinations")

    # spot check some expected routes
    expected_routes = [
        ("LHR", "JFK"),
        ("LHR", "CDG"),
        ("JFK", "LAX"),
        ("NRT", "SIN"),
    ]
    for src, dst in expected_routes:
        if dst not in routes.get(src, []):
            errors.append(f"expected route {src}->{dst} not found")

    print(f"[ok] expected routes present")

    # show top airports by connectivity
    top_airports = sorted(routes.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    print(f"\ntop 10 airports by destinations:")
    for code, dests in top_airports:
        print(f"  {code}: {len(dests)}")

    # summary
    if errors:
        print(f"\nFAILED: {len(errors)} errors")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("\nALL CHECKS PASSED")
        print("\nWARNING: this data is ~2014, use for sanity checks only!")
        return True


def main():
    print("=== FETCH OPENFLIGHTS ROUTES ===\n")

    download_routes()
    routes = parse_routes()
    save_routes(routes)

    success = run_sanity_checks(routes)
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
