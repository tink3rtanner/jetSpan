#!/usr/bin/env python3
"""
crawl-amadeus.py - fetch route data from Amadeus Airport Routes API

requires env vars:
  AMADEUS_API_KEY
  AMADEUS_API_SECRET

outputs:
  - raw/amadeus-checkpoint.json (progress checkpoint)
  - data/routes.json (final route data)

features:
  - checkpoints every 50 airports (resumable)
  - auto token refresh every 25 min
  - rate limiting (0.5s between calls)
  - only crawls large airports (saves API quota)

free tier: 2000 calls/month - enough for ~1200 large airports
"""

import json
import os
import time
import requests
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CHECKPOINT_FILE = REPO_ROOT / "raw" / "amadeus-checkpoint.json"
OUTPUT_FILE = REPO_ROOT / "data" / "routes.json"
AIRPORTS_FILE = REPO_ROOT / "data" / "airports.json"

# api config
API_KEY = os.environ.get("AMADEUS_API_KEY")
API_SECRET = os.environ.get("AMADEUS_API_SECRET")

# test env by default (production requires separate application)
# test data is based on real routes, good enough for v1
USE_PRODUCTION = os.environ.get("AMADEUS_USE_PRODUCTION", "").lower() == "true"
API_BASE = "https://api.amadeus.com" if USE_PRODUCTION else "https://test.api.amadeus.com"
TOKEN_URL = f"{API_BASE}/v1/security/oauth2/token"
ROUTES_URL = f"{API_BASE}/v1/airport/direct-destinations"

# rate limiting
SLEEP_BETWEEN_CALLS = 0.5  # seconds
CHECKPOINT_EVERY = 50  # airports
TOKEN_REFRESH_MINUTES = 25


def get_token():
    """get oauth2 access token"""
    if not API_KEY or not API_SECRET:
        raise ValueError("set AMADEUS_API_KEY and AMADEUS_API_SECRET env vars")

    r = requests.post(TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": API_KEY,
        "client_secret": API_SECRET,
    })

    if r.status_code != 200:
        raise ValueError(f"token request failed: {r.status_code} {r.text}")

    return r.json()["access_token"]


def get_destinations(token, airport_code):
    """get direct destinations from an airport"""
    r = requests.get(ROUTES_URL, params={
        "departureAirportCode": airport_code,
    }, headers={
        "Authorization": f"Bearer {token}",
    })

    if r.status_code == 200:
        data = r.json().get("data", [])
        return [d["iataCode"] for d in data]

    elif r.status_code == 429:  # rate limited
        print(f"  rate limited, waiting 60s...")
        time.sleep(60)
        return get_destinations(token, airport_code)  # retry

    elif r.status_code == 400:  # bad request (invalid airport code)
        return []

    else:
        print(f"  unexpected status {r.status_code}: {r.text[:100]}")
        return []


def load_checkpoint():
    """load checkpoint if exists"""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"routes": {}, "completed": []}


def save_checkpoint(routes, completed):
    """save checkpoint"""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"routes": routes, "completed": completed}, f)


def save_routes(routes):
    """save final routes to data/routes.json"""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(routes, f, separators=(",", ":"))

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"saved to {OUTPUT_FILE} ({size_kb:.1f} KB)")


def main():
    print("=== AMADEUS ROUTE CRAWLER ===\n")

    # load airports (only crawl large airports to save API quota)
    with open(AIRPORTS_FILE) as f:
        all_airports = json.load(f)

    # filter to large airports only
    airports = {k: v for k, v in all_airports.items() if v.get("type") == "large"}
    print(f"crawling {len(airports)} large airports (of {len(all_airports)} total)")

    # load checkpoint
    checkpoint = load_checkpoint()
    routes = checkpoint["routes"]
    completed = set(checkpoint["completed"])
    print(f"checkpoint: {len(completed)} already done\n")

    # get initial token
    print("getting auth token...")
    token = get_token()
    token_time = time.time()
    print("token acquired\n")

    # crawl
    to_crawl = [code for code in airports.keys() if code not in completed]
    total = len(to_crawl) + len(completed)

    for i, code in enumerate(to_crawl):
        # refresh token if needed
        if time.time() - token_time > TOKEN_REFRESH_MINUTES * 60:
            print("refreshing token...")
            token = get_token()
            token_time = time.time()

        # fetch destinations
        dests = get_destinations(token, code)
        routes[code] = dests
        completed.add(code)

        progress = len(completed)
        print(f"[{progress}/{total}] {code}: {len(dests)} destinations")

        # checkpoint
        if progress % CHECKPOINT_EVERY == 0:
            print(f"  checkpointing...")
            save_checkpoint(routes, list(completed))

        time.sleep(SLEEP_BETWEEN_CALLS)

    # final save
    save_checkpoint(routes, list(completed))
    save_routes(routes)

    # summary
    total_routes = sum(len(d) for d in routes.values())
    airports_with_routes = sum(1 for d in routes.values() if d)
    print(f"\ndone: {len(routes)} airports, {total_routes} route pairs")
    print(f"airports with routes: {airports_with_routes}")


if __name__ == "__main__":
    main()
