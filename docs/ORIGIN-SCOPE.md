# Origin Scope: Bristol-Only (for now)

The UI currently hardcodes Bristol, UK as the sole origin. The origin picker dropdown has been removed. This is a deliberate scoping decision — precomputing isochrone data is expensive and multi-origin support isn't worth the complexity yet.

## What's hardcoded

### Frontend (`isochrone.html`)
- `currentOrigin = 'bristol'` — never changes, no UI to change it
- Title panel says "from Bristol, UK" — no dropdown
- `ORIGINS` dict still defines london/newyork/paris/tokyo/sydney (kept for future use)
- `loadIsochroneData(currentOrigin)` only ever loads `data/isochrones/bristol.json`
- Origin-select event listener removed entirely

### Backend (`scripts/`)
- `dijkstra_router.py` — `ORIGINS` dict has multiple cities but only bristol has been run
- `precompute-isochrone.py` — supports `--all` flag but only `bristol.json` exists in `data/isochrones/`
- Ground time data (`data/ground/`) — all 8 regions complete (1201 airports), needs recompute to integrate

### Data (`data/isochrones/`)
- Only `bristol.json` exists (8.7 MB, 143k cells, res 1-4)
- Each origin would need its own JSON file (~8-9 MB each)
- GitHub Pages constraint: total repo should stay reasonable

## To add more origins later

1. Add origin to `ORIGINS` in `dijkstra_router.py` (airports, ground times)
2. Run `python scripts/precompute-isochrone.py <origin_key>`
3. Commit `data/isochrones/<origin>.json`
4. Re-add origin dropdown in `isochrone.html` (restore select element + event listener)
5. Ground data now covers all regions globally — no per-origin ground compute needed
6. File size: each origin is ~8-9 MB, so 5 origins = ~45 MB of isochrone JSON. May need to split by resolution or lazy-load.
