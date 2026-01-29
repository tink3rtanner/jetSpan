#!/usr/bin/env python3
"""
routing algorithm test harness

standalone implementation of the travel time routing algorithm
for iteration and testing without the UI.

usage:
  python scripts/routing_algo.py                    # run test suite
  python scripts/routing_algo.py --random 10        # test 10 random coords
  python scripts/routing_algo.py --coord -86.9 40.4 # test specific coord (lafayette IN)
"""

import json
import argparse
import random
from math import radians, cos, sin, asin, sqrt
from dataclasses import dataclass
from typing import Optional

# =============================================================================
# DATA LOADING
# =============================================================================

def load_data():
    """load routes and airports from data files"""
    with open('data/routes.json') as f:
        routes = json.load(f)
    with open('data/airports.json') as f:
        airports = json.load(f)
    return routes, airports

# =============================================================================
# ORIGIN CONFIGS (mirrors isochrone.html ORIGINS)
# =============================================================================

ORIGINS = {
    'bristol': {
        'name': 'Bristol, UK',
        'coords': (-2.587, 51.454),
        'airports': [
            {'code': 'BRS', 'ground_time': 25},
            {'code': 'LHR', 'ground_time': 120},
            {'code': 'LGW', 'ground_time': 150},
            {'code': 'BHX', 'ground_time': 90},
        ]
    },
    'london': {
        'name': 'London, UK',
        'coords': (-0.118, 51.509),
        'airports': [
            {'code': 'LHR', 'ground_time': 45},
            {'code': 'LGW', 'ground_time': 60},
            {'code': 'STN', 'ground_time': 75},
            {'code': 'LTN', 'ground_time': 60},
        ]
    },
    'newyork': {
        'name': 'New York, USA',
        'coords': (-74.006, 40.713),
        'airports': [
            {'code': 'JFK', 'ground_time': 45},
            {'code': 'EWR', 'ground_time': 40},
            {'code': 'LGA', 'ground_time': 35},
        ]
    },
}

# =============================================================================
# UTILITIES
# =============================================================================

def haversine(lng1, lat1, lng2, lat2):
    """distance in km between two points"""
    lng1, lat1, lng2, lat2 = map(radians, [lng1, lat1, lng2, lat2])
    dlng = lng2 - lng1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
    return 2 * 6371 * asin(sqrt(a))

def estimate_flight_minutes(dist_km):
    """estimate flight time from distance (mirrors UI)"""
    if dist_km < 500:
        return round(dist_km / 400 * 60 + 30)
    if dist_km < 1500:
        return round(dist_km / 550 * 60 + 25)
    if dist_km < 4000:
        return round(dist_km / 700 * 60 + 25)
    if dist_km < 8000:
        return round(dist_km / 800 * 60 + 25)
    return round(dist_km / 850 * 60 + 30)

def estimate_ground_minutes(dist_km, speed_kph=40):
    """estimate ground transport time"""
    return round((dist_km / speed_kph) * 60)

def format_time(minutes):
    """format minutes as Xh Ym"""
    h, m = divmod(minutes, 60)
    if h == 0:
        return f"{m}m"
    return f"{h}h {m:02d}m"

# =============================================================================
# ROUTE RESULT
# =============================================================================

@dataclass
class RouteResult:
    total_minutes: int
    origin_airport: str
    dest_airport: str
    ground_to: int      # mins to origin airport
    overhead: int       # airport overhead
    flight: int         # flight time
    arrival: int        # arrival overhead
    ground_from: int    # mins from dest airport to final dest
    dest_distance_km: float  # distance from dest airport to final dest
    route_exists: bool  # whether route actually exists in data

    def __str__(self):
        status = "REAL" if self.route_exists else "FAKE"
        return (
            f"{format_time(self.total_minutes):>8} | "
            f"{self.origin_airport}->{self.dest_airport} | "
            f"ground:{self.ground_to}+{self.ground_from}m "
            f"flight:{self.flight}m "
            f"dest:{self.dest_distance_km:.0f}km | "
            f"[{status}]"
        )

    @property
    def is_connection(self):
        return False


