#!/usr/bin/env python3
"""
osrm-rate-test.py - probe the demo OSRM API to find actual rate limits

strategy: start fast, back off when we hit 429s, find the sweet spot
"""

import json
import subprocess
import time
from collections import deque

# test location: bristol airport and some nearby cells
TEST_ORIGIN = "-2.7190,51.3827"  # BRS
TEST_DESTS = [
    "-2.5879,51.4545",  # bristol city
    "-2.3520,51.3815",  # bath
    "-3.1791,51.4816",  # cardiff
    "-1.8904,51.4082",  # swindon
    "-2.9685,51.4514",  # newport
]

URL_TEMPLATE = "https://router.project-osrm.org/table/v1/driving/{origin};{dests}?sources=0"


def make_request():
    """single OSRM request, returns (success, response_time_ms, status)"""
    dests = ";".join(TEST_DESTS)
    url = URL_TEMPLATE.format(origin=TEST_ORIGIN, dests=dests)

    start = time.time()
    result = subprocess.run(
        ["curl", "-s", "-w", "\n%{http_code}", "--max-time", "30", url],
        capture_output=True, text=True
    )
    elapsed_ms = (time.time() - start) * 1000

    if result.returncode != 0:
        return False, elapsed_ms, "curl_error"

    lines = result.stdout.strip().split("\n")
    status_code = lines[-1] if lines else "?"
    body = "\n".join(lines[:-1])

    try:
        data = json.loads(body)
        if data.get("code") == "Ok":
            return True, elapsed_ms, status_code
        else:
            return False, elapsed_ms, data.get("code", status_code)
    except json.JSONDecodeError:
        return False, elapsed_ms, f"json_error_{status_code}"


def run_burst_test(count, delay_sec):
    """fire off N requests with fixed delay, measure success rate"""
    successes = 0
    total_ms = 0
    errors = []

    print(f"\n--- burst test: {count} requests @ {delay_sec}s delay ---")

    for i in range(count):
        ok, ms, status = make_request()
        total_ms += ms

        if ok:
            successes += 1
            marker = "."
        else:
            marker = "X"
            errors.append(status)

        print(marker, end="", flush=True)

        if i < count - 1:  # don't sleep after last
            time.sleep(delay_sec)

    print()
    rate = successes / count * 100
    avg_ms = total_ms / count
    print(f"  {successes}/{count} ok ({rate:.0f}%), avg latency: {avg_ms:.0f}ms")
    if errors:
        print(f"  errors: {errors[:5]}{'...' if len(errors) > 5 else ''}")

    return successes, count


def find_sustainable_rate():
    """binary search for max sustainable rate"""
    print("=== OSRM RATE LIMIT TEST ===\n")
    print("probing demo server at router.project-osrm.org")
    print("goal: find max req/sec that doesn't trigger 429s\n")

    # first: verify connectivity with a slow test
    print("warmup: single request...")
    ok, ms, status = make_request()
    if not ok:
        print(f"FAILED: {status}. server down or blocked?")
        return None
    print(f"ok ({ms:.0f}ms)\n")

    # test various delays
    # starting conservative and working up
    test_delays = [
        (0.1, 10),   # 10 req/sec - probably too fast
        (0.25, 20),  # 4 req/sec
        (0.5, 20),   # 2 req/sec
        (0.75, 20),  # 1.3 req/sec
        (1.0, 15),   # 1 req/sec
        (1.5, 10),   # current setting
        (2.0, 10),   # conservative
    ]

    results = {}

    for delay, count in test_delays:
        successes, total = run_burst_test(count, delay)
        results[delay] = successes / total

        # if we got rate limited, back off briefly before next test
        if successes < total:
            print("  (backing off 10s before next test...)")
            time.sleep(10)
        else:
            time.sleep(2)  # brief pause between tests

    # report
    print("\n=== RESULTS ===")
    print(f"{'delay':>8} | {'rate':>10} | {'success':>8}")
    print("-" * 35)

    best_delay = None
    for delay in sorted(results.keys()):
        rate = 1 / delay
        success_pct = results[delay] * 100
        star = " <-- BEST" if success_pct >= 90 and (best_delay is None or delay < best_delay) else ""
        if success_pct >= 90:
            best_delay = delay
        print(f"{delay:>7.2f}s | {rate:>8.1f}/s | {success_pct:>6.0f}%{star}")

    if best_delay:
        print(f"\nRECOMMENDED: {best_delay}s delay ({1/best_delay:.1f} req/sec)")
        print(f"at 100 dests/batch: {3600/best_delay*100:.0f} cells/hour")
    else:
        print("\nall delays had issues - server may be rate limiting aggressively")

    return best_delay


if __name__ == "__main__":
    find_sustainable_rate()
