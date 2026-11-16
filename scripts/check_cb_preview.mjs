// Verify the built local map with the exact same OpenSeadragon version/SRI.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const work=path.join(root,'.work/.preview/ceske-budejovice');
const baseline=process.argv.includes('--baseline');
const site=path.join(work,baseline?'revisions/baseline/site':'site');
const config=JSON.parse(fs.readFileSync(path.join(work,'mesto.json'),'utf8'));
const addressIndex=JSON.parse(fs.readFileSync(path.join(site,'search.json'),'utf8'));
const baselineIndexPath=path.join(work,'revisions/baseline/site/search.json');
const comparisonIndex=fs.existsSync(baselineIndexPath)?JSON.parse(fs.readFileSync(baselineIndexPath,'utf8')):addressIndex;
const out=path.join(work,baseline?'revisions/baseline/qa-comparison':'qa');
fs.mkdirSync(out,{recursive:true});
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(root,'.runtime/browsers');
const {chromium}=await import('playwright');
const osd=fs.readFileSync(path.join(root,'node_modules/openseadragon/build/openseadragon/openseadragon.min.js'));
const integrity='sha384-'+crypto.createHash('sha384').update(osd).digest('base64');
if(integrity!=='sha384-4BsIv4BUV37POdA1NZ6UcVAsFk96MQXmFLog7pWs+JP+a8k2XjilfManEVdWDxTe') throw Error('Local OSD does not match production SRI');
const mime={'.html':'text/html; charset=utf-8','.json':'application/json','.js':'text/javascript','.css':'text/css','.png':'image/png','.webp':'image/webp','.jpg':'image/jpeg','.dzi':'application/xml','.svg':'image/svg+xml'};
const server=http.createServer((req,res)=>{
  const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const file=path.resolve(site,'.'+(pathname==='/'?'/index.html':pathname));
  if(!file.startsWith(site+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'content-type':mime[path.extname(file)]||'application/octet-stream'});
  if(path.basename(file)==='index.html') {
    const html=fs.readFileSync(file,'utf8');
    const marker="  const placesUl = $('places');";
    if(!html.includes(marker))throw Error('QA navigation hook is missing');
    // Expose the existing navigation function only in this test response.
    // Source files and rendered image pixels are not modified.
    res.end(html.replace(marker,"  window.__qaGoTo = goTo; window.__qaView = () => ({x:viewer.viewport.getCenter().x*W,y:viewer.viewport.getCenter().y*W,zoom:viewer.viewport.getZoom()});\n"+marker));
    return;
  }
  fs.createReadStream(file).pipe(res);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true});