@dataclass
class ConnectionResult:
    """result for 1-stop connection routing"""
    total_minutes: int
    origin_airport: str
    hub_airport: str
    dest_airport: str
    ground_to: int
    overhead: int
    leg1_flight: int
    connection: int  # connection time at hub
    leg2_flight: int
    arrival: int
    ground_from: int
    dest_distance_km: float

    def __str__(self):
        return (
            f"{format_time(self.total_minutes):>8} | "
            f"{self.origin_airport}->{self.hub_airport}->{self.dest_airport} | "
            f"ground:{self.ground_to}+{self.ground_from}m "
            f"flights:{self.leg1_flight}+{self.leg2_flight}m "
            f"connect:{self.connection}m "
            f"dest:{self.dest_distance_km:.0f}km | "
            f"[1-STOP]"
        )

    @property
    def is_connection(self):
        return True

    @property
    def route_exists(self):
        return True  # if we built it, both legs exist

# =============================================================================
# ROUTING ALGORITHMS
# =============================================================================

class Router:
    """base router with shared functionality"""

    def __init__(self, routes: dict, airports: dict, origin_key: str):
        self.routes = routes
        self.airports = airports
        self.origin = ORIGINS[origin_key]
        self.origin_airports = self.origin['airports']

    def has_route(self, from_code: str, to_code: str) -> bool:
        """check if direct route exists (either direction)"""
        if from_code in self.routes and to_code in self.routes[from_code]:
            return True
        if to_code in self.routes and from_code in self.routes[to_code]:
            return True
        return False

    def get_airport_coords(self, code: str) -> Optional[tuple]:
        """get airport coordinates"""
        apt = self.airports.get(code)
        if apt:
            return (apt['lng'], apt['lat'])
        return None

    def find_nearest_airports(self, dest_coords: tuple, count: int = 10) -> list:
        """find N nearest airports to destination coords"""
        lng, lat = dest_coords
        airports_with_dist = []

        for code, apt in self.airports.items():
            dist = haversine(lng, lat, apt['lng'], apt['lat'])
            airports_with_dist.append((code, dist))

        airports_with_dist.sort(key=lambda x: x[1])
        return airports_with_dist[:count]

    def calc_route(self, origin_apt: dict, dest_code: str,
                   dest_coords: tuple, check_route: bool) -> Optional[RouteResult]:
        """calculate route from origin airport to destination airport"""
        origin_code = origin_apt['code']
        origin_coords = self.get_airport_coords(origin_code)
        dest_apt_coords = self.get_airport_coords(dest_code)

        if not origin_coords or not dest_apt_coords:
            return None

        route_exists = self.has_route(origin_code, dest_code)

        if check_route and not route_exists:
            return None  # skip if route checking enabled and no route

        # calc components
        ground_to = origin_apt['ground_time']
        overhead = 90

        flight_dist = haversine(origin_coords[0], origin_coords[1],
                               dest_apt_coords[0], dest_apt_coords[1])
        flight = estimate_flight_minutes(flight_dist)

        # international?
        origin_country = self.airports.get(origin_code, {}).get('country', '')
        dest_country = self.airports.get(dest_code, {}).get('country', '')
        arrival = 60 if origin_country != dest_country else 30

        # ground from dest airport to final dest
        dest_dist = haversine(dest_apt_coords[0], dest_apt_coords[1],
                             dest_coords[0], dest_coords[1])
        ground_from = estimate_ground_minutes(dest_dist)

        total = ground_to + overhead + flight + arrival + ground_from

        return RouteResult(
            total_minutes=total,
            origin_airport=origin_code,
            dest_airport=dest_code,
            ground_to=ground_to,
            overhead=overhead,
            flight=flight,
            arrival=arrival,
            ground_from=ground_from,
            dest_distance_km=dest_dist,
            route_exists=route_exists,
        )


