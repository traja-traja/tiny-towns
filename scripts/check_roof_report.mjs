// Offline UI verification of the actual pilot result, not synthetic geometry.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(root, '.runtime', 'browsers');
const { chromium } = await import('playwright');
const city = process.argv[2] || 'velesin';
if (!['velesin','ceske-budejovice'].includes(city)) throw new Error('Unsupported pilot city');
const dest = path.join(root, '.work', city === 'velesin' ? 'roof-pilot' : 'cb-roof-pilot', 'qa');
fs.mkdirSync(dest, { recursive: true });
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport:{width:1400,height:1100}});
  const errors = [], requests = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('request', r => { if (/^https?:/.test(r.url())) requests.push(r.url()); });
  await page.goto(pathToFileURL(path.join(root,'cities',city,'roof-pilot/report.html')).href);
  const options = await page.locator('#building option').count();
  if (options !== 30 || await page.locator('canvas').count() !== 6) throw new Error('Wrong building/panel count');
  const report = {city,buildings:options,panels:6,views:[]};
  for (const index of city === 'ceske-budejovice' ? [0,2,4,5,6] : [0,2,6,10]) {
    await page.locator('#building').selectOption({index});
    await page.locator('#rotation').evaluate(el => {el.value='55';el.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.evaluate(() => new Promise(requestAnimationFrame));
    const metrics = await page.locator('canvas').evaluateAll(cs => cs.map(c => {
      const pixels = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
      let painted = 0; for(let i=3;i<pixels.length;i+=4) if(pixels[i]) painted++;
      return {width:c.width,height:c.height,painted};
    }));
    report.views.push({index,canvases:metrics});
    await page.locator('#models').screenshot({path:path.join(dest,`building-${index+1}.png`)});
  }
  await page.setViewportSize({width:390,height:900});
  await page.evaluate(() => new Promise(requestAnimationFrame));
  report.mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  report.errors=errors;report.networkRequests=requests;
  if (errors.length || requests.length || report.mobileOverflow) throw new Error(JSON.stringify(report));
  fs.writeFileSync(path.join(dest,'report-ui.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} finally {await browser.close();}
