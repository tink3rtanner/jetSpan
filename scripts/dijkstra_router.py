#!/usr/bin/env python3
"""
one-to-all shortest path routing using bounded-stops dijkstra

the right way to do this:
1. build flight graph from routes.json
2. run multi-source dijkstra from origin airports (with stop cap)
3. output best_time_to_airport for ALL airports
4. hex evaluation = min(best_time[a] + ground_time(a, cell))

this avoids the per-cell combinatorial blowup.
"""

import json
import heapq
import argparse
from math import radians, cos, sin, asin, sqrt
from dataclasses import dataclass, field
from typing import Optional

# =============================================================================
# DATA LOADING
# =============================================================================

def load_data():
    with open('data/routes.json') as f:
        routes = json.load(f)
    with open('data/airports.json') as f:
        airports = json.load(f)
    return routes, airports

# =============================================================================
# ORIGINS
# =============================================================================

ORIGINS = {
    'bristol': {
        'name': 'Bristol, UK',
        'coords': (-2.587, 51.454),
        # ground times are realistic train estimates (driving worse for london)
        'airports': [
            {'code': 'BRS', 'ground_time': 25},   # 25min drive to bristol airport
            {'code': 'LHR', 'ground_time': 110},  # 1h30 train to paddington + 20min heathrow express
            {'code': 'LGW', 'ground_time': 150},  # ~2h30 train via london victoria
            {'code': 'BHX', 'ground_time': 131},  # 1h20 train to birmingham + 50min to airport
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
    """distance in km"""
    lng1, lat1, lng2, lat2 = map(radians, [lng1, lat1, lng2, lat2])
    dlng = lng2 - lng1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
    return 2 * 6371 * asin(sqrt(a))

def estimate_flight_minutes(dist_km):
    """estimate flight time from distance"""
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
    return round((dist_km / speed_kph) * 60)

def format_time(minutes):
    h, m = divmod(minutes, 60)
    if h == 0:
        return f"{m}m"
    return f"{h}h {m:02d}m"

# =============================================================================
# FLIGHT GRAPH
# =============================================================================

class FlightGraph:
    """
    directed graph of airports and flight routes

    nodes: airport codes
    edges: (from, to) -> flight_time_minutes
    """

    def __init__(self, routes: dict, airports: dict):
        self.routes = routes
        self.airports = airports
        self.edges = {}  # (from, to) -> flight_time
        self.adjacency = {}  # from -> [(to, time), ...]
        self._build_graph()

    def _build_graph(self):
        """build adjacency list from routes"""
        for origin, dests in self.routes.items():
            if origin not in self.airports:
                continue
            origin_apt = self.airports[origin]
            origin_coords = (origin_apt['lng'], origin_apt['lat'])

            for dest in dests:
                if dest not in self.airports:
                    continue
                dest_apt = self.airports[dest]
                dest_coords = (dest_apt['lng'], dest_apt['lat'])

                dist = haversine(origin_coords[0], origin_coords[1],
                                dest_coords[0], dest_coords[1])
                flight_time = estimate_flight_minutes(dist)

                self.edges[(origin, dest)] = flight_time

                if origin not in self.adjacency:
                    self.adjacency[origin] = []
                self.adjacency[origin].append((dest, flight_time))

        # also add reverse edges (routes are often bidirectional)
        for origin, dests in self.routes.items():
            for dest in dests:
                if (dest, origin) not in self.edges and (origin, dest) in self.edges:
                    # add reverse
                    flight_time = self.edges[(origin, dest)]
                    self.edges[(dest, origin)] = flight_time
                    if dest not in self.adjacency:
                        self.adjacency[dest] = []
                    self.adjacency[dest].append((origin, flight_time))

    def get_neighbors(self, airport: str) -> list:
        """return [(neighbor, flight_time), ...]"""
        return self.adjacency.get(airport, [])

    def stats(self):
        return {
            'nodes': len(set(a for a, _ in self.edges.keys()) | set(b for _, b in self.edges.keys())),
            'edges': len(self.edges),
        }

# =============================================================================
# DIJKSTRA WITH BOUNDED STOPS
# =============================================================================

@dataclass
class PathState:
    """state in the priority queue"""
    total_time: int
    airport: str
    stops: int
    path: list = field(default_factory=list)

    def __lt__(self, other):
        return self.total_time < other.total_time

@dataclass
class AirportResult:
    """best path result to an airport"""
    total_time: int
    stops: int
    path: list  # list of airport codes
    origin_airport: str  # which origin airport we departed from

    def path_str(self):
        return ' -> '.join(self.path)

class DijkstraRouter:
    """
    multi-source bounded-stops dijkstra

    computes best time from origin city to ALL airports
    """

    # cost parameters
    ORIGIN_OVERHEAD = 90      # security, boarding at origin
    CONNECTION_TIME = 90      # min connection time at intermediate
    STOP_PENALTY = 30         # discourage unnecessary stops
    ARRIVAL_OVERHEAD_DOMESTIC = 30
    ARRIVAL_OVERHEAD_INTL = 60

    # constraints
    MAX_STOPS = 2
    MAX_CIRCUITY = 1.8  # reject if total flight dist > 1.8x great circle
    MIN_FLY_DISTANCE = 150  # km - don't fly if destination closer than this (just drive)

    def __init__(self, graph: FlightGraph, airports: dict, origin_key: str):
        self.graph = graph
        self.airports = airports
        self.origin = ORIGINS[origin_key]
        self.origin_airports = self.origin['airports']
        self.origin_coords = self.origin['coords']

        # results: airport -> AirportResult
        self.best_times = {}

    def _calc_path_distance(self, path: list) -> float:
        """calculate total flight distance for a path"""
        total = 0
        for i in range(len(path) - 1):
            a1 = self.airports.get(path[i])
            a2 = self.airports.get(path[i+1])
            if a1 and a2:
                total += haversine(a1['lng'], a1['lat'], a2['lng'], a2['lat'])
        return total

    def _check_circuity(self, dest_code: str, path: list) -> bool:
        """return True if route passes circuity check"""
        apt = self.airports.get(dest_code)
        if not apt:
            return True  # can't check, allow it

        # direct distance from origin city to destination airport
        direct_dist = haversine(
            self.origin_coords[0], self.origin_coords[1],
            apt['lng'], apt['lat']
        )

        # if destination is very close, should just drive (don't fly)
        if direct_dist < self.MIN_FLY_DISTANCE:
            return False

        # check circuity
        flight_dist = self._calc_path_distance(path)
        if direct_dist > 0 and flight_dist / direct_dist > self.MAX_CIRCUITY:
            return False

        return True

    def run(self):
        """
        run dijkstra from all origin airports

        stop counting:
        - 0 stops = direct flight (origin -> dest)
        - 1 stop = one connection (origin -> hub -> dest)
        - 2 stops = two connections (origin -> hub1 -> hub2 -> dest)

        we count the number of INTERMEDIATE airports (connections made)
        """
        # priority queue: (total_time, airport, stops, path)
        pq = []

        # visited: (airport, stops) -> best_time
        visited = {}

        # seed with origin airports (at the origin, we've taken 0 flights)
        for orig in self.origin_airports:
            code = orig['code']
            ground_time = orig['ground_time']
            initial_time = ground_time + self.ORIGIN_OVERHEAD

            state = PathState(
                total_time=initial_time,
                airport=code,
                stops=-1,  # will become 0 after first flight
                path=[code]
            )
            heapq.heappush(pq, state)

        while pq:
            state = heapq.heappop(pq)

            # skip if we've seen this (airport, stops) with better time
            key = (state.airport, state.stops)
            if key in visited and visited[key] <= state.total_time:
                continue
            visited[key] = state.total_time

            # record best time to this airport (if not seen or better)
            # only record if we've taken at least one flight (stops >= 0)
            # and route passes circuity/distance checks
            if state.stops >= 0:
                if self._check_circuity(state.airport, state.path):
                    if state.airport not in self.best_times or \
                       state.total_time < self.best_times[state.airport].total_time:
                        self.best_times[state.airport] = AirportResult(
                            total_time=state.total_time,
                            stops=state.stops,
                            path=state.path.copy(),
                            origin_airport=state.path[0] if state.path else ''
                        )

            # don't expand if at max stops
            if state.stops >= self.MAX_STOPS:
                continue

            # expand to neighbors
            for neighbor, flight_time in self.graph.get_neighbors(state.airport):
                # stop count: increment only if we're already airside (stops >= 0)
                # this counts intermediate airports (connections)
                if state.stops < 0:
                    # first flight: origin -> first dest = 0 stops (direct)
                    new_stops = 0
                    connection_cost = 0
                else:
                    # subsequent flight: this is a connection
                    new_stops = state.stops + 1
                    connection_cost = self.CONNECTION_TIME + self.STOP_PENALTY

                new_time = state.total_time + flight_time + connection_cost
                new_path = state.path + [neighbor]

                new_state = PathState(
                    total_time=new_time,
                    airport=neighbor,
                    stops=new_stops,
                    path=new_path
                )

                # only add if potentially better
                new_key = (neighbor, new_stops)
                if new_key not in visited or visited[new_key] > new_time:
                    heapq.heappush(pq, new_state)

        return self.best_times

    def query_cell(self, lng: float, lat: float,
                   max_ground_km: float = 400,
                   k_nearest: int = 10) -> Optional[dict]:
        """
        query best route to a cell location

        finds k nearest airports and returns best total time
        compares "just drive" vs "fly route" for nearby destinations
        """
        dist_from_origin = haversine(
            self.origin_coords[0], self.origin_coords[1], lng, lat
        )

        # calculate drive-only option (always available within reasonable distance)
        drive_only = None
        if dist_from_origin < max_ground_km:
            ground_time = estimate_ground_minutes(dist_from_origin)
            drive_only = {
                'total_minutes': ground_time,
                'dest_airport': None,
                'dest_distance_km': dist_from_origin,
                'ground_from': ground_time,
                'arrival_overhead': 0,
                'flight_time': 0,
                'stops': -1,  # indicates "drive only"
                'path': 'drive',
            }

        # for very close destinations, just drive (don't bother checking flights)
        if dist_from_origin < self.MIN_FLY_DISTANCE:
            return drive_only

        # find k nearest airports that we can reach
        candidates = []
        for code, result in self.best_times.items():
            apt = self.airports.get(code)
            if not apt:
                continue
            dist = haversine(lng, lat, apt['lng'], apt['lat'])
            if dist <= max_ground_km:
                candidates.append((code, dist, result))

        if not candidates:
            # no flight route - return drive if available
            return drive_only

        # sort by total time (airport time + ground time)
        def total_time(c):
            code, dist, result = c
            ground = estimate_ground_minutes(dist)
            # add arrival overhead
            origin_country = self.airports.get(result.origin_airport, {}).get('country', '')
            dest_country = self.airports.get(code, {}).get('country', '')
            arrival = self.ARRIVAL_OVERHEAD_INTL if origin_country != dest_country else self.ARRIVAL_OVERHEAD_DOMESTIC
            return result.total_time + ground + arrival

        candidates.sort(key=total_time)

        best_code, best_dist, best_result = candidates[0]
        ground_time = estimate_ground_minutes(best_dist)
        origin_country = self.airports.get(best_result.origin_airport, {}).get('country', '')
        dest_country = self.airports.get(best_code, {}).get('country', '')
        arrival = self.ARRIVAL_OVERHEAD_INTL if origin_country != dest_country else self.ARRIVAL_OVERHEAD_DOMESTIC

        fly_result = {
            'total_minutes': best_result.total_time + ground_time + arrival,
            'dest_airport': best_code,
            'dest_distance_km': best_dist,
            'ground_from': ground_time,
            'arrival_overhead': arrival,
            'flight_time': best_result.total_time,
            'stops': best_result.stops,
            'path': best_result.path_str(),
        }

        # compare fly vs drive - pick faster option
        if drive_only and drive_only['total_minutes'] < fly_result['total_minutes']:
            return drive_only

        return fly_result

# =============================================================================
# TEST HARNESS
# =============================================================================

def run_tests(routes, airports, origin_key='bristol'):
    print("=" * 70)
    print(f"DIJKSTRA ROUTER TEST - {origin_key}")
    print("=" * 70)

    # build graph
    graph = FlightGraph(routes, airports)
    stats = graph.stats()
    print(f"\nflight graph: {stats['nodes']} airports, {stats['edges']} edges")

    # run dijkstra
    router = DijkstraRouter(graph, airports, origin_key)
    print(f"running dijkstra from {origin_key}...")
    best_times = router.run()
    print(f"computed best times to {len(best_times)} airports")

    # show some stats
    by_stops = {0: 0, 1: 0, 2: 0}
    for code, result in best_times.items():
        by_stops[result.stops] = by_stops.get(result.stops, 0) + 1
    print(f"\nreachability by stops: direct={by_stops[0]}, 1-stop={by_stops[1]}, 2-stop={by_stops[2]}")

    # test some destinations
    test_coords = [
        (151.2, -33.9, 'Sydney'),
        (144.9, -37.8, 'Melbourne'),
        (-157.9, 21.3, 'Honolulu'),
        (174.8, -41.3, 'Wellington NZ'),
        (174.8, -36.9, 'Auckland'),
        (-86.9, 40.4, 'Lafayette IN'),
        (-74.0, 40.7, 'New York'),
        (139.7, 35.7, 'Tokyo'),
        (-0.12, 51.51, 'London'),
    ]

    print("\n" + "=" * 70)
    print("CELL QUERIES")
    print("=" * 70)

    for lng, lat, name in test_coords:
        result = router.query_cell(lng, lat)
        if result:
            if result['stops'] == -1:
                # drive only
                print(f"\n{name}:")
                print(f"  {format_time(result['total_minutes']):>8} | drive | {result['dest_distance_km']:.0f}km from origin")
            else:
                # flight route
                path_str = result['path']
                stop_label = ['direct', '1-stop', '2-stop'][min(result['stops'], 2)]
                print(f"\n{name}:")
                print(f"  {format_time(result['total_minutes']):>8} | {stop_label} | {path_str}")
                print(f"           | ground: {result['ground_from']}m ({result['dest_distance_km']:.0f}km to {result['dest_airport']})")
        else:
            print(f"\n{name}: UNREACHABLE")

    return router


def show_airport_times(router, count=50):
    """show best times to airports"""
    print("\n" + "=" * 70)
    print(f"TOP {count} AIRPORTS BY TRAVEL TIME")
    print("=" * 70)

    sorted_times = sorted(router.best_times.items(), key=lambda x: x[1].total_time)

    for code, result in sorted_times[:count]:
        apt = router.airports.get(code, {})
        name = apt.get('name', '')[:30]
        print(f"  {code:4} {format_time(result.total_time):>8} | {result.stops} stops | {result.path_str()[:40]:40} | {name}")


def export_times(router, filename='data/airport_times.json'):
    """export best times to json"""
    output = {
        'origin': router.origin['name'],
        'airports': {}
    }

    for code, result in router.best_times.items():
        output['airports'][code] = {
            'time': result.total_time,
            'stops': result.stops,
            'path': result.path,
        }

    with open(filename, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nexported {len(output['airports'])} airport times to {filename}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='dijkstra router test')
    parser.add_argument('--origin', default='bristol', choices=list(ORIGINS.keys()))
    parser.add_argument('--export', action='store_true', help='export times to json')
    parser.add_argument('--top', type=int, default=0, help='show top N airports')
    parser.add_argument('--coord', nargs=2, type=float, metavar=('LNG', 'LAT'),
                       help='query specific coordinate')
    args = parser.parse_args()

    routes, airports = load_data()
    print(f"loaded {len(routes)} route origins, {len(airports)} airports")

    router = run_tests(routes, airports, args.origin)

    if args.top:
        show_airport_times(router, args.top)

    if args.coord:
        print(f"\n--- Query: ({args.coord[0]}, {args.coord[1]}) ---")
        result = router.query_cell(args.coord[0], args.coord[1])
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("UNREACHABLE")

    if args.export:
        export_times(router)
