#!/usr/bin/env python3
"""
build-preview-site.py — assemble the full GitHub-Pages site into an output dir.

Layout produced:
    <out>/                       <- base branch (main) front-end + FULL data/ (77MB)
    <out>/preview/<slug>/        <- each non-main branch's FRONT-END ONLY
    <out>/preview/previews.json  <- manifest [{branch, slug, updated, commit, full}]
    <out>/preview/index.html     <- data-driven branch-selector landing page

THE HARD CONSTRAINT — share data, never duplicate it.
    data/ (77MB) is copied ONCE, at the site root. Each preview is front-end only
    (isochrone.html + friends, ~200KB). A fetch-shim injected into every preview
    HTML rewrites its relative `data/...` fetches to climb back to the shared root
    copy (`../../data/...`), so a preview loads root data with ZERO duplication and
    ZERO 404s — regardless of whether that branch knows anything about previews.

    Opt-in exception: a branch containing a `.preview-full-data` marker file gets
    its own data/ copy (for branches that regenerate data). Default = shared.

Everything is done via `git archive` (read-only) so the working tree / current
branch is never touched. Safe to run from any branch.

Usage:
    python3 scripts/build-preview-site.py --output _site
    python3 scripts/build-preview-site.py --output _site --base-branch main \
        --data-mode copy            # CI: real data copy (Pages artifact needs files)
    python3 scripts/build-preview-site.py --output /tmp/site \
        --base-branch feat/branch-preview-selector --data-mode symlink  # fast local test
"""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

FULL_DATA_MARKER = ".preview-full-data"   # opt-in per-branch: give this branch its own data/
DATA_DIR = "data"                          # the 77MB payload — shared, never duplicated

# fetch-shim injected into every preview HTML: repoints relative data/ fetches
# to the shared root copy two levels up (out of /preview/<slug>/).
FETCH_SHIM = """<script>
/* jetSpan preview data-sharing shim (injected at deploy time).
   This page lives at <root>/preview/<slug>/ but the 77MB data/ payload is NOT
   duplicated here — it lives at the site root. Rewrite any relative data/ fetch
   to climb back two levels to the shared copy, so previews add front-end weight
   only. Leaves absolute URLs and CDN requests untouched. */
(function () {
  var _fetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      if (typeof input === "string" && /^(\\.\\/)?data\\//.test(input)) {
        input = "../../" + input.replace(/^\\.\\//, "");
      }
    } catch (e) {}
    return _fetch.call(this, input, init);
  };
})();
</script>
"""


def git(*args):
    """Run a git command, return stdout (text)."""
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def slugify(branch):
    """URL-/filesystem-safe single path segment for a branch name."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", branch)


def list_branches(base_branch):
    """All deployable branches minus the base. Prefers remote-tracking refs (CI),
    falls back to / merges local branches so it works both in CI and on a laptop."""
    names = set()
    for ref_glob, strip in (("refs/remotes/origin/*", "origin/"),
                             ("refs/heads/*", "")):
        out = git("for-each-ref", "--format=%(refname:short)", ref_glob)
        for line in out.splitlines():
            n = line.strip()
            if not n or n.endswith("/HEAD") or n == "origin":
                continue
            if strip and n.startswith(strip):
                n = n[len(strip):]
            if n in (base_branch, "HEAD", "gh-pages"):
                continue
            names.add(n)
    return sorted(names)


def branch_has_marker(ref):
    """True if the branch's tree contains the full-data opt-in marker."""
    r = subprocess.run(["git", "cat-file", "-e", f"{ref}:{FULL_DATA_MARKER}"],
                       capture_output=True)
    return r.returncode == 0


def top_level_entries(ref):
    """Top-level tracked names in the branch tree."""
    return [l.strip() for l in git("ls-tree", "--name-only", ref).splitlines() if l.strip()]


