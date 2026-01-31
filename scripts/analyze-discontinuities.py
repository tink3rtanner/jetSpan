#!/usr/bin/env python3
"""
Analyze travel time discontinuities between adjacent H3 cells.

Finds neighboring cells with large time differences — indicates
OSRM boundary artifacts, routing bugs, or water filter issues.

Usage:
    python scripts/analyze-discontinuities.py              # res 4 (fast, ~5s)
    python scripts/analyze-discontinuities.py --res 6      # res 6 chunks (slow, loads all)
    python scripts/analyze-discontinuities.py --threshold 120  # custom threshold (minutes)
"""

import json
import gzip
import argparse
import math
from pathlib import Path
from collections import defaultdict

try:
    import h3
except ImportError:
    print("h3 not installed. run: pip install h3")
    exit(1)


def haversine_km(lat1, lon1, lat2, lon2):
    """great-circle distance in km"""
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def load_base_data(origin='bristol'):
    """load res 1-4 from base JSON."""
    path = Path(__file__).parent.parent / "data" / "isochrones" / f"{origin}.json"
    with open(path) as f:
        return json.load(f)


def load_r6_chunks(origin='bristol'):
    """load all res 6 chunks into flat dict. ~3000 files, takes a minute."""
    chunk_dir = Path(__file__).parent.parent / "data" / "isochrones" / origin / "r6"
    if not chunk_dir.exists():
        print(f"  no r6 chunks at {chunk_dir}")
        return {}
    cells = {}
    files = list(chunk_dir.glob("*.json.gz"))
    print(f"  loading {len(files)} r6 chunks...")
    for i, f in enumerate(files):
        if i % 500 == 0 and i > 0:
            print(f"  {i}/{len(files)} files, {len(cells):,} cells...")
        try:
            with gzip.open(f, 'rb') as gz:
                chunk = json.loads(gz.read())
            cells.update(chunk)
        except Exception as e:
            print(f"  warning: {f.name}: {e}")
    print(f"  loaded {len(cells):,} res 6 cells from {len(files)} chunks")
    return cells


def load_r5_chunks(origin='bristol'):
    """load all res 5 chunks into flat dict."""
    chunk_dir = Path(__file__).parent.parent / "data" / "isochrones" / origin / "r5"
    if not chunk_dir.exists():
        return {}
    cells = {}
    files = list(chunk_dir.glob("*.json.gz"))
    print(f"  loading {len(files)} r5 chunks...")
    for f in files:
        try:
            with gzip.open(f, 'rb') as gz:
                chunk = json.loads(gz.read())
            cells.update(chunk)
        except Exception:
            pass
    print(f"  loaded {len(cells):,} res 5 cells")
    return cells


def analyze_discontinuities(cells, threshold_min=120, res=4):
    """
    find adjacent cells with time differences exceeding threshold.
    returns list of (cell_a, cell_b, time_a, time_b, diff, details).
    """
    print(f"\nanalyzing {len(cells):,} cells at res {res}, threshold={threshold_min}m...")

    # build set for O(1) lookup
    cell_set = set(cells.keys())
    discontinuities = []
    checked = 0
    neighbor_hits = 0

    for cell_id, cell_data in cells.items():
        t_a = cell_data.get('t', 0)
        if t_a <= 0:
            continue

        # get immediate neighbors (ring distance 1)
        try:
            neighbors = h3.grid_ring(cell_id, 1)
        except Exception:
            continue

        checked += 1
        for nb in neighbors:
            if nb not in cell_set:
                continue
            if nb <= cell_id:
                continue  # avoid checking each pair twice

            neighbor_hits += 1
            nb_data = cells[nb]
            t_b = nb_data.get('t', 0)
            if t_b <= 0:
                continue

            diff = abs(t_a - t_b)
            if diff >= threshold_min:
                # classify the discontinuity
                a_osrm = bool(cell_data.get('g'))
                b_osrm = bool(nb_data.get('g'))
                a_drive = bool(cell_data.get('d'))
                b_drive = bool(nb_data.get('d'))
                a_apt = cell_data.get('a', 'drive' if a_drive else '?')
                b_apt = nb_data.get('a', 'drive' if b_drive else '?')

                # classify type
                if a_osrm != b_osrm and not a_drive and not b_drive:
                    dtype = 'OSRM_BOUNDARY'  # one side has OSRM, other doesn't
                elif a_apt != b_apt:
                    dtype = 'AIRPORT_SWITCH'  # different destination airports
                elif a_drive != b_drive:
                    dtype = 'DRIVE_FLIGHT'    # drive-only vs flight boundary
                else:
                    dtype = 'SAME_AIRPORT'    # same airport, different ground times

                # get coordinates for location context
                lat_a, lng_a = h3.cell_to_latlng(cell_id)
                lat_b, lng_b = h3.cell_to_latlng(nb)

                discontinuities.append({
                    'cell_a': cell_id,
                    'cell_b': nb,
                    'time_a': t_a,
                    'time_b': t_b,
                    'diff': diff,
                    'type': dtype,
                    'lat': (lat_a + lat_b) / 2,
                    'lng': (lng_a + lng_b) / 2,
                    'apt_a': a_apt,
                    'apt_b': b_apt,
                    'osrm_a': a_osrm,
                    'osrm_b': b_osrm,
                })

        if checked % 100000 == 0 and checked > 0:
            print(f"  checked {checked:,} cells, {len(discontinuities)} discontinuities so far...")

    print(f"  checked {checked:,} cells, {neighbor_hits:,} neighbor pairs")
    return discontinuities


