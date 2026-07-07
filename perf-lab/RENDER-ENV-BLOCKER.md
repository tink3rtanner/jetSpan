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
