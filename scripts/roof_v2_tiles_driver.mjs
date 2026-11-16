/** Render prepared roof-v2 substitutions with the actual local map renderer.
 * One browser, one page at a time. No network fetches, visual scoring, production
 * writes, or full-map rebuild. Python wrapper applies the process-tree RAM cap.
 */
import fs from 'node:fs/promises';
import {writeFileSync, realpathSync} from 'node:fs';
import path from 'node:path';
import {performance} from 'node:perf_hooks';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';

export function fatalGpuMessage(message) {
  return /out[ _-]?of[ _-]?memory|\boom\b|context[ _-]?(?:lost|loss)|webglprogram|shader[\s\S]{0,120}(?:error|fail)|(?:error|fail)[\s\S]{0,120}shader|gl_invalid|invalid_operation|invalid framebuffer|framebuffer[\s\S]{0,60}incomplete|gpu[\s\S]{0,60}(?:crash|error|fail)/i.test(message);
}

export function assertPixelQA(qa, baseline, label='tile') {
  if (!qa || !Number.isFinite(qa.opaque_fraction) || !Number.isFinite(qa.luma_variance) || !(qa.sample_count > 0))
    throw new Error(`${label}: missing/nonfinite pixel QA`);
  if (qa.opaque_fraction < .005 || qa.unique_rgb < 8 || qa.luma_variance < 2)
    throw new Error(`${label}: blank/uniform render (${JSON.stringify(qa)})`);
  if (baseline?.opaque_fraction > .02 && qa.opaque_fraction < baseline.opaque_fraction * .7)
    throw new Error(`${label}: most baseline geometry disappeared (alpha ${qa.opaque_fraction} vs ${baseline.opaque_fraction})`);
  return {...qa, baseline_opaque_fraction:baseline?.opaque_fraction ?? null, passed:true};
}

