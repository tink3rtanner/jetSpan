#!/usr/bin/env node

/**
 * Run JetSpan's browser journey benchmark and save a comparable JSON report.
 *
 * Requires Playwright in the Node environment:
 *   npx playwright install chromium
 *   node scripts/run-interaction-bench.mjs --label baseline
 */

import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.dirname(SCRIPT_DIR);

function parseArgs(argv) {
  const args = {
    url: 'http://localhost:8899/isochrone.html',
    label: 'run',
    out: null,
    compare: null,
    viewport: '1920x1080',
    headed: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--headed') args.headed = true;
    else if (arg.startsWith('--')) {
      const key = arg.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      if (!(key in args)) throw new Error(`Unknown option: ${arg}`);
      args[key] = argv[++i];
    }
  }
  return args;
}

function formatMs(value) {
  return `${Math.round(value || 0).toLocaleString()}ms`;
}

function summarize(run) {
  const rows = run.results
    .filter(result => !result.skipped)
    .map(result => {
      const chunks = result.resources?.chunks || 0;
      return [
        result.scenario.padEnd(22),
        formatMs(result.wallMs).padStart(9),
        `${(result.fps || 0).toFixed(1)}fps`.padStart(9),
        `p95 ${formatMs(result.p95FrameMs)}`.padStart(11),
        `max ${formatMs(result.maxFrameMs)}`.padStart(12),
        `blocked ${formatMs(result.longTaskTotalMs)}`.padStart(16),
        `chunks ${chunks}`.padStart(10),
      ].join('  ');
    });
  return rows.join('\n');
}

function compareRuns(baseline, current) {
  const previous = new Map(baseline.results.map(result => [result.scenario, result]));
  return current.results
    .filter(result => previous.has(result.scenario) && !result.skipped)
    .map(result => {
      const old = previous.get(result.scenario);
      const oldWall = old.wallMs || 0;
      const newWall = result.wallMs || 0;
      const pct = oldWall ? ((newWall - oldWall) / oldWall) * 100 : 0;
      const oldBlocked = old.longTaskTotalMs || 0;
      const newBlocked = result.longTaskTotalMs || 0;
      return `${result.scenario.padEnd(22)} wall ${formatMs(oldWall)} -> ${formatMs(newWall)}` +
        ` (${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%)` +
        `  blocked ${formatMs(oldBlocked)} -> ${formatMs(newBlocked)}`;
    })
    .join('\n');
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const [width, height] = args.viewport.split('x').map(Number);
  if (!width || !height) throw new Error(`Invalid viewport: ${args.viewport}`);

  const systemChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const launchOptions = { headless: !args.headed };
  try {
    await fs.access(systemChrome);
    launchOptions.executablePath = systemChrome;
  } catch {
    // Fall back to Playwright's managed Chromium on non-macOS systems.
  }
  const browser = await chromium.launch(launchOptions);
  try {
    const page = await browser.newPage({ viewport: { width, height } });
    await page.goto(args.url, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.addScriptTag({ path: path.join(REPO, 'scripts', 'interaction-bench.js') });
    const readiness = await page.evaluate(() => window.waitForJetSpanReady(120000));
    if (!readiness.ready) throw new Error('JetSpan did not become ready within 120s');

    const run = await page.evaluate(() => window.runInteractionBench());
    if (!run) throw new Error('Benchmark returned no report');
    await page.waitForFunction(
      () => typeof isUpdatingGrid !== 'undefined' && !isUpdatingGrid && map.loaded(),
      null,
      { timeout: 30000 },
    );
    const mapBox = await page.locator('#map').boundingBox();
    let trustedHoverVisible = false;
    if (mapBox) {
      const hitPoint = await page.evaluate(() => {
        const canvas = map.getCanvas();
        const rect = canvas.getBoundingClientRect();
        const cx = canvas.clientWidth / 2;
        const cy = canvas.clientHeight / 2;
        const candidates = [
          [cx, cy], [cx + 200, cy], [cx - 200, cy],
          [cx, cy + 200], [cx, cy - 200],
        ];
        for (const [x, y] of candidates) {
          const topElement = document.elementFromPoint(rect.left + x, rect.top + y);
          if (topElement === canvas &&
              map.queryRenderedFeatures([x, y], { layers: ['hexgrid-fill'] }).length) {
            return { x, y };
          }
        }
        return null;
      });
      if (hitPoint) {
        await page.mouse.move(mapBox.x + hitPoint.x, mapBox.y + hitPoint.y);
        await page.waitForTimeout(150);
        trustedHoverVisible = await page.locator('#tooltip').evaluate(
          element => element.classList.contains('visible'),
        );
      }
    }
    run.behavior = { trustedHoverVisible };
    if (!trustedHoverVisible) {
      throw new Error('Trusted hover did not display a tooltip');
    }
    if (run.layout?.horizontalOverflowPx > 1) {
      throw new Error(`Page overflows viewport by ${run.layout.horizontalOverflowPx}px`);
    }
    run.machine = os.hostname();
    run.platform = `${os.platform()} ${os.release()} ${os.arch()}`;

    const stamp = new Date().toISOString().slice(0, 10);
    const out = args.out
      ? path.resolve(args.out)
      : path.join(REPO, 'docs', 'benchmarks', `${stamp}-journey-${args.label}-${os.hostname()}.json`);
    await fs.mkdir(path.dirname(out), { recursive: true });
    await fs.writeFile(out, `${JSON.stringify(run, null, 2)}\n`);

    console.log(`\n=== JetSpan journey benchmark: ${args.label} ===`);
    console.log(`startup ready: ${formatMs(run.startup.readyMs)}; ` +
      `${run.startup.requests} requests; ${(run.startup.encodedBytes / 1048576).toFixed(1)} MiB encoded`);
    console.log(summarize(run));
    console.log(`\nslowest stops:`);
    const pan = run.results.find(result => result.scenario === 'pan-load-matrix');
    for (const stop of pan?.slowestStops || []) {
      console.log(`  ${stop.name.padEnd(22)} ${formatMs(stop.wallMs).padStart(9)}  ` +
        `r${stop.resolution}  ${stop.cells.toLocaleString()} cells  ${stop.chunks} chunks`);
    }
    console.log(`\nsaved: ${path.relative(REPO, out)}`);

    if (args.compare) {
      const baseline = JSON.parse(await fs.readFile(path.resolve(args.compare), 'utf8'));
      console.log(`\n=== comparison: ${args.compare} ===`);
      console.log(compareRuns(baseline, run));
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(`Benchmark failed: ${error.stack || error.message}`);
  process.exitCode = 1;
});
