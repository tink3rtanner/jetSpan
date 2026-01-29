#!/usr/bin/env python3
"""
validate route data against known nonstop flights
"""

import json

with open('data/routes.json') as f:
    routes = json.load(f)

def has_route(f, t):
    """check bidirectional"""
    return (f in routes and t in routes[f]) or (t in routes and f in routes[t])

print("=" * 70)
print("ROUTE DATA VALIDATION")
print("=" * 70)

# known nonstops that SHOULD exist
known_nonstops = [
    ('JFK', 'HNL', 'JFK-Honolulu nonstop (multiple carriers)'),
    ('LHR', 'PER', 'LHR-Perth nonstop (Qantas QF9/10)'),
    ('LHR', 'GIG', 'LHR-Rio nonstop (BA)'),
    ('JFK', 'LAX', 'JFK-LAX nonstop (many carriers)'),
    ('LHR', 'JFK', 'LHR-JFK nonstop (BA, AA, etc)'),
    ('CDG', 'JFK', 'CDG-JFK nonstop (AF, Delta)'),
    ('FRA', 'JFK', 'FRA-JFK nonstop (LH, etc)'),
    ('SIN', 'SYD', 'SIN-SYD nonstop (SQ, Qantas)'),
    ('LAX', 'HND', 'LAX-Tokyo Haneda nonstop'),
    ('SFO', 'AKL', 'SFO-Auckland nonstop (Air NZ)'),
    # a few more
    ('LHR', 'SIN', 'LHR-Singapore nonstop (SQ, BA)'),
    ('LHR', 'HKG', 'LHR-Hong Kong nonstop'),
    ('LHR', 'DXB', 'LHR-Dubai nonstop (Emirates, BA)'),
    ('LAX', 'SYD', 'LAX-Sydney nonstop (Qantas, Delta)'),
    ('DFW', 'SYD', 'DFW-Sydney nonstop (Qantas)'),
]

print("\nKNOWN NONSTOPS (should be in data):")
print("-" * 70)
missing = []
for orig, dest, desc in known_nonstops:
    exists = has_route(orig, dest)
    status = "OK" if exists else "MISSING"
    print(f"  {orig}-{dest}: {status:8} | {desc}")
    if not exists:
        missing.append((orig, dest, desc))

# known connection-only routes that should NOT exist as nonstops
connection_only = [
    ('LHR', 'SYD', 'LHR-Sydney (requires stop, Project Sunrise 2027)'),
    ('LHR', 'MEL', 'LHR-Melbourne (requires stop via SIN/DXB/etc)'),
    ('LHR', 'HNL', 'LHR-Honolulu (requires stop via LAX/SFO)'),
    ('BRS', 'HNL', 'Bristol-Honolulu (requires multiple stops)'),
    ('BRS', 'SYD', 'Bristol-Sydney (requires multiple stops)'),
    ('JFK', 'SYD', 'JFK-Sydney (no current nonstop)'),
    ('LHR', 'AKL', 'LHR-Auckland (requires stop)'),
]

print("\nCONNECTION-ONLY (should NOT be in nonstop data):")
print("-" * 70)
incorrect = []
for orig, dest, desc in connection_only:
    exists = has_route(orig, dest)
    status = "OK (absent)" if not exists else "INCORRECT (present)"
    print(f"  {orig}-{dest}: {status:18} | {desc}")
    if exists:
        incorrect.append((orig, dest, desc))

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Known nonstops missing: {len(missing)}/{len(known_nonstops)}")
for o, d, desc in missing:
    print(f"  - {o}-{d}: {desc}")

print(f"\nIncorrect nonstops present: {len(incorrect)}/{len(connection_only)}")
for o, d, desc in incorrect:
    print(f"  - {o}-{d}: {desc}")

if not missing and not incorrect:
    print("\nroute data looks good for nonstop-only model")
