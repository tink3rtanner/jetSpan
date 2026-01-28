#!/usr/bin/env python3
"""
merge-routes.py - merge amadeus and openflights route data

amadeus test data has more routes overall but is missing some major routes.
openflights is stale (~2014) but has better coverage of established routes.

strategy: use both, deduped. best of both worlds.

outputs:
  - data/routes.json (merged routes)
  - data/routes-stats.json (merge statistics)
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
AMADEUS_FILE = REPO_ROOT / "raw" / "amadeus-checkpoint.json"  # use checkpoint since it has all data
OPENFLIGHTS_FILE = REPO_ROOT / "raw" / "openflights-routes.json"
OUTPUT_FILE = REPO_ROOT / "data" / "routes.json"
STATS_FILE = REPO_ROOT / "data" / "routes-stats.json"


def main():
    print("=== MERGE ROUTES ===\n")

    # load amadeus data (from checkpoint)
    with open(AMADEUS_FILE) as f:
        amadeus_data = json.load(f)
    amadeus_routes = amadeus_data["routes"]
    print(f"amadeus: {len(amadeus_routes)} airports, {sum(len(d) for d in amadeus_routes.values())} routes")

    # load openflights data
    with open(OPENFLIGHTS_FILE) as f:
        openflights_routes = json.load(f)
    print(f"openflights: {len(openflights_routes)} airports, {sum(len(d) for d in openflights_routes.values())} routes")

    # merge
    merged = {}
    stats = {
        "amadeus_only": 0,
        "openflights_only": 0,
        "both": 0,
    }

    all_airports = set(amadeus_routes.keys()) | set(openflights_routes.keys())

    for airport in all_airports:
        amadeus_dests = set(amadeus_routes.get(airport, []))
        openflights_dests = set(openflights_routes.get(airport, []))

        # union of both sources
        merged[airport] = sorted(amadeus_dests | openflights_dests)

        # track stats
        stats["amadeus_only"] += len(amadeus_dests - openflights_dests)
        stats["openflights_only"] += len(openflights_dests - amadeus_dests)
        stats["both"] += len(amadeus_dests & openflights_dests)

    total_routes = sum(len(d) for d in merged.values())
    airports_with_routes = sum(1 for d in merged.values() if d)

    print(f"\nmerged: {len(merged)} airports, {total_routes} routes")
    print(f"airports with routes: {airports_with_routes}")
    print(f"\noverlap stats:")
    print(f"  both sources: {stats['both']}")
    print(f"  amadeus only: {stats['amadeus_only']}")
    print(f"  openflights only: {stats['openflights_only']}")

    # verify critical routes exist
    critical = [
        ("LHR", "JFK"),
        ("LHR", "CDG"),
        ("JFK", "LAX"),
        ("SYD", "SIN"),
    ]
    print(f"\ncritical route check:")
    for src, dst in critical:
        exists = dst in merged.get(src, []) or src in merged.get(dst, [])
        status = "ok" if exists else "MISSING"
        print(f"  [{status}] {src}<->{dst}")

    # save
    with open(OUTPUT_FILE, "w") as f:
        json.dump(merged, f, separators=(",", ":"))

    stats["total_airports"] = len(merged)
    stats["total_routes"] = total_routes
    stats["airports_with_routes"] = airports_with_routes

    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"\nsaved to {OUTPUT_FILE} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
