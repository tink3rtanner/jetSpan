#!/usr/bin/env node
// bench-node.js — CPU-bound micro-benchmark of jetspan's hot functions.
// WHY node not browser: the live MapLibre app renders WebGL in software on the pi
// and blocks the main thread hard enough to wedge headless chromium (needs sudo
// kill -9). The REAL bottlenecks (grid smoothing + contour dissolve + recolor) are
// pure JS + h3-js — hardware-independent (CPU), so we measure them faithfully here.
// FPS/paint numbers genuinely need a GPU browser (see RENDER-ENV-BLOCKER.md).
//
// Replicates isochrone.html: smoothGridTimes (1948), buildContourGeoJSON (2005),
// getBandIndex (1990). Real bristol data. Measures BEFORE (res-4 world, cumulative
// dissolve) vs the proposed FIXES (res-3 for world view; non-cumulative dissolve).

const h3 = require('h3-js');
const path = require('path');
const DATA = require(path.join(__dirname, '..', 'data', 'isochrones', 'bristol.json'));

// --- app constants (isochrone.html) ---
const TIME_BANDS = [2,4,6,8,10,12,14,18,24,Infinity].map(h=>({maxHours:h}));
const colorScale = 1.8; // new default (commit 584fd63d)

function getBandIndex(totalMinutes) {
  const hours = totalMinutes / 60;
  for (let i = 0; i < TIME_BANDS.length; i++)
    if (hours < TIME_BANDS[i].maxHours * colorScale) return i;
  return TIME_BANDS.length - 1;
}

// build a grid.features-like array from a resolution bucket
function featuresFor(resKey) {
  const bucket = DATA.resolutions[resKey];
  const feats = [];
  for (const k of Object.keys(bucket)) {
    feats.push({ properties: { h3Index: k, travelTimeMinutes: bucket[k].t } });
  }
  return feats;
}

// --- smoothGridTimes: 3 passes, gridDisk(cell,1) per cell (the ~2.3M-call pass) ---
function smoothGridTimes(features) {
  let vals = new Map();
  for (const f of features) vals.set(f.properties.h3Index, f.properties.travelTimeMinutes);
  const PASSES = 3, SELF_WEIGHT = 1;
  let diskCalls = 0;
  for (let p = 0; p < PASSES; p++) {
    const next = new Map();
    for (const [cell, t] of vals) {
      let sum = t * SELF_WEIGHT, w = SELF_WEIGHT;
      try {
        for (const nb of h3.gridDisk(cell, 1)) { diskCalls++; if (nb===cell) continue; const nt = vals.get(nb); if (nt!==undefined){sum+=nt;w++;} }
      } catch(e){}
      next.set(cell, sum / w);
    }
    vals = next;
  }
  for (const f of features) { const s = vals.get(f.properties.h3Index); f.properties.smoothTimeMinutes = (s!==undefined)?s:f.properties.travelTimeMinutes; }
  return { diskCalls };
}

// --- buildContourGeoJSON: CUMULATIVE (current) — dissolves 1x,2x,...9x the growing set ---
function buildContourCumulative(features) {
  const buckets = TIME_BANDS.map(()=>[]);
  for (const f of features) buckets[getBandIndex(f.properties.smoothTimeMinutes ?? f.properties.travelTimeMinutes)].push(f.properties.h3Index);
  let cumulative = [], dissolves = 0, cellsDissolved = 0;
  for (let i = 0; i < TIME_BANDS.length - 1; i++) {
    cumulative = cumulative.concat(buckets[i]);
    if (!cumulative.length) continue;
    try { h3.cellsToMultiPolygon(cumulative, true); dissolves++; cellsDissolved += cumulative.length; } catch(e){}
  }
  return { dissolves, cellsDissolved };
}

