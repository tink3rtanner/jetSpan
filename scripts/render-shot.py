#!/usr/bin/env python3
"""
render-shot.py — headless render harness for jetspan isochrone.html.

Serves the repo on :8765, loads isochrone.html in headless chromium via
playwright, sets the palette + camera, waits for tiles + hex data to settle,
and screenshots. Used to iterate the vintage-wash style visually without a
human in the loop.

Usage:
  python3 scripts/render-shot.py --palette heatmap --view close --out /tmp/shot.png
  python3 scripts/render-shot.py --palette heatmap --view far   --out /tmp/shot.png
  python3 scripts/render-shot.py --palette heatmap --linestyle contours --view close --out /tmp/shot.png

Views (center/zoom tuned for the Bristol-origin isochrone over Europe):
  close = zoomed on UK/W-Europe (see the band texture + border conflict)
  far   = whole-Europe/N-Africa (see the overall wash gradient)

Notes:
- one browser at a time (doctor's pi-thrash rule). This script opens + closes a
  single chromium per invocation.
- waits on network-idle + a fixed settle for MapLibre tile + h3 fill paint.
- palette is applied by driving the #palette-select dropdown post-load.
"""
import argparse, subprocess, time, sys, os, signal, socket

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8765

# camera presets: [lng, lat, zoom]
VIEWS = {
    "close": [-2.6, 51.4, 4.2],   # Bristol origin, W-Europe — band texture + borders
    "far":   [10.0, 47.0, 2.9],   # whole Europe/Med — overall wash gradient
}

def port_open(p):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", p)) == 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--palette", default="heatmap")
    ap.add_argument("--linestyle", default=None,
                    help="engraved line style: washes|contours|layered (default: app's persisted/default)")
    ap.add_argument("--view", default="close", choices=list(VIEWS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--settle", type=float, default=6.0, help="seconds to wait after camera set")
    args = ap.parse_args()

    lng, lat, zoom = VIEWS[args.view]

    # start server only if not already up
    srv = None
    if not port_open(PORT):
        srv = subprocess.Popen(["python3", "-m", "http.server", str(PORT)],
                               cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            if port_open(PORT):
                break
            time.sleep(0.2)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed; run: pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(2)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            page = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
            page.goto(f"http://127.0.0.1:{PORT}/isochrone.html", wait_until="networkidle", timeout=60000)
            # give the map object time to init
            page.wait_for_timeout(3000)
            # drive a <select> by JS value + change event. The controls panel
            # can be collapsed (selects hidden), which makes playwright's
            # select_option wait forever on visibility — the app only listens
            # for 'change', so a synthetic dispatch is equivalent.
            def set_select(sel_id, value):
                return page.evaluate(
                    """([id, v]) => {
                        const el = document.getElementById(id);
                        if (!el) return 'missing:' + id;
                        el.value = v;
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        return el.value;
                    }""",
                    [sel_id, value],
                )
            got = set_select("palette-select", args.palette)
            if got != args.palette:
                print(f"WARNING: palette select -> {got!r} (wanted {args.palette!r})", file=sys.stderr)
            # verify the app actually took the line style — a silent no-op
            # means blind renders
            if args.linestyle:
                got = set_select("linestyle-select", args.linestyle)
                page.wait_for_timeout(1000)  # paint-prop settle
                applied = page.evaluate(
                    "() => (typeof currentLineStyle !== 'undefined') ? currentLineStyle : null")
                if applied != args.linestyle:
                    print(f"WARNING: linestyle did not apply (app has {applied!r}, wanted {args.linestyle!r})",
                          file=sys.stderr)
            # jump camera
            page.evaluate(
                """([lng, lat, zoom]) => {
                    if (window.map) { window.map.jumpTo({center: [lng, lat], zoom: zoom}); }
                }""",
                [lng, lat, zoom],
            )
            page.wait_for_timeout(int(args.settle * 1000))
            page.screenshot(path=args.out)
            browser.close()
        print(f"wrote {args.out}")
    finally:
        if srv:
            srv.send_signal(signal.SIGTERM)

if __name__ == "__main__":
    main()