const report={localMap:true,variant:baseline?'preserved-baseline':'current',comparisonCamera:'frozen baseline address coordinates, existing app navigation exposed only in QA HTTP response',offlineDependency:{version:'4.1.0',integrity},errors:[],localFailures:[],optionalMissing:[],externalRequests:[],views:[],buildingViews:[]};
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  page.on('pageerror',e=>report.errors.push(String(e)));
  page.on('response',r=>{
    if(!r.url().startsWith(base)||r.status()<400)return;
    const issue={url:r.url(),status:r.status()};
    // The existing viewer probes this optional file and catches its absence.
    // Accept only that exact 404 when this city's GTFS is explicitly disabled.
    if(r.status()===404&&new URL(r.url()).pathname==='/mhd.json'&&!config.mhd?.gtfs)
      report.optionalMissing.push({...issue,reason:'GTFS disabled; viewer leaves MHD off'});
    else report.localFailures.push(issue);
  });
  await page.route('**/*',async route=>{
    const url=route.request().url();
    if(url.startsWith(base)||url.startsWith('data:')) return route.continue();
    report.externalRequests.push(url);
    if(url==='https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.0/openseadragon.min.js') return route.fulfill({status:200,contentType:'text/javascript',body:osd,headers:{'access-control-allow-origin':'*'}});
    // Offline test: font styles omitted, weather stays unavailable (not fabricated).
    if(url.startsWith('https://fonts.googleapis.com/')) return route.fulfill({status:200,contentType:'text/css',body:''});
    return route.abort('internetdisconnected');
  });
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#loading')?.hidden,{timeout:30000});
  await page.waitForFunction(()=>[...document.querySelectorAll('#osd canvas')].some(c=>c.width>0),{timeout:30000});
  for(const season of ['summer','winter']) {
    await page.locator(`#seasons [data-s="${season}"]`).click();
    await page.waitForTimeout(1800);
    const view=await page.locator('#osd canvas').first().evaluate(c=>{
      const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
      let nonzero=0;for(let i=3;i<d.length;i+=4) if(d[i])nonzero++;
      return {width:c.width,height:c.height,nonzero};
    });
    if(view.nonzero<10000)throw Error('Map canvas is blank');
    report.views.push({season,...view});
    await page.screenshot({path:path.join(out,`${season}-desktop.png`)});
  }
  await page.locator('#q').fill('Krajinská');
  await page.waitForTimeout(500);
  report.searchResults=await page.locator('#results').innerText();
  if(!report.searchResults.trim())throw Error('Known street search returned no results');
  await page.locator('#q').fill('');
  await page.locator('#zin').click();
  await page.waitForTimeout(1000);
  await page.screenshot({path:path.join(out,'centre-detail.png')});
  // Compare actual rendered tiles at identical addresses and zoom, in daylight.
  // These are UI searches; no synthetic geometry is substituted into the map.
  await page.locator('#seasons [data-s="summer"]').click();
  await page.locator('#weather [data-w="clear"]').click();
  await page.locator('#realTime').uncheck();
  await page.locator('#night').evaluate(input=>{
    input.value='0';input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  const disabledOverlays=['l-labels','l-traffic','l-people','l-smoke','l-hover'];
  for(const id of disabledOverlays)await page.locator('#'+id).uncheck();
  for(const [address,file] of [
    ['Na Mlýnské stoce 367','na-mlynske-367.png'],
    ['J. Š. Baara 1810','marianske-baara-1810.png'],
    ['nám. Přemysla Otakara II. 67','namesti-67.png'],
  ]) {
    await page.locator('#q').fill(address);
    const result=page.locator('#results button').filter({hasText:address}).first();
    await result.waitFor({state:'visible'});
    await result.click();
    await page.locator('#cardClose').waitFor({state:'visible'});
    const details=await page.locator('#cardDl').innerText();
    if(!details.includes(address))throw Error('Selected building has unexpected address: '+address);
    await page.locator('#cardClose').click();
    const comparisonEntry=comparisonIndex.find(row=>row[0]===address);
    if(!comparisonEntry)throw Error('Missing comparison anchor: '+address);
    await page.evaluate(([x,y])=>window.__qaGoTo(x,y,2),comparisonEntry.slice(2,4));
    await page.waitForTimeout(1800);
    const camera=await page.evaluate(()=>window.__qaView());
    if(Math.abs(camera.x-comparisonEntry[2])>.1||Math.abs(camera.y-comparisonEntry[3])>.1)
      throw Error('Comparison camera did not reach its frozen position');
    await page.screenshot({path:path.join(out,file)});
    const indexEntry=addressIndex.find(row=>row[0]===address);
    report.buildingViews.push({address,file,details,imageAnchor:indexEntry?.slice(1,4),
      comparisonAnchor:comparisonEntry.slice(1,4),camera,
      zoomImageRatio:2,season:'summer',weather:'clear',time:0,disabledOverlays});
  }
  await page.setViewportSize({width:390,height:850});
  await page.waitForTimeout(700);
  report.mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  await page.screenshot({path:path.join(out,'mobile.png')});
  report.title=await page.title();
  report.subtitle=await page.locator('#sub').innerText();
  report.passed=!report.errors.length&&!report.localFailures.length&&!report.mobileOverflow;
  fs.writeFileSync(path.join(out,'preview-ui.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
  if(!report.passed)throw Error('Map UI checks failed; inspect preview-ui.json');
}finally{await browser.close();await new Promise(r=>server.close(r));}
