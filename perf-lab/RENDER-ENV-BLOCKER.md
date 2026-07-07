# Render-environment blocker (found 2026-07-06)

The live MapLibre app (isochrone.html) canNOT be reliably rendered/driven via the
playwright-MCP headless chromium ON THE PI:
- headless chromium launches with `--disable-gpu` → WebGL runs in SOFTWARE (llvmpipe).
- the globe + ~100k h3 hex fills peg software-WebGL; the page goes unresponsive to
  MCP `evaluate`/`wait_for`/`screenshot` within the 30s tool-idle timeout → repeated
  "sent no response for 300s" / "Timeout 30000ms" aborts. Observed 4+ times 2026-07-06
  at BOTH high load (2.7) AND low load (0.85) — so it's the software-WebGL cost, not
  system load.
- CONTRAST: the static design-lab tiles (plain inline SVG, no WebGL) render fine in
  the same MCP browser. So the blocker is specifically the WebGL globe.

IMPLICATIONS:
- COLOR FIX (heatmap monotonic + colorScale 1.8, commit 584fd63d) is verified by the
  7 static tiles (same relaxed-green scaling) + code review, NOT by a live-app shot.
- PERF benchmark (this dir's harness) needs a DIFFERENT render env to run:
  options — (a) bump `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` way up + accept slow runs,
  (b) run the harness on a GPU/laptop-class machine (real WebGL), (c) hardware-accel
  the pi's headless chromium if possible (unlikely on the Pi 5 headless).
- Don't keep retrying the pi headless-MCP path — it's a dead end for the globe.

## SOLVED 2026-07-07 — render on the pi via the wayland desktop GPU

The blocker was HEADLESS chromium (software WebGL). The pi HAS a GPU (VideoCore VII)
+ a live wayland desktop (labwc + wayvnc --gpu). Launch a HEADFUL browser on that
display and WebGL is hardware-accelerated → the globe renders fine + fast.

Working recipe (screenshots the live app with real GPU WebGL):
```bash
export WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000
chromium --ozone-platform=wayland --kiosk --window-size=1400,900 --no-first-run \
  --disable-session-crashed-bubble "http://127.0.0.1:8765/isochrone.html" &
CP=$!; sleep 22; grim /tmp/jetspan-render.png; kill "$CP"
```
- `grim` captures the wayland output. sleep ~20s covers tile fetch + grid build.
- Confirmed 2026-07-07: full Europe render, hardware WebGL; verified the colour fix
  (green Europe) + perf fixes (non-cumulative isolines render clean, no world-zoom freeze).
- CAUTION: do NOT `pkill -f` with a pattern that also matches your own shell's command
  line (e.g. "kiosk.*isochrone") — it kills the running shell. Kill by captured PID.
