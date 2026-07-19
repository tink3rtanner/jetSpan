#!/usr/bin/env python3
"""Headless driver for the interaction performance suite.

Serves nothing itself — point it at an already-running static server
(e.g. `python3 -m http.server 8899` in the repo root), it launches
headless chromium via playwright, injects scripts/interaction-bench.js,
runs the suite, and writes a dated JSON to docs/benchmarks/.

Usage:
    python3 scripts/run-interaction-bench.py --label baseline-main
    python3 scripts/run-interaction-bench.py --url http://localhost:8899/isochrone.html \
        --label pin-feature --compare docs/benchmarks/2026-07-03-interaction-baseline-main-pi.json

Re-runnable: future perf work should run this before/after a change and
commit both JSONs. The in-page suite (interaction-bench.js) is injected,
so this driver works against ANY revision of isochrone.html.
"""
import argparse
import json
import platform
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent


def summarize(run):
    rows = []
    for r in run["results"]:
        if r.get("skipped"):
            rows.append(f"  {r['scenario']:<20} SKIPPED")
            continue
        rows.append(
            f"  {r['scenario']:<20} {r['fps']:>6.1f} fps  avg {r['avgFrameMs']:>6.2f}ms"
            f"  p95 {r['p95FrameMs']:>7.2f}ms  jank {r['jankPct']:>5.1f}%"
            f"  longtasks {r['longTasks']:>3}/{r['longTaskTotalMs']}ms"
        )
    return "\n".join(rows)


def compare(baseline, current):
    base = {r["scenario"]: r for r in baseline["results"] if not r.get("skipped")}
    rows = []
    for r in current["results"]:
        if r.get("skipped") or r["scenario"] not in base:
            continue
        b = base[r["scenario"]]
        dfps = r["fps"] - b["fps"]
        dp95 = r["p95FrameMs"] - b["p95FrameMs"]
        rows.append(
            f"  {r['scenario']:<20} fps {b['fps']:>6.1f} -> {r['fps']:>6.1f} ({dfps:+.1f})"
            f"   p95 {b['p95FrameMs']:>7.2f} -> {r['p95FrameMs']:>7.2f}ms ({dp95:+.2f})"
        )
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8899/isochrone.html")
    ap.add_argument("--label", default="run", help="label for the output filename")
    ap.add_argument("--out", default=None, help="explicit output path (overrides label)")
    ap.add_argument("--compare", default=None, help="baseline JSON to diff against")
    ap.add_argument("--viewport", default="1280x800")
    args = ap.parse_args()

    w, h = (int(x) for x in args.viewport.split("x"))
    bench_js = (REPO / "scripts" / "interaction-bench.js").read_text()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        # wait for full data load (base JSON + route table + airports)
        # NB: the app declares its data globals with `let`, so they are NOT
        # window properties — reference them as bare identifiers.
        page.wait_for_function(
            "() => typeof LOADED_ISOCHRONE !== 'undefined' && LOADED_ISOCHRONE"
            " && LOADED_ROUTE_TABLE && LOADED_AIRPORTS",
            timeout=120000,
        )
        page.wait_for_timeout(2000)  # let initial grid render settle
        # add_script_tag (not evaluate) — evaluate() would invoke the file's
        # completion value (the bench function) immediately with a null arg
        page.add_script_tag(content=bench_js)
        run = page.evaluate("() => runInteractionBench()")
        browser.close()

    if run is None:
        print("FAIL: bench returned null", file=sys.stderr)
        sys.exit(1)

    run["machine"] = platform.node()
    out = Path(args.out) if args.out else (
        REPO / "docs" / "benchmarks" / f"{date.today().isoformat()}-interaction-{args.label}-{platform.node()}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(run, indent=2))

    print(f"\n=== interaction bench [{args.label}] on {platform.node()} ===")
    print(summarize(run))
    try:
        print(f"\nsaved: {out.relative_to(REPO)}")
    except ValueError:  # --out outside the repo
        print(f"\nsaved: {out}")

    if args.compare:
        baseline = json.loads(Path(args.compare).read_text())
        print(f"\n=== diff vs {args.compare} ({baseline['timestamp']}) ===")
        print(compare(baseline, run))


if __name__ == "__main__":
    main()
