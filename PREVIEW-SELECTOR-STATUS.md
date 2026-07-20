# Branch-preview selector + per-branch Pages previews — build status

**Branch:** `feat/branch-preview-selector` (pushed to origin) · **Status: DONE, awaiting the one gated flip (josh's call).**
Built 2026-07-20 by a dedicated jetSpan session spawned by jarvis.

## What it does (josh's intent)
Live default stays `main` at the root URL, untouched. The settings menu gets a **Branch**
dropdown; picking a branch navigates to that branch's preview at `/preview/<slug>/isochrone.html`
(and "main (live)" navigates back to root). A standalone **`/preview/index.html`** landing page
lists every preview. Both the dropdown and the landing page are populated from a data-driven
`/preview/previews.json` manifest — the branch list is never hand-maintained.

## THE hard constraint — shared data, satisfied
`data/` is **77MB**. It is published **once, at the site root**. Each `/preview/<slug>/` is
**front-end only** (~200KB). A tiny **fetch-shim**, injected into every preview HTML at deploy
time, rewrites that page's relative `data/…` fetches to climb back to the shared root copy
(`../../data/…`). So a preview adds front-end weight only — **no data is ever duplicated per
branch**. Verified: a preview loads all data with **zero 404s**; the preview's own `data/` path
is 404 (nothing there); published total = **103MB** for 5 previews (77MB data + front-ends),
comfortably under the 1GB Pages cap even at a dozen+ branches.

Opt-in exception for a branch that *regenerates* data: drop a `.preview-full-data` marker file
in that branch's root and it gets its own `data/` copy (no shim). Default = shared.

## Files
| file | what |
|---|---|
| `isochrone.html` | new `#branch-select` in the settings panel (a "Preview branch" section, `theme-select` styling, hidden until the manifest loads) + slug-aware nav JS reading `/preview/previews.json` |
| `scripts/build-preview-site.py` | assembles the whole site: root (base branch + shared data) + one front-end-only preview per non-main branch + `previews.json` + `preview/index.html`. Read-only (`git archive`), never touches the working tree. `--data-mode copy` (CI) / `symlink` (fast local test). Excludes ephemeral `claude/*` session branches. |
| `.github/workflows/deploy-pages.yml` | **build** job (any branch: assembles + uploads artifact, validates in CI, no env gate) + **deploy** job (github-pages env, publishes). Triggers: push to any branch, branch `delete` (prune), manual dispatch. |

Slugs: branch names contain `/` (`feat/mobile`), so previews are keyed by a URL-safe slug
(`feat-mobile`); the manifest carries both `{branch, slug}` for display + navigation.

Whole-site rebuild model: every run rebuilds the entire site from the branches that currently
exist — so a deleted branch's preview is **auto-pruned** (it's just absent next build), and a
main push (or dispatch) refreshes **all** previews at once.

## How it was tested
- **Local assembled site served on http.server**, both `--data-mode symlink` and `copy` (CI path).
- **Headless-chromium (playwright) load tests**, tracking every network response:
  - root `isochrone.html`: data loaded (4518 airports, isochrone present), **0 data 404s**.
  - preview `isochrone.html`: data loaded **through the shim from shared root**, **0 data 404s**, dropdown present with 7 options (main + 6 previews).
  - `/preview/index.html`: 7 cards rendered.
  - dropdown **navigation fires** (switching to `feat-mobile` → `/preview/feat-mobile/isochrone.html`). Old branches without the dropdown still load fine and are reachable via the index page.
- **Real GitHub CI**: the `build` job **succeeded** (assembled root + 5 previews + manifest, artifact uploaded) — run `29760357761`. The `deploy` job was correctly **rejected by github-pages environment protection** on the feature branch → the live site is untouched, exactly as intended pre-authorization.

## Hard gates honored
`main` untouched · Pages source **not** flipped · no branches deleted · `.claude/` not committed.

---

## THE ONE GATED STEP — josh's call, jarvis relays

The live site still serves the **legacy** source (confirmed: `build_type: legacy`, `source main /`).
Nothing published changes until josh authorizes the flip. To go live:

**1. Merge `feat/branch-preview-selector` → main** (brings the workflow + the dropdown onto the
   default branch — required, since Actions runs the workflow version on `main` and the env
   protection only lets the default branch deploy). A PR is open for review.

**2. Flip Pages to Actions publishing:**
```bash
gh api -X PUT repos/tink3rtanner/jetSpan/pages -f build_type=workflow
```

**3. Trigger the first Actions publish from main:**
```bash
gh workflow run deploy-pages.yml --ref main
```
(The merge push in step 1 will also trigger it; this is belt-and-suspenders. The deploy job now
passes env protection because main is the default branch.)

After that, `https://tink3rtanner.github.io/jetSpan/` is served by the assembled artifact:
main at root (with the Branch dropdown), every branch at `/preview/<slug>/`, landing page at
`/preview/index.html`. Rollback = `gh api -X PUT repos/tink3rtanner/jetSpan/pages -f build_type=legacy`.

## Notes / trade-offs for josh
- After the flip, **feature-branch pushes build+validate but don't publish** (env protection =
  default-branch-only). Previews refresh on **main pushes or manual `workflow run --ref main`**.
  If you want every feature-branch push to auto-publish its own preview, relax the `github-pages`
  environment's deployment-branch rule in repo Settings → Environments. Default (main-only) is
  the safer choice and is what's wired now.
- Old feature branches (`feat/mobile`, etc.) predate the dropdown, so their preview pages have no
  in-page switcher — you navigate them via `/preview/index.html`. New branches cut from main
  after the merge inherit the dropdown automatically.