class BuggyRouter(Router):
    """
    CURRENT (BUGGY) algorithm - estimates flight even when no route exists
    """

    def find_best_route(self, dest_coords: tuple) -> Optional[RouteResult]:
        nearest = self.find_nearest_airports(dest_coords, count=5)

        best = None
        for origin_apt in self.origin_airports:
            for dest_code, dest_dist in nearest:
                # BUG: doesn't check if route exists, always calculates
                result = self.calc_route(origin_apt, dest_code, dest_coords,
                                        check_route=False)
                if result and (best is None or result.total_minutes < best.total_minutes):
                    best = result

        return best


class FixedRouter(Router):
    """
    FIXED algorithm - only considers routes that actually exist
    expands search if no reachable airports found nearby
    """

    # max distance from dest airport to final destination (nobody drives 500km+)
    MAX_GROUND_DIST_KM = 400

    def __init__(self, routes: dict, airports: dict, origin_key: str):
        super().__init__(routes, airports, origin_key)
        # precompute set of all reachable airports from this origin
        self.reachable = self._build_reachable_set()

    def _build_reachable_set(self) -> set:
        """build set of all airports reachable from origin airports"""
        reachable = set()
        for origin_apt in self.origin_airports:
            code = origin_apt['code']
            # outbound routes
            if code in self.routes:
                reachable.update(self.routes[code])
            # inbound routes (bidirectional)
            for from_code, dests in self.routes.items():
                if code in dests:
                    reachable.add(from_code)
        return reachable

    def find_nearest_reachable_airports(self, dest_coords: tuple,
                                        count: int = 5,
                                        max_dist_km: float = None) -> list:
        """find nearest airports that have routes from origin"""
        lng, lat = dest_coords
        reachable_with_dist = []

        for code in self.reachable:
            apt = self.airports.get(code)
            if not apt:
                continue
            dist = haversine(lng, lat, apt['lng'], apt['lat'])
            if max_dist_km is None or dist <= max_dist_km:
                reachable_with_dist.append((code, dist))

        reachable_with_dist.sort(key=lambda x: x[1])
        return reachable_with_dist[:count]

    def find_best_route(self, dest_coords: tuple) -> Optional[RouteResult]:
        # find nearest reachable airports within reasonable ground distance
        nearest_reachable = self.find_nearest_reachable_airports(
            dest_coords, count=10, max_dist_km=self.MAX_GROUND_DIST_KM
        )

        if not nearest_reachable:
            return None

        best = None
        for origin_apt in self.origin_airports:
            for dest_code, dest_dist in nearest_reachable:
                result = self.calc_route(origin_apt, dest_code, dest_coords,
                                        check_route=True)
                if result and (best is None or result.total_minutes < best.total_minutes):
                    best = result

        return best


