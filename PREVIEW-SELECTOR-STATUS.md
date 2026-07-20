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

---

## task 2 — has-PR filter + branch maintenance + stale-feature refresh (2026-07-20, jetSpan session)

Three-part maintenance pass. All verified live, not claimed.

### 1. Preview filter → HAS-PR (done, verified live)
**Old bug:** `build-preview-site.py` excluded all `claude/*` but not `codex/*` → asymmetric; josh's two parallel hole-fix branches couldn't show side-by-side.
**New rule:** a branch shows iff it has an **OPEN PR (any prefix)** OR is a **`feat/*` branch ahead of main**. Everything else (ephemeral worktrees, merged/settled branches) is excluded.
- Implemented in `list_branches()` via `open_pr_branches()` (`gh pr list --repo tink3rtanner/jetSpan --state open --json headRefName`). Degrades gracefully — no gh/auth/net → `feat/*`-ahead only.
- **CI token fix (was the live blocker):** the workflow gave `gh` no token, so in Actions the call failed and the filter silently degraded to feat-ahead-only — dropping nifty. Added `pull-requests: read` permission + `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` on the build step. Latest CI log: `open PRs (gh ok): [nifty, codex/performance-bench, feat/mobile]`.
- **Proof (live `previews.json`):** now lists `claude/nifty-montalcini-150823` (has-PR, full-data), `codex/performance-bench` (has-PR), `feat/mobile` (has-PR). A `claude/*` with no PR was tested locally → correctly excluded. Symmetric claude/codex handling confirmed (codex PR #3 shows too).
- Live: https://tink3rtanner.github.io/jetSpan/preview/previews.json · nifty preview 200 at `/preview/claude-nifty-montalcini-150823/isochrone.html` · root still 200.

### 2. Branch maintenance (done)
Re-confirmed `git log main..origin/<b>` empty at delete time before removing:
- **Deleted** `feat/vintage-theme` (0 unique, merged) + `feat/click-to-pin-hex` (0 unique, merged).
- **Kept** `feat/branch-preview-selector` (merged <1 day — josh's >1-day buffer).
- Untouched: nifty, codex/performance-bench.

### 3. Stale-feature refresh (both rebased onto current main; conflicts resolved)

**`feat/mobile` — REFRESHED + PR'd → still relevant.** PR **#4**.
- Rebased its 1 commit (was 28 behind) onto current main. 2 conflicts, both "both-sides-inserted-at-same-anchor," resolved by keeping both: (a) CSS — main's vintage-theme block + mobile's media queries (added one `}` git had folded onto the shared closer); (b) JS — main's click-to-pin system + mobile's `closeTooltip()`.
- Relevance: layout/touch is orthogonal to the color rewrite. All selectors it targets still exist; `route-line` source, tap handler, close button, legend-expand all wire cleanly.
- Known gap (noted in PR): the collapsed mobile legend strip is a **static** CSS gradient — re-pointed from the retired modern palette to the vintage **hypso** default, but does not yet live-sync to the active `VINTAGE_PALETTES` selection (follow-up).
- Verified: headless load → 0 page errors, `closeTooltip`+`togglePin` defined, `hexgrid`+`pinned-cells` sources created, 127k isochrone cells + hypso palette loaded. Live preview 200: https://tink3rtanner.github.io/jetSpan/preview/feat-mobile/isochrone.html
- **josh (2026-07-20): "not convinced mobile support is great, needs more work, will test later"** → PR #4 left OPEN for his review, not merged.

**`feat/color-gradient` — SUPERSEDED → DROPPED (no PR).** Deleted per josh ("delete the dropped ones, archive whatever"); commit preserved as tag **`archive/feat-color-gradient`** (dd3692de).
- The rebase surfaced the verdict: its controls (`toggle-smooth`, `color-focus` gamma slider, `gamma-auto-btn`) wire to DOM that main's vintage overhaul **removed**, and its smooth ramp was anchored on a single hardcoded band palette that no longer exists.
- Main already delivers both of its goals, better: **6 selectable ordered palettes** (Heat/Sepia/Viridis/Verdigris/Hypsometric/Galton) cover "better color ramp"; the **`colorScale` slider** (1–4×, band-threshold redistribution) covers the gamma "color focus: near/far" value-prop.
- Its only unique remainder — *continuous* non-banded interpolation — directly contradicts main's deliberate **discrete-band engraved-plate** aesthetic (the whole vintage direction). Refreshing = a re-design, not a rebase. Recoverable from the archive tag if the gamma-focus idea is ever wanted as a fresh feature on the vintage palettes.

### Final state
- **origin branches:** main, `feat/branch-preview-selector` (held), `feat/mobile` (PR #4), `claude/nifty-montalcini-150823` (PR #2), `codex/performance-bench` (PR #3).
- **Deleted:** feat/vintage-theme, feat/click-to-pin-hex, feat/color-gradient (→ tag `archive/feat-color-gradient`).
- **Open PRs in the selector:** #2 nifty, #3 codex/performance-bench, #4 feat/mobile — all live-previewable.
- Gates honored: main render intact (root 200), protected branches (branch-preview-selector/mobile/nifty) kept, nifty/codex contents untouched, `.claude/` still gitignored.