def print_report(discs, top_n=30):
    """print summary report of discontinuities."""
    if not discs:
        print("\nno discontinuities found!")
        return

    # sort by diff descending
    discs.sort(key=lambda d: d['diff'], reverse=True)

    # count by type
    by_type = defaultdict(int)
    for d in discs:
        by_type[d['type']] += 1

    print(f"\n{'='*70}")
    print(f"DISCONTINUITY REPORT: {len(discs)} total")
    print(f"{'='*70}")
    print("\nby type:")
    for dtype, count in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {dtype:20s} {count:6d}")

    # histogram of diff magnitudes
    print("\nby magnitude:")
    buckets = [120, 180, 240, 360, 480, 720, 9999]
    labels = ['2-3h', '3-4h', '4-6h', '6-8h', '8-12h', '12h+']
    for i, (lo, hi) in enumerate(zip(buckets, buckets[1:])):
        count = sum(1 for d in discs if lo <= d['diff'] < hi)
        if count > 0:
            print(f"  {labels[i]:8s} {count:6d} {'█' * min(50, count // 10)}")

    print(f"\ntop {top_n} worst discontinuities:")
    print(f"{'diff':>6s}  {'type':>16s}  {'apt_a':>5s}→{'apt_b':<5s}  {'osrm':>8s}  {'location'}")
    print('-' * 70)
    for d in discs[:top_n]:
        osrm_str = f"{'O' if d['osrm_a'] else 'H'}→{'O' if d['osrm_b'] else 'H'}"
        loc = f"{d['lat']:.1f}, {d['lng']:.1f}"
        time_str = f"{d['time_a']}→{d['time_b']}"
        print(f"{d['diff']:5d}m  {d['type']:>16s}  {d['apt_a']:>5s}→{d['apt_b']:<5s}  {osrm_str:>8s}  {loc:>12s}  {time_str}")

    # geographic clusters of OSRM_BOUNDARY discontinuities
    osrm_discs = [d for d in discs if d['type'] == 'OSRM_BOUNDARY']
    if osrm_discs:
        print(f"\nOSRM boundary hotspots (clustered by 2° grid):")
        grid = defaultdict(list)
        for d in osrm_discs:
            key = (round(d['lat'] / 2) * 2, round(d['lng'] / 2) * 2)
            grid[key].append(d)
        for (lat, lng), cluster in sorted(grid.items(), key=lambda x: -len(x[1]))[:10]:
            avg_diff = sum(d['diff'] for d in cluster) / len(cluster)
            print(f"  ({lat:5.0f}, {lng:5.0f}): {len(cluster):5d} discs, avg diff {avg_diff:.0f}m")


def main():
    parser = argparse.ArgumentParser(description="Analyze travel time discontinuities")
    parser.add_argument("--res", type=int, default=4, choices=[4, 5, 6],
                        help="Resolution to analyze (4=fast, 6=thorough)")
    parser.add_argument("--threshold", type=int, default=120,
                        help="Minimum time difference in minutes (default: 120)")
    parser.add_argument("--origin", default="bristol",
                        help="Origin city (default: bristol)")
    parser.add_argument("--top", type=int, default=30,
                        help="Number of worst discontinuities to show")
    args = parser.parse_args()

    print(f"loading data for {args.origin}...")

    if args.res <= 4:
        data = load_base_data(args.origin)
        cells = data['resolutions'].get(str(args.res), {})
        print(f"  res {args.res}: {len(cells):,} cells")
    elif args.res == 5:
        cells = load_r5_chunks(args.origin)
    else:
        cells = load_r6_chunks(args.origin)

    discs = analyze_discontinuities(cells, args.threshold, args.res)
    print_report(discs, args.top)

    # summary stats for test integration
    if discs:
        max_diff = max(d['diff'] for d in discs)
        osrm_boundary = sum(1 for d in discs if d['type'] == 'OSRM_BOUNDARY')
        print(f"\nmax discontinuity: {max_diff}m")
        print(f"OSRM boundary artifacts: {osrm_boundary}")


if __name__ == "__main__":
    main()