class ConnectionRouter(Router):
    """
    EXPERIMENTAL: 1-stop connection routing via major hubs

    tries direct first, then 1-stop via hubs if no direct found
    """

    MAX_GROUND_DIST_KM = 400
    CONNECTION_TIME = 120  # minutes for hub connection (deplane, walk, reboard)

    # major global hubs for connections
    # grouped by region for potential optimization
    HUBS = {
        'europe': ['LHR', 'CDG', 'FRA', 'AMS', 'MAD', 'FCO', 'IST'],
        'middle_east': ['DXB', 'DOH', 'AUH'],
        'asia': ['SIN', 'HKG', 'BKK', 'ICN', 'NRT', 'PEK', 'PVG'],
        'north_america': ['JFK', 'LAX', 'ORD', 'DFW', 'ATL', 'SFO', 'YYZ', 'YVR'],
        'oceania': ['SYD', 'AKL'],
        'south_america': ['GRU', 'SCL', 'BOG'],
        'africa': ['JNB', 'CAI', 'NBO'],
    }

    def __init__(self, routes: dict, airports: dict, origin_key: str):
        super().__init__(routes, airports, origin_key)
        self.reachable_direct = self._build_reachable_set()
        self.all_hubs = self._flatten_hubs()

    def _build_reachable_set(self) -> set:
        """airports reachable by direct flight from origin"""
        reachable = set()
        for origin_apt in self.origin_airports:
            code = origin_apt['code']
            if code in self.routes:
                reachable.update(self.routes[code])
            for from_code, dests in self.routes.items():
                if code in dests:
                    reachable.add(from_code)
        return reachable

    def _flatten_hubs(self) -> list:
        """all hubs as flat list"""
        hubs = []
        for region_hubs in self.HUBS.values():
            hubs.extend(region_hubs)
        return hubs

    def find_nearest_airports_in_set(self, dest_coords: tuple, airport_set: set,
                                     count: int = 5, max_dist_km: float = None) -> list:
        """find nearest airports from a given set"""
        lng, lat = dest_coords
        with_dist = []
        for code in airport_set:
            apt = self.airports.get(code)
            if not apt:
                continue
            dist = haversine(lng, lat, apt['lng'], apt['lat'])
            if max_dist_km is None or dist <= max_dist_km:
                with_dist.append((code, dist))
        with_dist.sort(key=lambda x: x[1])
        return with_dist[:count]

    def find_best_direct_route(self, dest_coords: tuple) -> Optional[RouteResult]:
        """try direct routing first"""
        nearest = self.find_nearest_airports_in_set(
            dest_coords, self.reachable_direct,
            count=10, max_dist_km=self.MAX_GROUND_DIST_KM
        )
        if not nearest:
            return None

        best = None
        for origin_apt in self.origin_airports:
            for dest_code, dest_dist in nearest:
                result = self.calc_route(origin_apt, dest_code, dest_coords, check_route=True)
                if result and (best is None or result.total_minutes < best.total_minutes):
                    best = result
        return best

    def find_best_1stop_route(self, dest_coords: tuple) -> Optional['ConnectionResult']:
        """try 1-stop routing via hubs"""
        # find airports near destination (any airport, not just reachable)
        nearest_dest = self.find_nearest_airports(dest_coords, count=10)
        # filter to within ground distance
        nearest_dest = [(c, d) for c, d in nearest_dest if d <= self.MAX_GROUND_DIST_KM]

        if not nearest_dest:
            return None

        best = None
        for origin_apt in self.origin_airports:
            origin_code = origin_apt['code']

            for hub_code in self.all_hubs:
                # check: origin -> hub exists?
                if not self.has_route(origin_code, hub_code):
                    continue

                for dest_code, dest_dist in nearest_dest:
                    # check: hub -> dest exists?
                    if not self.has_route(hub_code, dest_code):
                        continue

                    # we have a valid 1-stop route!
                    result = self._calc_1stop_route(
                        origin_apt, hub_code, dest_code, dest_coords, dest_dist
                    )
                    if result and (best is None or result.total_minutes < best.total_minutes):
                        best = result

        return best

    def _calc_1stop_route(self, origin_apt: dict, hub_code: str,
                          dest_code: str, dest_coords: tuple,
                          dest_dist: float) -> Optional['ConnectionResult']:
        """calculate 1-stop route time"""
        origin_code = origin_apt['code']
        origin_coords = self.get_airport_coords(origin_code)
        hub_coords = self.get_airport_coords(hub_code)
        dest_apt_coords = self.get_airport_coords(dest_code)

        if not all([origin_coords, hub_coords, dest_apt_coords]):
            return None

        # leg 1: origin -> hub
        leg1_dist = haversine(origin_coords[0], origin_coords[1],
                             hub_coords[0], hub_coords[1])
        leg1_flight = estimate_flight_minutes(leg1_dist)

        # leg 2: hub -> dest
        leg2_dist = haversine(hub_coords[0], hub_coords[1],
                             dest_apt_coords[0], dest_apt_coords[1])
        leg2_flight = estimate_flight_minutes(leg2_dist)

        # ground times
        ground_to = origin_apt['ground_time']
        ground_from = estimate_ground_minutes(dest_dist)

        # overhead times
        origin_overhead = 90  # security etc at origin
        connection_overhead = self.CONNECTION_TIME  # at hub
        # arrival overhead (customs if intl)
        origin_country = self.airports.get(origin_code, {}).get('country', '')
        dest_country = self.airports.get(dest_code, {}).get('country', '')
        arrival_overhead = 60 if origin_country != dest_country else 30

        total = (ground_to + origin_overhead + leg1_flight +
                connection_overhead + leg2_flight +
                arrival_overhead + ground_from)

        return ConnectionResult(
            total_minutes=total,
            origin_airport=origin_code,
            hub_airport=hub_code,
            dest_airport=dest_code,
            ground_to=ground_to,
            overhead=origin_overhead,
            leg1_flight=leg1_flight,
            connection=connection_overhead,
            leg2_flight=leg2_flight,
            arrival=arrival_overhead,
            ground_from=ground_from,
            dest_distance_km=dest_dist,
        )

    def find_best_route(self, dest_coords: tuple):
        """try direct first, then 1-stop"""
        direct = self.find_best_direct_route(dest_coords)
        if direct:
            return direct

        # no direct, try 1-stop
        return self.find_best_1stop_route(dest_coords)