def archive_extract(ref, dest, paths):
    """git archive <ref> -- <paths...> | extract into dest. paths=None => whole tree."""
    os.makedirs(dest, exist_ok=True)
    cmd = ["git", "archive", "--format=tar", ref]
    if paths is not None:
        cmd += ["--", *paths]
    proc = subprocess.run(cmd, check=True, capture_output=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tf:
        tf.extractall(dest)


def resolve_ref(branch):
    """Pick a git ref that exists for a branch name (local or remote-tracking)."""
    for candidate in (branch, f"origin/{branch}"):
        if subprocess.run(["git", "rev-parse", "--verify", "--quiet", candidate],
                          capture_output=True).returncode == 0:
            return candidate
    raise SystemExit(f"cannot resolve ref for branch {branch!r}")


def inject_shim(preview_dir):
    """Insert the data-sharing shim right after <head> in every .html in a preview."""
    for root, _dirs, files in os.walk(preview_dir):
        for fn in files:
            if not fn.endswith(".html"):
                continue
            path = os.path.join(root, fn)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
            if "jetSpan preview data-sharing shim" in html:
                continue  # idempotent
            # insert right after the opening <head ...> tag; fall back to <html>/top
            m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
            if m:
                html = html[:m.end()] + "\n" + FETCH_SHIM + html[m.end():]
            else:
                html = FETCH_SHIM + html
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)


def build_root(out, base_branch, data_mode):
    """Assemble the site root from the base branch, incl the shared data/ payload."""
    base_ref = resolve_ref(base_branch)
    if data_mode == "symlink":
        # front-end only, then symlink data -> repo copy (fast local iteration)
        paths = [e for e in top_level_entries(base_ref) if e != DATA_DIR]
        archive_extract(base_ref, out, paths)
        repo_data = os.path.abspath(DATA_DIR)
        link = os.path.join(out, DATA_DIR)
        if os.path.lexists(link):
            (shutil.rmtree if os.path.isdir(link) and not os.path.islink(link) else os.remove)(link)
        os.symlink(repo_data, link)
        print(f"  root: {base_branch} front-end + data symlink -> {repo_data}")
    else:
        # full archive incl data/ (CI: Pages artifact needs real files)
        archive_extract(base_ref, out, None)
        print(f"  root: {base_branch} full tree (incl data/) copied")


def build_preview(out, branch, data_mode):
    """Assemble one branch's front-end (shared-data) into preview/<slug>/."""
    ref = resolve_ref(branch)
    slug = slugify(branch)
    dest = os.path.join(out, "preview", slug)
    full = branch_has_marker(ref)
    entries = top_level_entries(ref)
    paths = None if full else [e for e in entries if e != DATA_DIR]
    archive_extract(ref, dest, paths)
    if not full:
        inject_shim(dest)  # only shared-data previews need the data repoint
    updated, commit = git("log", "-1", "--format=%cI%n%H", ref).splitlines()[:2]
    tag = " [FULL-DATA]" if full else ""
    print(f"  preview/{slug}: {branch}{tag} ({'full' if full else 'front-end only'})")
    return {"branch": branch, "slug": slug, "updated": updated,
            "commit": commit[:12], "full": full}