// --- FIX: NON-cumulative dissolve — each band dissolves only its own cells once ---
function buildContourNonCumulative(features) {
  const buckets = TIME_BANDS.map(()=>[]);
  for (const f of features) buckets[getBandIndex(f.properties.smoothTimeMinutes ?? f.properties.travelTimeMinutes)].push(f.properties.h3Index);
  let dissolves = 0, cellsDissolved = 0;
  for (let i = 0; i < TIME_BANDS.length - 1; i++) {
    if (!buckets[i].length) continue;
    try { h3.cellsToMultiPolygon(buckets[i], true); dissolves++; cellsDissolved += buckets[i].length; } catch(e){}
  }
  return { dissolves, cellsDissolved };
}

// --- recolor: getBandIndex over all cells (the per-tick recolor cost) ---
function recolor(features) { let acc=0; for (const f of features) acc += getBandIndex(f.properties.smoothTimeMinutes ?? f.properties.travelTimeMinutes); return acc; }

function time(label, fn) {
  const t0 = process.hrtime.bigint();
  const r = fn();
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  return { label, ms: +ms.toFixed(1), meta: r };
}

function run(resKey, tag) {
  const feats = featuresFor(resKey);
  const n = feats.length;
  const smooth = time(`smooth`, ()=>smoothGridTimes(feats));         // mutates feats (adds smoothTimeMinutes)
  const cumul  = time(`contour-cumulative`, ()=>buildContourCumulative(feats));
  const noncum = time(`contour-noncumulative`, ()=>buildContourNonCumulative(feats));
  const rec    = time(`recolor`, ()=>recolor(feats));
  return { tag, resKey, cells: n,
    smoothMs: smooth.ms, diskCalls: smooth.meta.diskCalls,
    contourCumulativeMs: cumul.ms, contourNonCumulativeMs: noncum.ms,
    dissolveCellsCumulative: cumul.meta.cellsDissolved, dissolveCellsNonCumulative: noncum.meta.cellsDissolved,
    recolorMs: rec.ms };
}

console.log('=== jetspan CPU micro-benchmark (node, real bristol data) ===');
const res4 = run('4', 'BASELINE world-view (res 4, 109k)');
const res3 = run('3', 'FIX #3 world-view served at res 3 (15k)');
for (const r of [res4, res3]) {
  console.log(`\n[${r.tag}]  cells=${r.cells}`);
  console.log(`  smoothGridTimes:        ${r.smoothMs} ms   (${r.diskCalls.toLocaleString()} gridDisk calls)`);
  console.log(`  buildContour CUMULATIVE: ${r.contourCumulativeMs} ms  (dissolved ${r.dissolveCellsCumulative.toLocaleString()} cell-instances across bands)`);
  console.log(`  buildContour non-cumul:  ${r.contourNonCumulativeMs} ms  (dissolved ${r.dissolveCellsNonCumulative.toLocaleString()} cell-instances)`);
  console.log(`  recolor (getBandIndex):  ${r.recolorMs} ms`);
}
// headline deltas
const worldBuildBaseline = res4.smoothMs + res4.contourCumulativeMs;
const worldBuildFix = res3.smoothMs + res3.contourNonCumulativeMs;
console.log('\n=== HEADLINE ===');
console.log(`world-view heavy build (smooth + contour):`);
console.log(`  BASELINE (res4, cumulative): ${worldBuildBaseline.toFixed(0)} ms`);
console.log(`  FIX (res3, non-cumulative):  ${worldBuildFix.toFixed(0)} ms   → ${(worldBuildBaseline/worldBuildFix).toFixed(1)}x faster`);
console.log(`contour dissolve at res4:  cumulative ${res4.contourCumulativeMs} ms → non-cumulative ${res4.contourNonCumulativeMs} ms  (${(res4.contourCumulativeMs/res4.contourNonCumulativeMs).toFixed(1)}x)`);
console.log(`\nNOTE: FPS/paint not measured (needs GPU browser; pi = software WebGL). These are CPU-bound ops, hardware-representative.`);

// emit JSON for results/
const fs = require('fs');
const out = { generatedNote: 'stamp-after-run', node: process.version, res4, res3, worldBuildBaseline, worldBuildFix };
fs.writeFileSync(path.join(__dirname,'results','baseline-node.json'), JSON.stringify(out,null,2));
console.log('\nwrote perf-lab/results/baseline-node.json');
