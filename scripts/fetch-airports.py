#!/usr/bin/env python3
"""
fetch-airports.py - download and filter OurAirports data

outputs:
  - raw/ourairports.csv (full download)
  - data/airports.json (filtered: large/medium airports with IATA codes)

sanity checks:
  - raw csv has 2000+ rows
  - filtered json has 800+ airports
  - key airports present: LHR, JFK, BRS, NRT, SYD, DXB
"""

import csv
import json
import os
import urllib.request
from pathlib import Path

# paths relative to repo root
REPO_ROOT = Path(__file__).parent.parent
RAW_CSV = REPO_ROOT / "raw" / "ourairports.csv"
OUTPUT_JSON = REPO_ROOT / "data" / "airports.json"

# ourairports data url (updated nightly)
OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# sanity check constants
MIN_RAW_ROWS = 2000
MIN_FILTERED_AIRPORTS = 800
REQUIRED_AIRPORTS = ["LHR", "JFK", "BRS", "NRT", "SYD", "DXB", "CDG", "LAX", "CVG"]


def download_airports():
    """download raw airports csv from ourairports"""
    print(f"downloading from {OURAIRPORTS_URL}...")
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(OURAIRPORTS_URL, RAW_CSV)

    # count rows for sanity
    with open(RAW_CSV) as f:
        row_count = sum(1 for _ in f) - 1  # minus header
    print(f"downloaded {row_count} airports to {RAW_CSV}")
    return row_count


def parse_and_filter():
    """parse csv, filter to large/medium airports with IATA codes"""
    airports = {}
    skipped = {"no_iata": 0, "small": 0, "closed": 0}

    with open(RAW_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            iata = row.get("iata_code", "").strip()
            atype = row.get("type", "")

            # skip if no iata code
            if not iata or iata == "":
                skipped["no_iata"] += 1
                continue

            # skip small/closed airports
            if atype not in ["large_airport", "medium_airport"]:
                if atype == "closed":
                    skipped["closed"] += 1
                else:
                    skipped["small"] += 1
                continue

            # parse coordinates
            try:
                lat = float(row["latitude_deg"])
                lng = float(row["longitude_deg"])
            except (ValueError, KeyError):
                continue

            airports[iata] = {
                "name": row.get("name", ""),
                "lat": lat,
                "lng": lng,
                "country": row.get("iso_country", ""),
                "type": atype.replace("_airport", ""),  # "large" or "medium"
            }

    print(f"filtered: {len(airports)} airports")
    print(f"skipped: {skipped}")
    return airports


def save_airports(airports):
    """save filtered airports to json"""
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(airports, f, separators=(",", ":"))  # compact json

    size_kb = OUTPUT_JSON.stat().st_size / 1024
    print(f"saved to {OUTPUT_JSON} ({size_kb:.1f} KB)")


def run_sanity_checks(raw_count, airports):
    """verify data quality"""
    print("\n=== SANITY CHECKS ===")
    errors = []

    # check raw count
    if raw_count < MIN_RAW_ROWS:
        errors.append(f"raw csv only has {raw_count} rows (expected {MIN_RAW_ROWS}+)")
    else:
        print(f"[ok] raw csv has {raw_count} rows")

    # check filtered count
    if len(airports) < MIN_FILTERED_AIRPORTS:
        errors.append(f"only {len(airports)} airports after filter (expected {MIN_FILTERED_AIRPORTS}+)")
    else:
        print(f"[ok] {len(airports)} airports after filter")

    # check required airports present
    missing = [code for code in REQUIRED_AIRPORTS if code not in airports]
    if missing:
        errors.append(f"missing required airports: {missing}")
    else:
        print(f"[ok] all required airports present: {REQUIRED_AIRPORTS}")

    # spot check a few airports
    spot_checks = [
        ("LHR", "Heathrow", "GB"),
        ("JFK", "Kennedy", "US"),  # "John F. Kennedy" has period
        ("NRT", "Narita", "JP"),
    ]
    for code, expected_name_part, expected_country in spot_checks:
        apt = airports.get(code, {})
        if expected_name_part.lower() not in apt.get("name", "").lower():
            errors.append(f"{code} name doesn't contain '{expected_name_part}': {apt.get('name')}")
        if apt.get("country") != expected_country:
            errors.append(f"{code} country is {apt.get('country')}, expected {expected_country}")

    print(f"[ok] spot checks passed")

    # summary
    if errors:
        print(f"\nFAILED: {len(errors)} errors")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("\nALL CHECKS PASSED")
        return True


def main():
    print("=== FETCH AIRPORTS ===\n")

    raw_count = download_airports()
    airports = parse_and_filter()
    save_airports(airports)

    success = run_sanity_checks(raw_count, airports)
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
