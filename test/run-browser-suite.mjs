// Headless run of _test_runner.html — serves the worktree, loads the page in
// chromium, waits for the suite to finish, prints the <pre> output. Used to
// verify the browser-side antimeridian regression (section 12) actually runs.
import { chromium } from 'playwright';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(fileURLToPath(import.meta.url), '..', '..'); // worktree root
const TYPES = { '.html':'text/html', '.js':'text/javascript', '.mjs':'text/javascript',
  '.json':'application/json', '.gz':'application/gzip', '.css':'text/css' };

const server = http.createServer(async (req, res) => {
  try {
    const path = decodeURIComponent(req.url.split('?')[0]);
    const buf = await readFile(join(ROOT, path));
    const headers = { 'Content-Type': TYPES[extname(path)] || 'application/octet-stream' };
    if (extname(path) === '.gz') headers['Content-Encoding'] = 'gzip';
    res.writeHead(200, headers); res.end(buf);
  } catch { res.writeHead(404); res.end('not found'); }
});

await new Promise(r => server.listen(0, r));
const port = server.address().port;

const browser = await chromium.launch();
const page = await browser.newPage();
page.on('console', m => { if (m.type() === 'error') console.log('[console.error]', m.text()); });
await page.goto(`http://localhost:${port}/_test_runner.html`);
await page.waitForFunction(
  () => document.getElementById('output').textContent.includes('TESTS'),
  { timeout: 60000 }
).catch(() => console.log('(timed out waiting for suite to finish)'));

const out = await page.$eval('#output', el => el.textContent);
// print only the antimeridian section + summary to keep it focused
const lines = out.split('\n');
const s12 = lines.findIndex(l => l.includes('Antimeridian'));
console.log(lines.slice(s12 >= 0 ? s12 : 0).join('\n'));

await browser.close();
server.close();
