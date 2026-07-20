// Node unit tests for getVisibleParentCells — the pure viewport→H3-parent-cell
// seam that drives chunk loading (isochrone.html). We extract the live function
// text from isochrone.html and eval it with real h3-js so the test exercises the
// SHIPPING code, not a copy: editing the function is what turns red → green.
//
// Bug under test: when the viewport straddles the international date line,
// map.getBounds() yields west > east (e.g. west=170, east=-170) OR an unwrapped
// east > 180 (west=170, east=190). The naive `for (lng=west; lng<=east; ...)`
// loop then samples nothing (or the wrong hemisphere), so chunks on one side of
// the line never load — "alternates one side or the other".
//
// Run: cd test && npm test

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import * as h3 from 'h3-js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const HTML = readFileSync(join(__dirname, '..', 'isochrone.html'), 'utf8');

// --- extract a top-level `function NAME(...) { ... }` by brace-matching ---
// (getVisibleParentCells has no braces inside strings/regex, so this is safe here)
function extractFunction(html, name) {
  const start = html.indexOf(`function ${name}`);
  if (start === -1) throw new Error(`function ${name} not found in isochrone.html`);
  let depth = 0, i = html.indexOf('{', start), seenBrace = false;
  for (; i < html.length; i++) {
    if (html[i] === '{') { depth++; seenBrace = true; }
    else if (html[i] === '}') { depth--; if (seenBrace && depth === 0) { i++; break; } }
  }
  const src = html.slice(start, i);
  // eval with h3 injected as the only free variable the function references
  return new Function('h3', `${src}\n return ${name};`)(h3);
}

const getVisibleParentCells = extractFunction(HTML, 'getVisibleParentCells');

// --- tiny assert harness (mirrors _test_runner.html's assert(cond, name)) ---
let pass = 0, fail = 0;
const fails = [];
function assert(cond, name) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; fails.push(name); console.log('  ✗ FAIL: ' + name); }
}

// centroid longitude of a parent cell, in [-180, 180]
const cellLng = (cell) => h3.cellToLatLng(cell)[1];
const anyEastOf = (cells, lng) => cells.some(c => cellLng(c) > lng);
const anyWestOf = (cells, lng) => cells.some(c => cellLng(c) < lng);

console.log('\n--- getVisibleParentCells: antimeridian ---');

// A viewport straddling the date line near Fiji: covers lng [170,180] and
// [-180,-170]. getBounds() reports this as west > east (wrapped form).
{
  const bounds = { north: 10, south: -10, west: 170, east: -170 };
  const cells = getVisibleParentCells(bounds, 2);
  assert(cells.length > 0, 'wrapped bounds (west>east) yields cells at all');
  assert(anyEastOf(cells, 150), 'wrapped: includes an EAST-of-line cell (centroid lng > 150)');
  assert(anyWestOf(cells, -150), 'wrapped: includes a WEST-of-line cell (centroid lng < -150)');
}

// Same window, but the unwrapped form MapLibre sometimes returns: east > 180.
{
  const bounds = { north: 10, south: -10, west: 170, east: 190 };
  const cells = getVisibleParentCells(bounds, 2);
  assert(anyEastOf(cells, 150), 'unwrapped (east>180): includes an EAST-of-line cell');
  assert(anyWestOf(cells, -150), 'unwrapped (east>180): includes a WEST-of-line cell');
}

console.log('\n--- getVisibleParentCells: normal viewport (regression) ---');

// A plain non-crossing viewport around Greenwich must still work and must NOT
// suddenly pull in date-line cells.
{
  const bounds = { north: 10, south: -10, west: -10, east: 10 };
  const cells = getVisibleParentCells(bounds, 2);
  assert(cells.length > 0, 'greenwich viewport yields cells');
  assert(!anyEastOf(cells, 150) && !anyWestOf(cells, -150),
    'greenwich viewport pulls in NO date-line cells');
}

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) { console.log('FAILED: ' + fails.join('; ')); process.exit(1); }
