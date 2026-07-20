# Branch-preview selector + per-branch Pages previews — STATUS

**Branch:** `feat/branch-preview-selector` (PR #1) · **Status: LIVE.** Pages is now served by
GitHub Actions; previews are public. Built + shipped 2026-07-20 by a jetSpan session (jarvis).

## Live URLs (relay to josh)
- **Root (live default = main content):** https://tink3rtanner.github.io/jetSpan/isochrone.html
- **Branch-selector landing:** https://tink3rtanner.github.io/jetSpan/preview/
- **A live preview (has the Branch dropdown):** https://tink3rtanner.github.io/jetSpan/preview/feat-branch-preview-selector/isochrone.html
- **Manifest:** https://tink3rtanner.github.io/jetSpan/preview/previews.json

Other live previews: `/preview/feat-mobile/isochrone.html`, `/preview/feat-vintage-theme/isochrone.html`,
`/preview/feat-click-to-pin-hex/isochrone.html`, `/preview/feat-color-gradient/isochrone.html`.

## What it does
The settings menu has a **Branch** dropdown → navigates to `/preview/<slug>/isochrone.html`
("main (live)" → root). A standalone **`/preview/index.html`** lists every preview. Both are
populated from the data-driven **`/preview/previews.json`** manifest — never hand-maintained.

## The hard constraint — shared data, satisfied (verified LIVE)
`data/` (77MB) is published **once at the site root**. Each preview is **front-end only** (~200KB);
an injected fetch-shim repoints that page's relative `data/…` calls to the shared root copy. Live
headless-browser check on `/preview/feat-branch-preview-selector/`: data loaded through the shim
(4518 airports, isochrone present), **0 data-404s**; the preview's own `data/` path is 404 (nothing
duplicated). No data is ever copied per branch.

**Auto-detect for data-changing branches (new):** a preview now gets its OWN `data/` copy when
EITHER it carries the `.preview-full-data` marker (manual override) OR its `data/` differs from the
base branch (`git diff --quiet` auto-detect). So a data-regenerating branch's preview always shows
ITS data, never main's — no flag to remember. Verified with a throwaway data-mutating branch →
`[FULL-DATA: data-differs]`, own data dir, no shim. All 5 current branches = shared (none touch data).

## Files
| file | what |
|---|---|
| `isochrone.html` | `#branch-select` in the settings panel (hidden until manifest loads) + slug-aware nav JS reading `/preview/previews.json` |
| `scripts/build-preview-site.py` | assembles root (base + shared data) + one preview per non-main branch; auto-detects data-divergent branches for own-data copies; excludes ephemeral `claude/*`; `--data-mode copy` (CI) / `symlink` (local) |
| `.github/workflows/deploy-pages.yml` | **build** job (any branch, validates + uploads artifact) + **deploy** job (github-pages env, publishes). Triggers: push to any branch, branch `delete` (prune), dispatch. Workflow-level `concurrency: pages-deploy, cancel-in-progress:false` → concurrent branch pushes QUEUE, never collide. |

## Go-live changes applied (all done)
1. **Pages flipped to Actions:** `gh api -X PUT repos/tink3rtanner/jetSpan/pages -f build_type=workflow` → `build_type: workflow`.
2. **github-pages env relaxed to ALL branches:** `deployment_branch_policy: null`, `protection_rules: []` (was custom-branch-restricted to main/feat-vintage-theme). So every branch push can deploy — no more deploy-job rejections.
3. **Deploy runs on any-branch push** (already wired; env was the only blocker). Latest run **BOTH jobs green** (build:success, deploy:success).

⚠️ **Gotcha (documented for future):** flipping `build_type` to `workflow` **re-creates the
github-pages environment with the default main-only branch restriction**, silently overwriting an
earlier `null` relax. Fix = relax the env policy AFTER the flip. If a future Pages reconfig ever
re-adds the restriction (deploys start failing "not allowed to deploy … environment protection
rules"), re-run:
```bash
printf '{"deployment_branch_policy":null}' | gh api -X PUT repos/tink3rtanner/jetSpan/environments/github-pages --input -
```

## Verification (actually run, not claimed)
- **CI:** run `29762888685` — build:success **and** deploy:success (both green).
- **Live root** `…/jetSpan/isochrone.html`: 200; headless browser → data loaded (4518 airports, isochrone present), **0 data-404s**.
- **Live preview** `…/preview/feat-branch-preview-selector/isochrone.html`: 200; headless browser → data loaded via shim, **0 data-404s**, Branch dropdown present with 6 options. Preview-local `data/airports.json` → 404 (correctly not duplicated).
- `previews.json`, `/preview/`, `/preview/index.html`, root `/data/airports.json` all 200.

## Gates honored
`main` branch untouched (`origin/main` still `f2e4c183`) · no branches deleted · main's render intact.

## Remaining — josh's call (NOT done, by design)
**Merge PR #1 → main.** Not done (original "don't merge to main" gate wasn't explicitly lifted).
Two effects when you do:
1. The **Branch dropdown appears on the live ROOT** (main's `isochrone.html` gains it). Right now
   the live root is plain main content; the dropdown is visible inside previews only.
2. **Main pushes republish the whole site**, and every new branch cut from main inherits the
   workflow → true "every push publishes" for all future branches.
   (Today only branches that already carry the workflow — i.e. `feat/branch-preview-selector` — self-trigger a deploy; old branches like `feat/mobile` don't have the workflow file, so their own pushes don't publish, but they're still rebuilt whenever any workflow-bearing branch is pushed.)

Rollback (if ever needed): `gh api -X PUT repos/tink3rtanner/jetSpan/pages -f build_type=legacy` restores branch-served Pages from main/.