def write_manifest(out, previews):
    path = os.path.join(out, "preview", "previews.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(previews, f, indent=2)
    print(f"  manifest: {len(previews)} preview(s) -> preview/previews.json")


def write_index(out, base_branch):
    """Write the standalone branch-selector landing page (reads previews.json)."""
    path = os.path.join(out, "preview", "index.html")
    with open(path, "w") as f:
        f.write(INDEX_HTML.replace("__BASE_BRANCH__", base_branch))
    print("  index: preview/index.html")


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>jetSpan · branch previews</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #12140f; color: #e8e4d8; padding: 40px 20px; }
  .wrap { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 22px; font-weight: 600; margin: 0 0 4px; letter-spacing: .3px; }
  .sub { color: #8a8778; font-size: 13px; margin: 0 0 28px; }
  a { color: inherit; text-decoration: none; }
  .card { display: flex; align-items: center; justify-content: space-between; gap: 16px;
          border: 1px solid #2c2e26; border-radius: 10px; padding: 14px 18px; margin-bottom: 10px;
          background: #191b14; transition: border-color .15s, background .15s; }
  .card:hover { border-color: #6b7a3a; background: #1e2016; }
  .card.live { border-color: #4a5a28; }
  .name { font-weight: 600; font-size: 15px; }
  .meta { color: #8a8778; font-size: 12px; margin-top: 2px; }
  .badge { font-size: 10px; text-transform: uppercase; letter-spacing: .5px; color: #b7c47a;
           border: 1px solid #4a5a28; border-radius: 999px; padding: 2px 8px; }
  .go { color: #8a8778; font-size: 18px; }
  .empty { color: #8a8778; padding: 24px; text-align: center; border: 1px dashed #2c2e26; border-radius: 10px; }
  .foot { color: #55564c; font-size: 12px; margin-top: 28px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>jetSpan · branch previews</h1>
  <p class="sub">Each preview is a front-end-only deploy sharing the live data. Pick a build to open it.</p>
  <div id="list"></div>
  <p class="foot">Live default is <strong>__BASE_BRANCH__</strong>. Previews auto-deploy on push and prune on branch delete.</p>
</div>
<script>
// climb to the site root from /preview/index.html, then read the manifest.
function siteRoot() { return window.location.pathname.replace(/preview\\/[^/]*$/, ""); }
function fmt(iso) { try { return new Date(iso).toLocaleString("en-GB", {day:"numeric",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}); } catch (e) { return iso || ""; } }
(async function () {
  const root = siteRoot();
  const list = document.getElementById("list");
  // main / live is always offered first
  let html = '<a class="card live" href="' + root + 'isochrone.html">'
    + '<div><div class="name">main <span class="badge">live</span></div>'
    + '<div class="meta">the published default build</div></div><div class="go">&rsaquo;</div></a>';
  let previews = [];
  try {
    const res = await fetch(root + "preview/previews.json", {cache: "no-cache"});
    if (res.ok) { const m = await res.json(); previews = Array.isArray(m) ? m : (m.previews || []); }
  } catch (e) {}
  previews.sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
  for (const p of previews) {
    html += '<a class="card" href="' + root + 'preview/' + encodeURIComponent(p.slug) + '/isochrone.html">'
      + '<div><div class="name">' + p.branch + (p.full ? ' <span class="badge">full data</span>' : '') + '</div>'
      + '<div class="meta">' + fmt(p.updated) + (p.commit ? ' · ' + p.commit : '') + '</div></div>'
      + '<div class="go">&rsaquo;</div></a>';
  }
  if (!previews.length) html += '<div class="empty">No branch previews yet. Push a non-main branch to create one.</div>';
  list.innerHTML = html;
})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Assemble the jetSpan Pages site (root + previews).")
    ap.add_argument("--output", required=True, help="output directory (wiped and rebuilt)")
    ap.add_argument("--base-branch", default="main", help="branch served at the root (default: main)")
    ap.add_argument("--branches", default="", help="comma list of preview branches (default: auto-detect all non-base)")
    ap.add_argument("--data-mode", choices=["copy", "symlink"], default="copy",
                    help="copy = real data files (CI/Pages); symlink = fast local test")
    args = ap.parse_args()

    out = os.path.abspath(args.output)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    print(f"building site -> {out}  (base={args.base_branch}, data-mode={args.data_mode})")
    build_root(out, args.base_branch, args.data_mode)

    branches = ([b.strip() for b in args.branches.split(",") if b.strip()]
                if args.branches else list_branches(args.base_branch))
    previews = []
    for b in branches:
        try:
            previews.append(build_preview(out, b, args.data_mode))
        except subprocess.CalledProcessError as e:
            print(f"  !! skipped {b}: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)

    write_manifest(out, previews)
    write_index(out, args.base_branch)
    print(f"done: {len(previews)} preview(s) + root.")


if __name__ == "__main__":
    main()
