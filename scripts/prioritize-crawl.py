#!/usr/bin/env python3
"""generate a prioritized crawl order for medium airports.

outputs a text file (one airport code per line) sorted by:
1. region priority (UK first, then europe, then outward)
2. within each region: cell count (how many cells route through this airport)

usage:
    python scripts/prioritize-crawl.py
    python scripts/prioritize-crawl.py --output raw/crawl-priority.txt
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
AIRPORTS_FILE = REPO_ROOT / "data" / "airports.json"
ROUTES_FILE = REPO_ROOT / "data" / "routes.json"
OSRM_DIR = REPO_ROOT / "data" / "ground"
# base isochrone used to count cells per destination airport
ISOCHRONE_FILE = REPO_ROOT / "data" / "isochrones" / "bristol.json"

# region priority: UK first, then expanding outward from bristol
REGION_PRIORITY = [
    "GB",       # uk — stress test for local routing
    "europe",   # nearby continent
    "north-america",
    "middle-east",
    "asia",
    "africa",
    "oceania",
    "south-america",
    "other",
]

# country -> region (matches osrm-crawler.py)
REGION_MAP = {
    "US": "north-america", "CA": "north-america", "MX": "north-america",
    "GB": "europe", "DE": "europe", "FR": "europe", "ES": "europe", "IT": "europe",
    "NL": "europe", "BE": "europe", "AT": "europe", "CH": "europe", "PT": "europe",
    "IE": "europe", "SE": "europe", "NO": "europe", "DK": "europe", "FI": "europe",
    "PL": "europe", "CZ": "europe", "GR": "europe", "RO": "europe", "HU": "europe",
    "HR": "europe", "BG": "europe", "SK": "europe", "SI": "europe", "LT": "europe",
    "LV": "europe", "EE": "europe", "IS": "europe", "LU": "europe", "MT": "europe",
    "CY": "europe", "RS": "europe", "BA": "europe", "ME": "europe", "MK": "europe",
    "AL": "europe", "XK": "europe", "MD": "europe", "UA": "europe", "BY": "europe",
    "RU": "europe",
    "AE": "middle-east", "SA": "middle-east", "QA": "middle-east",
    "OM": "middle-east", "BH": "middle-east", "KW": "middle-east",
    "IL": "middle-east", "JO": "middle-east", "LB": "middle-east",
    "IQ": "middle-east", "IR": "middle-east", "TR": "middle-east",
    "CN": "asia", "JP": "asia", "KR": "asia", "IN": "asia", "TH": "asia",
    "SG": "asia", "MY": "asia", "ID": "asia", "PH": "asia", "VN": "asia",
    "TW": "asia", "HK": "asia", "PK": "asia", "BD": "asia", "LK": "asia",
    "NP": "asia", "MM": "asia", "KH": "asia", "LA": "asia", "MN": "asia",
    "KZ": "asia", "UZ": "asia", "TM": "asia", "KG": "asia", "TJ": "asia",
    "AU": "oceania", "NZ": "oceania", "FJ": "oceania", "PG": "oceania",
    "NC": "oceania", "PF": "oceania",
    "BR": "south-america", "AR": "south-america", "CL": "south-america",
    "CO": "south-america", "PE": "south-america", "VE": "south-america",
    "EC": "south-america", "BO": "south-america", "PY": "south-america",
    "UY": "south-america", "GY": "south-america", "SR": "south-america",
}


def get_region(country):
    """map country code to region. GB gets its own priority tier."""
    if country == "GB":
        return "GB"
    return REGION_MAP.get(country, "other")


def load_crawled_airports():
    """return set of airport codes that already have OSRM data."""
    crawled = set()
    for f in OSRM_DIR.glob("*.json"):
        if f.name.startswith("origin-") or f.name == "test.json":
            continue
        data = json.load(open(f))
        crawled.update(data.keys())
    return crawled


def count_cells_per_airport(isochrone_path):
    """count how many res-4 cells route through each destination airport."""
    counts = {}
    with open(isochrone_path) as f:
        iso = json.load(f)
    # use res 4 as representative (largest base resolution)
    res4 = iso.get("resolutions", {}).get("4", {})
    for cell, data in res4.items():
        apt = data.get("a")
        if apt:
            counts[apt] = counts.get(apt, 0) + 1
    return counts


def main():
    import argparse
    parser = argparse.ArgumentParser(description="prioritize OSRM crawl order")
    parser.add_argument("--output", "-o", default="raw/crawl-priority.txt",
                        help="output file (default: raw/crawl-priority.txt)")
    args = parser.parse_args()

    # load data
    with open(AIRPORTS_FILE) as f:
        airports = json.load(f)

    crawled = load_crawled_airports()
    cell_counts = count_cells_per_airport(ISOCHRONE_FILE)

    # find all reachable airports (from routes)
    with open(ROUTES_FILE) as f:
        routes = json.load(f)
    reachable = set()
    for src, dests in routes.items():
        reachable.add(src)
        for d in dests:
            reachable.add(d if isinstance(d, str) else d[0])

    # filter to uncrawled airports that exist in our airport data
    uncrawled = []
    for code in reachable:
        if code in crawled:
            continue
        apt = airports.get(code)
        if not apt:
            continue
        country = apt.get("country", "")
        region = get_region(country)
        cells = cell_counts.get(code, 0)
        uncrawled.append({
            "code": code,
            "name": apt.get("name", ""),
            "country": country,
            "region": region,
            "cells": cells,
            "type": apt.get("type", "unknown"),
        })

    # sort: region priority first, then cell count descending within region
    region_order = {r: i for i, r in enumerate(REGION_PRIORITY)}
    uncrawled.sort(key=lambda a: (
        region_order.get(a["region"], 99),
        -a["cells"],  # highest cell count first within region
    ))

    # output
    output_path = REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        for apt in uncrawled:
            f.write(f"{apt['code']}\n")

    # summary
    print(f"prioritized {len(uncrawled)} uncrawled airports")
    print(f"output: {output_path}")
    print()

    # show top airports per region
    for region in REGION_PRIORITY:
        region_apts = [a for a in uncrawled if a["region"] == region]
        if not region_apts:
            continue
        total_cells = sum(a["cells"] for a in region_apts)
        print(f"  {region}: {len(region_apts)} airports, {total_cells} cells")
        # show top 5
        for apt in region_apts[:5]:
            print(f"    {apt['code']:4s} {apt['name'][:40]:40s} {apt['country']:3s} {apt['cells']:>5d} cells")
        if len(region_apts) > 5:
            print(f"    ... and {len(region_apts) - 5} more")


if __name__ == "__main__":
    main()
