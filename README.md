# JetSpan

Interactive visualizations exploring how air travel "warps" geography - places connected by direct flights cluster together in travel-time space while poorly connected places stretch apart.

## Running

Open any HTML file directly in a browser, or serve locally:

```bash
python -m http.server 8765
# Then visit http://localhost:8765
```

## What's Built

### `index.html` - The Shrinking World

Main interactive visualization centered on London. Features:

- **Morph View**: Slider smoothly transitions cities between geographic positions and time-warped positions (distance = flight hours, bearing preserved)
- **Split View**: Side-by-side comparison of geographic vs time-space
- **Compare View**: Multiple origin cities shown simultaneously
- Uses D3.js with Natural Earth projection
- ~50 world cities with flight times from London

### `panels.html` - Nine Visualization Approaches

A 3x3 grid exploring different ways to show time-space relationships:

1. Geographic Baseline - Standard map reference
2. Radial Time-Space - Direction preserved, distance = hours
3. Warped Coastlines - Geography distorted by travel time
4. Shrivelled Map - L'Hostis-style peaks and valleys (2D side view)
5. Topological Metro - Cities as metro-map nodes
6. Split Comparison - Geo vs time side-by-side
7. Proportional Symbols - Bubble size = travel time
8. Animated Morph - Auto-playing transition
9. Layered Rings - Concentric hour bands

### `lhostis.html` - 3D Shrivelled Map

Three.js 3D visualization of the USA demonstrating L'Hostis "shrivelled map" concept:

- Terrain mesh bounded by US outline
- Airports sit at peaks (fast air travel keeps them "high")
- Valleys sag between cities (slow ground travel)
- Interactive controls: drag to rotate, scroll to zoom
- Slider adjusts shrivel intensity (0-2x)
- Toggle for air route visibility
- Color gradient: yellow (peaks) → green → blue/teal (valleys)

Uses Delaunay triangulation (Delaunator library) to create interior mesh vertices filtered to US boundary.

## Specs & Future Work

- `spec.md` - Original exploration document with 6 prototype concepts
- `flight-isochrone-spec.md` - Spec for future isochrone map feature (not yet built)

### Known Issues / Improvements

The plan file at `~/.claude/plans/tingly-wondering-pelican.md` documents proposed improvements to `index.html` warping:

- Fix bearing calculation (use screen-space instead of spherical bearing)
- Add isochrone rings at key time intervals
- Fade geography during warp transition
- Improve interpolation (polar coordinates)

## Dependencies

All loaded via CDN, no build step required:

- D3.js v7 (index.html, panels.html)
- TopoJSON client (index.html, panels.html)
- Three.js r128 (lhostis.html)
- Delaunator 5.0 (lhostis.html)