export async function bounded(promise, label, milliseconds) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label}: timeout after ${milliseconds} ms`)), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}

export function sameEntryPath(entry, moduleFile, platform=process.platform) {
  if (!entry) return false;
  const paths = platform === 'win32' ? path.win32 : path;
  const canonical = value => {
    let result = paths.resolve(value);
    try { result = realpathSync.native(result); } catch { /* tests / nonexistent path */ }
    return platform === 'win32' ? result.toLowerCase() : result;
  };
  return canonical(entry) === canonical(moduleFile);
}

async function main() {
const configPath = process.argv[2];
if (!configPath) throw new Error('Usage: node scripts/roof_v2_tiles_driver.mjs prepared/config.json');
console.log(`[roof-v2] config.read ${configPath}`);
const config = JSON.parse(await fs.readFile(configPath, 'utf8'));
const {root, work, output, staging, info, tiles, expected} = config;
const exists = async p => p && !!(await fs.stat(p).catch(() => null));
let executablePath = config.browser;
if (!executablePath) {
  for (const candidate of ['C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe']) {
    if (await exists(candidate)) { executablePath = candidate; break; }
  }
}
if (!(await exists(executablePath))) throw new Error('No installed Chrome/Edge; pass --browser in the Python wrapper.');
const allowed = new Map([
  ['/render.html', path.join(staging, 'render.html')],
  ['/build/scene.json', path.join(staging, 'scene.json')],
  ['/build/ground_summer.png', config.texture_paths?.['ground_summer.png'] || path.join(work, 'build/ground_summer.png')],
  ['/build/lightmap.png', config.texture_paths?.['lightmap.png'] || path.join(work, 'build/lightmap.png')],
  ['/assets/custom_models.js', path.join(work, 'assets/custom_models.js')],
  ['/node_modules/three/build/three.module.js', path.join(root, 'node_modules/three/build/three.module.js')],
  ['/node_modules/three/build/three.core.js', path.join(root, 'node_modules/three/build/three.core.js')],
]);
const mime = {'.html':'text/html', '.js':'text/javascript', '.json':'application/json', '.png':'image/png'};
const started = performance.now();
const metrics = {browser:executablePath, local_only:true, software_gpu:!!config.software_gpu,
  tile_count:tiles.length, modes:{}, expected, optional_assets_missing:[],status:'running',
  preview_resolution:config.preview_resolution};
const metricsPath = path.join(output, 'render-metrics.json');
const checkpoint = (phase, detail = {}) => {
  metrics.phase = phase;
  metrics.seconds = (performance.now()-started)/1000;
  console.log(`[roof-v2 ${metrics.seconds.toFixed(3)}s] ${phase} ${JSON.stringify(detail)}`);
  writeFileSync(metricsPath, JSON.stringify(metrics,null,2)+'\n');
};
const watchdogMs = Math.max(30000,Math.min(600000,Number(config.watchdog_ms)||300000));
const watchdog = setTimeout(() => {
  metrics.status = 'watchdog_timeout';
  metrics.error = `Hard driver watchdog reached ${watchdogMs} ms`;
  try { checkpoint('watchdog.exit124'); } catch (e) { console.error(e); }
  // The owning resource_guard Windows Job closes the entire browser tree.
  process.exit(124);
}, watchdogMs);
const args = ['--use-gl=angle'];
if (config.software_gpu) args.push('--use-angle=swiftshader', '--enable-unsafe-swiftshader');
let browser;
try {
  checkpoint('playwright.import.start');
  const {chromium} = await bounded(import('playwright'), 'playwright.import', 30000);
  checkpoint('playwright.import.done');
  checkpoint('browser.launch.start',{executablePath,args,watchdog_ms:watchdogMs});
  browser = await bounded(chromium.launch({headless:true, executablePath, args, timeout:45000}), 'browser.launch', 50000);
  checkpoint('browser.launch.done');
  const modes = config.modes || ['after','diagnostic'];
  if (!modes.length || modes.some(m => !['after','diagnostic'].includes(m))) throw new Error('Invalid render modes');
  for (const mode of modes) {
    const diagnostic = mode === 'diagnostic';
    const begin = performance.now();
    const folder = path.join(output, mode);
    await fs.mkdir(folder, {recursive:true});
    checkpoint(`${mode}.page.start`);
    const page = await bounded(browser.newPage({viewport:{width:1024,height:1024}}), `${mode}.newPage`, 30000);
    const errors = [], missing = [], messages = [], gpuErrors = [], tileMetrics = [];
    const modeMetrics = metrics.modes[mode] = {status:'starting',errors,missing,messages,gpuErrors,tiles:tileMetrics};
    let rejectFatal, fatalError;
    const fatalPromise = new Promise((_, reject) => { rejectFatal = reject; });
    // A console/page error can arrive before navigation is being awaited.
    fatalPromise.catch(() => {});
    const fail = message => {
      errors.push(message);
      console.error(`[roof-v2 ${mode}] FATAL ${message}`);
      if (!fatalError) {
        fatalError = new Error(`${mode}: ${message}`);
        metrics.error = fatalError.message;
        checkpoint(`${mode}.fatal`,{message});
        rejectFatal(fatalError);
      }
    };
    const raced = (promise, phase, timeout) => bounded(Promise.race([promise,fatalPromise]), `${mode}.${phase}`, timeout);
    const assertHealthy = () => {
      if (errors.length || missing.length || gpuErrors.length)
        throw new Error(`${mode}: renderer failure ${JSON.stringify({errors,missing,gpuErrors})}`);
    };
    page.on('pageerror', err => fail(`pageerror: ${err.stack || err.message}`));
    page.on('crash', () => fail('Browser page crashed'));
    page.on('requestfailed', request => fail(`requestfailed: ${request.url()} ${request.failure()?.errorText || ''}`));
    page.on('console', msg => {
      if (['warning','error'].includes(msg.type())) messages.push(msg.text());
      if (fatalGpuMessage(msg.text())) { gpuErrors.push(msg.text()); fail(`GPU: ${msg.text()}`); }
    });
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin === 'http://roof-v2.local' && url.pathname === '/favicon.ico') {
        await route.fulfill({status:204,body:''}); return;
      }
      const file = url.origin === 'http://roof-v2.local' && allowed.get(url.pathname);
      if (!file) { missing.push(url.href); fail(`Blocked unexpected request: ${url.href}`); await route.abort('blockedbyclient'); return; }
      // The production renderer explicitly catches this optional import. A
      // city without custom models must preserve that same fallback behavior.
      if (url.pathname === '/assets/custom_models.js' && !(await exists(file))) {
        if (!metrics.optional_assets_missing.includes(url.pathname)) metrics.optional_assets_missing.push(url.pathname);
        // Equivalent to the production import().catch(() => ({})), without
        // reporting an intentionally absent module as a failed network load.
        await route.fulfill({status:200,contentType:'text/javascript',body:'export {};\n'});
        return;
      }
      await route.fulfill({path:file, contentType:mime[path.extname(file)] || 'application/octet-stream'});
    });
    const query = new URLSearchParams({mpp:String(info.mpp), tile:String(info.tile), alpha:'1', season:'summer',
      v2diagnostic:diagnostic ? '1' : '0'});
    checkpoint(`${mode}.navigation.start`);
    await raced(page.goto(`http://roof-v2.local/render.html?${query}`, {waitUntil:'load',timeout:120000}), 'goto', 125000);
    checkpoint(`${mode}.navigation.loaded`);
    await raced(page.waitForFunction(() => window.READY === true, null, {timeout:180000,polling:100}), 'ready', 185000);
    checkpoint(`${mode}.renderer.ready`);
    const state = await raced(page.evaluate(() => ({info:window.INFO, stats:window.ROOF_V2_STATS})), 'state', 15000);
    if (state.stats?.context_lost) throw new Error(`${mode}: WebGL context already lost`);
    for (const key of ['x0','y1','width','height','mpp','tile']) {
      if (Math.abs(state.info[key] - info[key]) > 1e-7) throw new Error(`Tile grid mismatch: ${key}`);
    }
    const stats = state.stats;
    if (JSON.stringify([...stats.replaced_scene_ids].sort((a,b)=>a-b)) !== JSON.stringify(expected.scene_ids))
      throw new Error('Not all original source-OID scene pieces were removed.');
    for (const key of ['mesh_parts','roof_triangles','wall_triangles'])
      if (stats[key] !== expected[key]) throw new Error(`Geometry count mismatch: ${key}`);
    modeMetrics.stats = stats;
    modeMetrics.status = 'rendering';
    assertHealthy();
    const tileHashes = new Set();
    for (const [i,j] of tiles) {
      const tick = performance.now();
      checkpoint(`${mode}.tile.start`,{i,j});
      const rendered = await raced(page.evaluate(([x,y]) => ({png:window.renderTile(x,y),
        qa:window.ROOF_V2_LAST_PIXEL_QA,context_lost:window.ROOF_V2_STATS.context_lost}), [i,j]), `tile.${i}_${j}`, 60000);
      assertHealthy();
      if (rendered.context_lost) throw new Error(`${mode} ${i}_${j}: WebGL context lost`);
      const pixelQA = assertPixelQA(rendered.qa, config.baseline_pixel_qa?.[`${i}_${j}`], `${mode} ${i}_${j}`);
      const png = rendered.png;
      if (typeof png !== 'string' || !png.startsWith('data:image/png;base64,')) throw new Error(`Invalid tile ${i}_${j}`);
      const bytes = Buffer.from(png.slice(png.indexOf(',')+1), 'base64');
      if (bytes.toString('hex',0,8) !== '89504e470d0a1a0a') throw new Error('PNG signature mismatch');
      if (bytes.readUInt32BE(16) !== info.tile || bytes.readUInt32BE(20) !== info.tile) throw new Error('PNG dimensions mismatch');
      const sha256 = createHash('sha256').update(bytes).digest('hex');
      tileHashes.add(sha256);
      await fs.writeFile(path.join(folder, `${i}_${j}.png`), bytes);
      tileMetrics.push({i,j,bytes:bytes.length,sha256,pixel_qa:pixelQA,seconds:(performance.now()-tick)/1000});
      console.log(`${mode} ${i}_${j}: ${tileMetrics.at(-1).seconds.toFixed(3)} s`);
      checkpoint(`${mode}.tile.validated`,{i,j,pixel_qa:pixelQA});
    }
    assertHealthy();
    if (tiles.length > 1 && tileHashes.size === 1) throw new Error(`${mode}: all rendered tiles are identical`);
    modeMetrics.seconds = (performance.now()-begin)/1000;
    modeMetrics.status = 'validated';
    await fs.writeFile(path.join(folder, 'info.json'), JSON.stringify(info));
    checkpoint(`${mode}.page.close.start`);
    await bounded(page.close(), `${mode}.page.close`, 10000);
    checkpoint(`${mode}.page.closed`);
  }
  metrics.status = 'validated';
} catch (error) {
  metrics.status = 'failed';
  metrics.error = String(error.stack || error);
  checkpoint('render.failed',{error:metrics.error});
  throw error;
} finally {
  metrics.seconds = (performance.now()-started)/1000;
  // Persist the error/result before browser.close: Chromium can hang during
  // teardown after GPU/context failures, so it must never hide the diagnosis.
  checkpoint('browser.close.start');
  if (browser) {
    try { await bounded(browser.close(), 'browser.close', 10000); }
    catch (error) {
      metrics.status = 'close_timeout'; metrics.close_error = String(error);
      checkpoint('browser.close.exit124',{error:metrics.close_error});
      process.exit(124);
    }
  }
  clearTimeout(watchdog);
  checkpoint('driver.complete');
}
console.log(JSON.stringify({seconds:metrics.seconds,tile_count:tiles.length,modes:Object.keys(metrics.modes)}));
}

const entryPath = process.argv[1] ? path.resolve(process.argv[1]) : null;
const modulePath = fileURLToPath(import.meta.url);
const isEntry = sameEntryPath(entryPath,modulePath);
console.log(`[roof-v2] STARTUP ${JSON.stringify({entry_path:entryPath,module_path:modulePath,
  normalized_entry:entryPath?.toLowerCase(),normalized_module:modulePath.toLowerCase(),platform:process.platform,main:isEntry})}`);
if (isEntry) await main();