# =============================================================================
# TEST HARNESS
# =============================================================================

def test_coordinate(lng: float, lat: float, routes: dict, airports: dict,
                    origin_key: str = 'bristol', verbose: bool = True) -> dict:
    """test both algorithms on a single coordinate"""

    buggy = BuggyRouter(routes, airports, origin_key)
    fixed = FixedRouter(routes, airports, origin_key)

    dest_coords = (lng, lat)

    buggy_result = buggy.find_best_route(dest_coords)
    fixed_result = fixed.find_best_route(dest_coords)

    if verbose:
        print(f"\ncoord: ({lng:.3f}, {lat:.3f}) from {origin_key}")
        print("-" * 70)
        print(f"  BUGGY: {buggy_result}")
        print(f"  FIXED: {fixed_result}")

        if buggy_result and fixed_result:
            diff = fixed_result.total_minutes - buggy_result.total_minutes
            if diff > 0:
                print(f"  DELTA: +{diff}min (fixed is slower but REAL)")
            elif diff < 0:
                print(f"  DELTA: {diff}min (fixed found better route)")

            if buggy_result.dest_airport != fixed_result.dest_airport:
                print(f"  AIRPORT CHANGE: {buggy_result.dest_airport} -> {fixed_result.dest_airport}")

    return {
        'coords': dest_coords,
        'buggy': buggy_result,
        'fixed': fixed_result,
    }


