/**
 * JetSpan Performance Test Suite
 *
 * Comprehensive stress tests for the flight isochrone visualization.
 * Inject this into the browser console to run tests.
 *
 * Usage:
 *   // Load in browser console or inject via automation
 *   await perfTests.runAll();           // Run full suite
 *   await perfTests.runPanSuite();      // Pan tests only
 *   await perfTests.runZoomSuite();     // Zoom tests only
 *   perfTests.printResults();           // Show results table
 *
 * Test Categories:
 *   1. Zoom levels (res 1-6 transitions)
 *   2. Global panning (14 locations around the world)
 *   3. Cache effectiveness (revisit same locations)
 *   4. Edge cases (water, remote areas, high density)
 */

window.perfTests = {
  results: [],
  screenshots: [],

  // ============================================================
  // TEST LOCATIONS - Global coverage for pan testing
  // ============================================================
  locations: [
    // Europe
    { name: 'Bristol (origin)', coords: [-2.587, 51.454], region: 'europe' },
    { name: 'London', coords: [-0.118, 51.509], region: 'europe' },
    { name: 'Paris', coords: [2.352, 48.857], region: 'europe' },
    { name: 'Berlin', coords: [13.405, 52.520], region: 'europe' },
    { name: 'Moscow', coords: [37.618, 55.756], region: 'europe' },
    { name: 'Reykjavik', coords: [-21.896, 64.147], region: 'europe' },

    // Middle East / Africa
    { name: 'Dubai', coords: [55.270, 25.205], region: 'middle-east' },
    { name: 'Cape Town', coords: [18.424, -33.925], region: 'africa' },

    // Asia Pacific
    { name: 'Mumbai', coords: [72.878, 19.076], region: 'asia' },
    { name: 'Tokyo', coords: [139.691, 35.690], region: 'asia' },
    { name: 'Sydney', coords: [151.209, -33.869], region: 'oceania' },

    // Americas
    { name: 'Los Angeles', coords: [-118.244, 34.052], region: 'north-america' },
    { name: 'New York', coords: [-74.006, 40.713], region: 'north-america' },
    { name: 'Sao Paulo', coords: [-46.633, -23.551], region: 'south-america' },
  ],

  // ============================================================
  // ZOOM LEVELS - Test resolution transitions
  // ============================================================
  zoomLevels: [
    { zoom: 0.8, name: 'Far globe', expectedRes: 1 },
    { zoom: 1.0, name: 'Globe', expectedRes: 1 },
    { zoom: 1.5, name: 'Globe/Continental boundary', expectedRes: 2 },
    { zoom: 2.0, name: 'Continental wide', expectedRes: 2 },
    { zoom: 2.5, name: 'Continental/Regional boundary', expectedRes: 3 },
    { zoom: 3.5, name: 'Regional wide', expectedRes: 3 },
    { zoom: 4.0, name: 'Regional/Local boundary', expectedRes: 4 },
    { zoom: 5.0, name: 'Local', expectedRes: 4 },
    { zoom: 5.5, name: 'Local/Street boundary', expectedRes: 5 },
    { zoom: 6.5, name: 'Street level', expectedRes: 5 },
    { zoom: 7.5, name: 'Detailed', expectedRes: 6 },
  ],

  // ============================================================
  // EDGE CASE LOCATIONS - Stress test specific scenarios
  // ============================================================
  edgeCases: [
    { name: 'Mid-Atlantic (water)', coords: [-30, 35], type: 'water' },
    { name: 'Pacific Ocean', coords: [-150, 0], type: 'water' },
    { name: 'Greenland (remote)', coords: [-42, 72], type: 'remote' },
    { name: 'Siberia (remote)', coords: [120, 65], type: 'remote' },
    { name: 'Singapore (high density)', coords: [103.8, 1.35], type: 'dense' },
    { name: 'Frankfurt (hub)', coords: [8.682, 50.110], type: 'hub' },
  ],

  // ============================================================
  // HELPER FUNCTIONS
  // ============================================================

  getCells() {
    return map.getSource('hexgrid')?._data?.features?.length || 0;
  },

  getRes(zoom) {
    return typeof getResolutionForZoom === 'function'
      ? getResolutionForZoom(zoom)
      : 'N/A';
  },

  async waitForRender(timeout = 8000) {
    const start = performance.now();
    await new Promise(r => setTimeout(r, 500));

    let lastCount = 0;
    let stable = 0;

    while (performance.now() - start < timeout) {
      await new Promise(r => setTimeout(r, 200));
      const count = this.getCells();
      if (count === lastCount && count > 0) {
        stable++;
        if (stable >= 3) break;
      } else {
        stable = 0;
        lastCount = count;
      }
    }

    return Math.round(performance.now() - start);
  },

  async runTest(name, lng, lat, zoom, category = 'general') {
    const startTime = performance.now();
    map.jumpTo({ center: [lng, lat], zoom: zoom });

    const renderTime = await this.waitForRender();
    const cells = this.getCells();
    const res = this.getRes(zoom);
    const msPerCell = cells > 0 ? (renderTime / cells).toFixed(2) : 'N/A';

    const result = {
      name,
      category,
      zoom: zoom.toFixed(1),
      res,
      cells,
      renderTime,
      msPerCell,
      timestamp: new Date().toISOString(),
    };

    this.results.push(result);
    console.log(`[${category}] ${name}: ${renderTime}ms, ${cells} cells (res ${res})`);

    return result;
  },

  // ============================================================
  // TEST SUITES
  // ============================================================

  async runZoomSuite() {
    console.log('\n========== ZOOM LEVEL SUITE ==========\n');
    const center = [-2.587, 51.454]; // Bristol

    for (const level of this.zoomLevels) {
      await this.runTest(
        level.name,
        center[0], center[1],
        level.zoom,
        'zoom'
      );
    }

    return this.results.filter(r => r.category === 'zoom');
  },

  async runPanSuite(zoom = 5) {
    console.log('\n========== PAN SUITE (z' + zoom + ') ==========\n');

    for (const loc of this.locations) {
      await this.runTest(
        loc.name,
        loc.coords[0], loc.coords[1],
        zoom,
        'pan'
      );
    }

    return this.results.filter(r => r.category === 'pan');
  },

  async runEdgeCaseSuite(zoom = 5) {
    console.log('\n========== EDGE CASE SUITE ==========\n');

    for (const loc of this.edgeCases) {
      await this.runTest(
        `${loc.name} (${loc.type})`,
        loc.coords[0], loc.coords[1],
        zoom,
        'edge-' + loc.type
      );
    }

    return this.results.filter(r => r.category.startsWith('edge'));
  },

  async runCacheSuite() {
    console.log('\n========== CACHE SUITE ==========\n');

    // Visit 3 locations, then revisit to test cache
    const testLocs = [
      { name: 'Bristol', coords: [-2.587, 51.454] },
      { name: 'Paris', coords: [2.352, 48.857] },
      { name: 'Berlin', coords: [13.405, 52.520] },
    ];

    // First pass (cold)
    for (const loc of testLocs) {
      await this.runTest(loc.name + ' (cold)', loc.coords[0], loc.coords[1], 5, 'cache-cold');
    }

    // Second pass (warm)
    for (const loc of testLocs) {
      await this.runTest(loc.name + ' (warm)', loc.coords[0], loc.coords[1], 5, 'cache-warm');
    }

    return this.results.filter(r => r.category.startsWith('cache'));
  },

  async runAll() {
    console.log('\n##################################################');
    console.log('# JETSPAN PERFORMANCE TEST SUITE');
    console.log('# ' + new Date().toISOString());
    console.log('##################################################\n');

    this.results = [];

    await this.runZoomSuite();
    await this.runPanSuite();
    await this.runEdgeCaseSuite();
    await this.runCacheSuite();

    this.printSummary();
    return this.results;
  },

  // ============================================================
  // REPORTING
  // ============================================================

  printResults() {
    console.table(this.results.map(r => ({
      Test: r.name,
      Category: r.category,
      Zoom: r.zoom,
      Res: r.res,
      Cells: r.cells,
      'Time (ms)': r.renderTime,
      'ms/cell': r.msPerCell,
    })));
  },

  printSummary() {
    console.log('\n========== SUMMARY ==========\n');

    const categories = [...new Set(this.results.map(r => r.category))];

    for (const cat of categories) {
      const catResults = this.results.filter(r => r.category === cat);
      const avgTime = Math.round(catResults.reduce((a, r) => a + r.renderTime, 0) / catResults.length);
      const maxTime = Math.max(...catResults.map(r => r.renderTime));
      const maxTest = catResults.find(r => r.renderTime === maxTime)?.name;

      console.log(`${cat}: avg=${avgTime}ms, max=${maxTime}ms (${maxTest})`);
    }

    const totalAvg = Math.round(this.results.reduce((a, r) => a + r.renderTime, 0) / this.results.length);
    console.log(`\nOVERALL: avg=${totalAvg}ms across ${this.results.length} tests`);
  },

  exportJSON() {
    return JSON.stringify({
      timestamp: new Date().toISOString(),
      results: this.results,
    }, null, 2);
  },
};

console.log('JetSpan Performance Test Suite loaded.');
console.log('Run: perfTests.runAll() for full suite');
console.log('Run: perfTests.runZoomSuite() for zoom tests');
console.log('Run: perfTests.runPanSuite() for pan tests');
