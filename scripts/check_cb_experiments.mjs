// Offline browser QA of the actual measured gallery, after all heavy work.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(root,'.runtime/browsers');
const {chromium}=await import('playwright');
const folder=path.join(root,'cities/ceske-budejovice/experiments');
const out=path.join(root,'.work/cb-experiments/qa');
fs.mkdirSync(out,{recursive:true});
const report={errors:[],networkRequests:[],roofViews:[],arcadeViews:[],facadeViews:[],referenceViews:[],links:[]};
const browser=await chromium.launch({headless:true});
try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  page.on('pageerror',e=>report.errors.push(String(e)));
  page.on('request',r=>{if(/^https?:/.test(r.url()))report.networkRequests.push(r.url());});
  await page.route(/^https?:/,route=>route.abort('internetdisconnected'));
  await page.goto(pathToFileURL(path.join(folder,'report.html')).href,{waitUntil:'load'});
  report.mapRebuildComplete=await page.evaluate(()=>D.map_rebuild?.status==='complete');
  if(!report.mapRebuildComplete)throw Error('Final gallery QA requires the completed map rebuild metadata');
  if(!await page.evaluate(()=>!!D.map_comparison))throw Error('Actual before/after map screenshots are missing');
  await page.waitForFunction(()=>['map-before','map-after'].every(id=>{const im=document.getElementById(id);return im.complete&&im.naturalWidth>0;}));
  report.mapComparison=await page.locator('#map-pair-section img').evaluateAll(images=>images.map(im=>({width:im.naturalWidth,height:im.naturalHeight})));
  const counts=await page.evaluate(()=>({roof:document.querySelectorAll('#roof-building option').length,arcade:document.querySelectorAll('#arcade-building option').length,facade:document.querySelectorAll('#facade-building option').length,detail:D.protocol.detailed_footprints,round2:D.round2?.candidates?.length||0}));
  if(counts.roof!==18||counts.arcade!==3||counts.facade!==3||counts.detail>20)throw Error('Unexpected counts: '+JSON.stringify(counts));
  report.counts=counts;
  report.heightFindingCards=await page.locator('#height-finding-cards article').count();
  if(report.heightFindingCards!==3)throw Error('Missing current height findings');
  async function canvasCounts(prefix){
    await page.evaluate(()=>new Promise(requestAnimationFrame));
    return page.locator(`#${prefix}-models canvas`).evaluateAll(cs=>cs.map(c=>{
      const data=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
      let geometryPixels=0;for(let i=0;i<data.length;i+=4)if(data[i+3]>245&&data[i]>120&&data[i+1]>80&&data[i+2]>60)geometryPixels++;
      return {width:c.width,height:c.height,geometryPixels};
    }));
  }
  const roofIds=await page.locator('#roof-building option').evaluateAll(options=>options.map(o=>o.value));
  for(const id of roofIds){
    await page.locator('#roof-building').selectOption(id);
    const expected=await page.evaluate(id=>D.roofs.runs.filter(r=>r.id===id).map(r=>({variant:r.variant,renderable:!!(r.model?.vertices?.length&&r.model?.faces?.length),error:r.error||null})),id);
    const canvases=await canvasCounts('roof');
    if(canvases.length!==expected.length)throw Error('Wrong number of roof cards '+id);
    expected.forEach((run,i)=>{if(run.renderable&&!canvases[i].geometryPixels)throw Error('Blank renderable roof '+id+' '+run.variant);});
    report.roofViews.push({id,runs:expected,canvases});
  }
  const photos=await page.evaluate(()=>D.research.roofs?.photo_review?.cases||[]);
  for(const photo of photos){
    const id=photo.ids.find(id=>roofIds.includes(id));if(!id)continue;
    await page.locator('#roof-building').selectOption(id);
    await page.waitForFunction(()=>{const im=document.getElementById('roof-photo');return im.complete&&im.naturalWidth>0;});
    report.referenceViews.push({key:photo.key,id,width:await page.locator('#roof-photo').evaluate(im=>im.naturalWidth),attribution:await page.locator('#roof-photo-attribution').innerText()});
  }
  if(report.referenceViews.length!==5)throw Error('Expected five photographic roof review cases');
  report.referenceUniqueSources=new Set(photos.map(p=>p.local_reference)).size;
  for(const [key,filename]of [['pool','roof-pool.png'],['black_tower','roof-black-tower.png'],['arena','roof-arena.png']]){
    const photo=photos.find(p=>p.key===key);await page.locator('#roof-building').selectOption(photo.ids[0]);
    await page.locator('#roof-rotation').evaluate(el=>{el.value='45';el.dispatchEvent(new Event('input',{bubbles:true}));});
    await canvasCounts('roof');
    await page.locator('#roof-models').screenshot({path:path.join(out,filename)});
  }
  const arcadeIds=await page.locator('#arcade-building option').evaluateAll(options=>options.map(o=>o.value));
  for(const id of arcadeIds){
    await page.locator('#arcade-building').selectOption(id);
    for(const depth of ['2','3.5']){
      await page.locator('#arcade-depth').selectOption(depth);
      const canvases=await canvasCounts('arcade');
      if(canvases.length!==4||canvases.some(c=>!c.geometryPixels))throw Error('Missing arcade geometry '+id+' depth '+depth);
      report.arcadeViews.push({id,depth,canvases});
    }
  }
  await page.locator('#arcade-building').selectOption('acf04bcb-18f5-41ec-b7e7-14232e12fc1f');
  await page.locator('#arcade-depth').selectOption('2');
  await canvasCounts('arcade');
  const arcadeFront=await page.locator('#arcade-models canvas').first().evaluate(c=>c.toDataURL());
  await page.locator('#arcade-models').screenshot({path:path.join(out,'arcade-front-detail.png')});
  await page.locator('#arcade-closeup').uncheck();
  await page.locator('#arcade-rotation').evaluate(el=>{el.value='265';el.dispatchEvent(new Event('input',{bubbles:true}));});
  report.arcadeFullView=await canvasCounts('arcade');
  report.arcadeCameraChangesImage=arcadeFront!==await page.locator('#arcade-models canvas').first().evaluate(c=>c.toDataURL());
  if(!report.arcadeCameraChangesImage)throw Error('Arcade camera control did not change the image');
  await page.locator('#arcade-models').screenshot({path:path.join(out,'arcade-full-volume.png')});
  const facadeIds=await page.locator('#facade-building option').evaluateAll(options=>options.map(o=>o.value));
  for(const id of facadeIds){
    await page.locator('#facade-building').selectOption(id);
    await page.waitForFunction(()=>[...document.querySelectorAll('#facade-models img,#roi-photo')].every(im=>im.complete&&im.naturalWidth>0));
    const images=await page.locator('#facade-models img,#roi-photo').evaluateAll(ims=>ims.map(im=>({width:im.naturalWidth,height:im.naturalHeight})));
    if(images.length!==4)throw Error('Expected three SVGs plus ROI image');
    report.facadeViews.push({id,images,review:await page.locator('#facade-review').innerText(),attribution:await page.locator('#photo-attribution').innerText()});
  }
  await page.locator('#facade-building').selectOption(facadeIds[0]);
  await page.waitForFunction(()=>[...document.querySelectorAll('#facade-models img')].every(im=>im.complete&&im.naturalWidth>0));
  await page.locator('#facade-models').screenshot({path:path.join(out,'facade-townhall.png')});
  const localLinks=await page.locator('a[href]').evaluateAll(as=>as.map(a=>a.getAttribute('href')).filter(h=>h&&!h.startsWith('#')&&!/^[a-z]+:/i.test(h)));
  for(const href of new Set(localLinks)){
    const file=path.resolve(folder,href);const exists=fs.existsSync(file)&&(!fs.statSync(file).isDirectory()||fs.existsSync(path.join(file,'index.html')));
    report.links.push({href,exists});if(!exists)throw Error('Broken local link '+href);
  }
  for(const required of ['roof-heights/README.md','roof-heights/results.json','roof-heights/fit-report.html','round-2-README.md','round-2-candidates.json'])if(!report.links.some(l=>l.href===required&&l.exists))throw Error('Missing audit/backlog link '+required);
  await page.setViewportSize({width:390,height:900});
  await page.evaluate(()=>new Promise(requestAnimationFrame));
  report.mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  await page.locator('header').screenshot({path:path.join(out,'mobile-header.png')});
  report.passed=!report.errors.length&&!report.networkRequests.length&&!report.mobileOverflow;
  if(!report.passed)throw Error('Gallery browser checks failed');
  console.log(JSON.stringify(report));
}catch(error){report.passed=false;report.failure=String(error);throw error;}
finally{fs.writeFileSync(path.join(out,'gallery-ui.json'),JSON.stringify(report,null,2));await browser.close();}