def run_test_suite(routes: dict, airports: dict):
    """run tests on known problematic coordinates"""

    print("=" * 70)
    print("ROUTING ALGORITHM TEST SUITE")
    print("=" * 70)

    # test cases: (lng, lat, description)
    test_cases = [
        # US midwest regionals - should route via ORD not tiny airports
        (-86.9, 40.4, "Lafayette, IN (near LAF)"),
        (-88.2, 40.1, "Champaign, IL (near CMI)"),
        (-89.0, 40.5, "Bloomington, IL (near BMI)"),
        (-90.7, 42.4, "Dubuque, IA (near DBQ)"),
        (-89.4, 43.1, "Madison, WI (near MSN)"),

        # major cities - should work fine
        (-87.6, 41.9, "Chicago, IL (near ORD)"),
        (-74.0, 40.7, "New York, NY (near JFK)"),
        (-118.2, 34.0, "Los Angeles, CA (near LAX)"),

        # european - should work fine
        (2.35, 48.86, "Paris, FR (near CDG)"),
        (-0.12, 51.51, "London, UK (near LHR)"),
        (13.4, 52.5, "Berlin, DE (near BER)"),

        # remote/edge cases
        (-3.7, 40.4, "Madrid, ES"),
        (139.7, 35.7, "Tokyo, JP"),
        (151.2, -33.9, "Sydney, AU"),
    ]

    results = []
    issues = []

    for lng, lat, desc in test_cases:
        print(f"\n{'='*70}")
        print(f"TEST: {desc}")
        result = test_coordinate(lng, lat, routes, airports, 'bristol')
        results.append((desc, result))

        # flag issues
        buggy = result['buggy']
        fixed = result['fixed']

        if buggy and not buggy.route_exists:
            issues.append(f"BUGGY used fake route: {desc} via {buggy.dest_airport}")

        if fixed is None and buggy is not None:
            issues.append(f"FIXED found no route but BUGGY did: {desc}")

    # summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if issues:
        print(f"\n{len(issues)} issues found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nno issues found")

    # stats
    fake_routes = sum(1 for _, r in results if r['buggy'] and not r['buggy'].route_exists)
    print(f"\nstats:")
    print(f"  total tests: {len(results)}")
    print(f"  buggy fake routes: {fake_routes}")


def run_random_tests(n: int, routes: dict, airports: dict):
    """test N random coordinates"""
    print(f"\ntesting {n} random coordinates...")

    issues = 0
    for i in range(n):
        # random coord (land-ish areas)
        lng = random.uniform(-120, 140)
        lat = random.uniform(-40, 60)

        result = test_coordinate(lng, lat, routes, airports, 'bristol', verbose=True)

        if result['buggy'] and not result['buggy'].route_exists:
            issues += 1

    print(f"\n{issues}/{n} had fake routes in buggy algorithm")


def show_reachable_stats(routes: dict, airports: dict, origin_key: str = 'bristol'):
    """show stats about reachable airports from origin"""
    fixed = FixedRouter(routes, airports, origin_key)

    print(f"\n{'='*70}")
    print(f"REACHABLE AIRPORTS FROM {origin_key.upper()}")
    print(f"{'='*70}")
    print(f"\ntotal reachable: {len(fixed.reachable)}")

    # group by country
    by_country = {}
    for code in fixed.reachable:
        apt = airports.get(code)
        if apt:
            country = apt.get('country', 'unknown')
            by_country.setdefault(country, []).append(code)

    print(f"\nby country (top 20):")
    for country, codes in sorted(by_country.items(), key=lambda x: -len(x[1]))[:20]:
        print(f"  {country}: {len(codes)} airports")

    # show US coverage specifically
    us_airports = by_country.get('US', [])
    print(f"\nUS airports reachable: {len(us_airports)}")
    if us_airports:
        # show which US airports
        us_with_names = []
        for code in us_airports:
            apt = airports.get(code)
            if apt:
                us_with_names.append((code, apt.get('name', '')[:30]))
        us_with_names.sort(key=lambda x: x[0])
        print("  " + ", ".join(f"{c}" for c, n in us_with_names[:30]))
        if len(us_with_names) > 30:
            print(f"  ... and {len(us_with_names) - 30} more")


def debug_route(lng: float, lat: float, routes: dict, airports: dict,
                origin_key: str = 'bristol'):
    """detailed debug of routing for a specific coordinate"""
    fixed = FixedRouter(routes, airports, origin_key)
    dest_coords = (lng, lat)

    print(f"\n{'='*70}")
    print(f"DEBUG: routing to ({lng}, {lat}) from {origin_key}")
    print(f"{'='*70}")

    # find nearest airports (any)
    nearest_all = fixed.find_nearest_airports(dest_coords, count=10)
    print(f"\nnearest 10 airports (any):")
    for code, dist in nearest_all:
        has_route = code in fixed.reachable
        apt = airports.get(code, {})
        print(f"  {code:4} {dist:6.0f}km {'REACHABLE' if has_route else 'no route':12} ({apt.get('name', '')[:30]})")

    # find nearest reachable
    nearest_reachable = fixed.find_nearest_reachable_airports(dest_coords, count=10, max_dist_km=400)
    print(f"\nnearest 10 REACHABLE airports (within 400km):")
    if not nearest_reachable:
        print("  NONE - location unreachable by direct flight")
    else:
        for code, dist in nearest_reachable:
            apt = airports.get(code, {})
            # show which origin airports have routes
            origin_routes = []
            for orig in fixed.origin_airports:
                if fixed.has_route(orig['code'], code):
                    origin_routes.append(orig['code'])
            print(f"  {code:4} {dist:6.0f}km from: {','.join(origin_routes):20} ({apt.get('name', '')[:25]})")

    # run full route calc
    result = fixed.find_best_route(dest_coords)
    print(f"\nBEST ROUTE:")
    if result:
        print(f"  {result}")
    else:
        print("  UNREACHABLE")


def test_connections(routes: dict, airports: dict, origin_key: str = 'bristol'):
    """test connection routing on previously unreachable destinations"""

    print("=" * 70)
    print(f"CONNECTION ROUTING TEST from {origin_key}")
    print("=" * 70)

    conn_router = ConnectionRouter(routes, airports, origin_key)
    fixed_router = FixedRouter(routes, airports, origin_key)

    # destinations that need connections from bristol
    test_cases = [
        (151.2, -33.9, 'Sydney'),
        (144.9, -37.8, 'Melbourne'),
        (-157.9, 21.3, 'Honolulu'),
        (174.8, -41.3, 'Wellington NZ'),
        (174.8, -36.9, 'Auckland'),
        # also test some that should be direct
        (-0.12, 51.51, 'London'),
        (-74.0, 40.7, 'New York'),
        (139.7, 35.7, 'Tokyo'),
    ]

    for lng, lat, name in test_cases:
        dest_coords = (lng, lat)

        direct = fixed_router.find_best_route(dest_coords)
        with_conn = conn_router.find_best_route(dest_coords)

        print(f"\n{name}:")
        print(f"  direct:     {direct if direct else 'UNREACHABLE'}")
        print(f"  w/connect:  {with_conn if with_conn else 'UNREACHABLE'}")

        if with_conn and not direct:
            print(f"  ^ CONNECTION ENABLED THIS ROUTE")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='routing algorithm test harness')
    parser.add_argument('--random', type=int, help='test N random coordinates')
    parser.add_argument('--coord', nargs=2, type=float, metavar=('LNG', 'LAT'),
                       help='test specific coordinate')
    parser.add_argument('--debug', nargs=2, type=float, metavar=('LNG', 'LAT'),
                       help='detailed debug for specific coordinate')
    parser.add_argument('--stats', action='store_true',
                       help='show reachable airport stats')
    parser.add_argument('--connections', action='store_true',
                       help='test 1-stop connection routing')
    parser.add_argument('--origin', default='bristol',
                       choices=list(ORIGINS.keys()),
                       help='origin city')
    args = parser.parse_args()

    routes, airports = load_data()
    print(f"loaded {len(routes)} route origins, {len(airports)} airports")

    if args.connections:
        test_connections(routes, airports, args.origin)
    elif args.debug:
        debug_route(args.debug[0], args.debug[1], routes, airports, args.origin)
    elif args.coord:
        test_coordinate(args.coord[0], args.coord[1], routes, airports, args.origin)
    elif args.random:
        run_random_tests(args.random, routes, airports)
    elif args.stats:
        show_reachable_stats(routes, airports, args.origin)
    else:
        run_test_suite(routes, airports)
