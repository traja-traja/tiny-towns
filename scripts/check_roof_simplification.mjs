// Browser QA of the measured offline simplification gallery. Run after fitting.
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(root,'.runtime/browsers');
const {chromium}=await import('playwright');
const folder=path.join(root,'cities/ceske-budejovice/experiments/roof-simplification');
const out=path.join(root,'.work/roof-simplification/qa');
fs.mkdirSync(out,{recursive:true});
const smoke=process.argv.includes('--smoke');
const report={mode:smoke?'final-smoke':'full',errors:[],networkRequests:[],objects:[],cameraViews:[],links:[]};
const browser=await chromium.launch({headless:true});
try{
  const page=await browser.newPage({viewport:{width:1540,height:1100}});
  page.on('pageerror',e=>report.errors.push(String(e)));
  page.on('request',r=>{if(/^https?:/.test(r.url()))report.networkRequests.push(r.url());});
  await page.route(/^https?:/,route=>route.abort('internetdisconnected'));
  await page.goto(pathToFileURL(path.join(folder,'report.html')).href,{waitUntil:'load'});
  report.counts=await page.evaluate(()=>({groups:D.groups.length,buildings:D.buildings.length,runs:D.runs.length,methods:D.methods.length}));
  if(report.counts.groups!==6||report.counts.buildings!==7)throw Error('Expected six requested objects / seven source footprints');
  const embeddedInput=await page.evaluate(()=>D.gallery.inputs.find(i=>i.path.endsWith('/results.json')));
  const actualInput=createHash('sha256').update(fs.readFileSync(path.join(folder,'results.json'))).digest('hex');
  if(embeddedInput?.sha256!==actualInput)throw Error('Gallery is stale relative to results.json');
  report.resultsSha256=actualInput;
  if(smoke){
    report.recommendationCount=await page.evaluate(()=>Array.isArray(D.recommendations)?D.recommendations.length:Object.keys(D.recommendations||{}).length);
    if(!report.recommendationCount)throw Error('Final report has no recorded recommendations');
    const groups=await page.locator('#building option').evaluateAll(os=>os.map(o=>o.value));
    for(const id of groups){await page.locator('#building').selectOption(id);await page.evaluate(()=>new Promise(requestAnimationFrame));const view=await page.evaluate(()=>({state:window.__drawState,recommendation:document.getElementById('recommendation').textContent}));if(!view.state.bounds.every(Number.isFinite)||!view.recommendation.trim())throw Error('Final view missing '+id);report.objects.push({id,...view});}
    const hrefs=await page.locator('a[href]').evaluateAll(as=>as.map(a=>a.getAttribute('href')).filter(h=>h&&!h.startsWith('#')&&!/^[a-z]+:/i.test(h)));for(const href of new Set(hrefs)){const exists=fs.existsSync(path.resolve(folder,href));report.links.push({href,exists});if(!exists)throw Error('Broken local link '+href);}
    report.passed=!report.errors.length&&!report.networkRequests.length;
    if(!report.passed)throw Error('Final smoke check failed');
    console.log(JSON.stringify({passed:true,mode:report.mode,counts:report.counts,recommendations:report.recommendationCount,resultsSha256:actualInput}));
  }else{
  report.defaultWireframe=await page.locator('#wireframe').isChecked();
  if(report.defaultWireframe)throw Error('Triangulation must not be the default display');
  async function state(){await page.evaluate(()=>new Promise(requestAnimationFrame));return page.evaluate(()=>window.__drawState);}
  report.tJunction=await page.evaluate(()=>{
    const model={vertices:[[0,0,1],[2,0,1],[2,2,1],[0,2,1],[1,1,1]],faces:[[0,1,2],[0,4,3],[4,2,3]],face_semantics:['roof','roof','roof'],face_region_ids:[0,0,0],comparison_roof_regions:[{id:0,polygon:{type:'Polygon',coordinates:[[[0,0],[2,0],[2,2],[0,2],[0,0]]]},plane:[0,0,1]}]};
    const g=geometry(model);return{filteredFaces:g.regionFilteredFaces,segments:g.byFace.flat().length};
  });
  if(report.tJunction.filteredFaces!==3||report.tJunction.segments!==4)throw Error('Spurious roof edge at triangulation T-junction');
  const ids=await page.locator('#building option').evaluateAll(options=>options.map(o=>o.value));
  for(const id of ids){
    await page.locator('#building').selectOption(id);
    await page.locator('#all-variants').check();
    const s=await state();
    const expected=await page.evaluate(id=>{const ids=D.groups.find(g=>g.id===id).building_ids;return [...new Set(D.runs.filter(r=>ids.includes(r.id)).map(r=>r.variant))];},id);
    if(s.cards.length!==expected.length)throw Error('Missing variant cards for '+id);
    if(!s.bounds.every(Number.isFinite)||!Number.isFinite(s.scale)||s.scale<=0)throw Error('Invalid fit-to-view '+id);
    const canvases=await page.locator('#models canvas').evaluateAll(cs=>cs.map(c=>{
      const px=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
      let pixels=0;for(let i=0;i<px.length;i+=4)if(px[i+3]>200)pixels++;
      return{width:c.width,height:c.height,drawnFaces:+c.dataset.drawnFaces,drawnEdges:+c.dataset.drawnEdges,pixels,scale:+c.dataset.scale};
    }));
    if(canvases.some(c=>c.drawnFaces>0&&c.pixels<100))throw Error('Blank geometry '+id);
    if(new Set(canvases.map(c=>c.scale)).size!==1)throw Error('Different scale across methods '+id);
    report.objects.push({id,variants:expected,state:s,canvases});
    await page.locator('#all-variants').uncheck();
    const defaults=await state();
    if(defaults.cards.length<2||defaults.cards.length>3)throw Error('Expected two or three selected comparison cards');
    await page.locator('#models').screenshot({path:path.join(out,'comparison-'+id.replace(/[^a-z0-9_-]/gi,'_')+'.png')});
    const selectors=['variant-a','variant-b','variant-c'],secondary=['roofer_c035','merge_15deg_050m','roofer_lod22_regular'];
    for(let i=0;i<3;i++)await page.locator('#'+selectors[i]).selectOption(secondary[i]);
    await state();await page.locator('#models').screenshot({path:path.join(out,'secondary-'+id.replace(/[^a-z0-9_-]/gi,'_')+'.png')});
    const preferred=await page.evaluate(()=>D.default_comparison_variants);
    for(let i=0;i<3;i++)await page.locator('#'+selectors[i]).selectOption(preferred[i]);
    await state();
  }
  await page.locator('#building').selectOption(ids[0]);
  const cameraImages={};
  for(const view of ['iso','top','front','side']){
    await page.locator(`[data-view="${view}"]`).click();
    const s=await state();
    cameraImages[view]=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());
    report.cameraViews.push({view,state:s});
  }
  if(new Set(Object.values(cameraImages)).size!==4)throw Error('Camera presets do not produce distinct images');
  await page.locator('[data-view="iso"]').click();
  const solidImage=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());
  await page.locator('#wireframe').check();
  const wire=await state();
  const wireImage=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());
  report.wireframeChangesImage=solidImage!==wireImage;
  report.wireframeVisibleNote=await page.locator('#diagnostic-note').isVisible();
  if(!report.wireframeChangesImage||!report.wireframeVisibleNote)throw Error('Wireframe toggle not visible/effective');
  await page.locator('#models').screenshot({path:path.join(out,'diagnostic-triangulation.png')});
  await page.locator('#wireframe').uncheck();
  await page.locator('#edges').uncheck();
  report.noEdges=await state();
  if(report.noEdges.cards.some(c=>c.edges!==0))throw Error('Edges toggle left lines on');
  await page.locator('#edges').check();
  const full=await state();
  await page.locator('#roof-only').check();
  report.roofOnly=await state();
  if(!report.roofOnly.cards.some((c,i)=>c.faces<full.cards[i].faces))throw Error('Roof-only did not filter walls');
  await page.locator('#roof-only').uncheck();
  if(await page.locator('#points').isEnabled()){
    const before=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());
    await page.locator('#points').check();await state();
    const after=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());
    await page.locator('#models').screenshot({path:path.join(out,'point-reference.png')});report.pointsToggleChangesImage=before!==after;if(!report.pointsToggleChangesImage)throw Error('Point reference did not change image');
    await page.locator('#points').uncheck();
  }
  const methodIds=await page.locator('#variant-b option').evaluateAll(os=>os.map(o=>o.value));
  for(const method of methodIds){await page.locator('#variant-b').selectOption(method);await state();}
  report.methodSelectorValues=methodIds;
  const localLinks=await page.locator('a[href]').evaluateAll(as=>as.map(a=>a.getAttribute('href')).filter(h=>h&&!h.startsWith('#')&&!/^[a-z]+:/i.test(h)));
  for(const href of new Set(localLinks)){const file=path.resolve(folder,href);const exists=fs.existsSync(file);report.links.push({href,exists});if(!exists)throw Error('Broken local link '+href);}
  await page.setViewportSize({width:390,height:900});
  await page.waitForTimeout(120);
  report.mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  await page.locator('header').screenshot({path:path.join(out,'mobile-header.png')});
  report.mobile=await state();
  report.passed=!report.errors.length&&!report.networkRequests.length&&!report.mobileOverflow;
  if(!report.passed)throw Error('Offline gallery checks failed');
  console.log(JSON.stringify({passed:report.passed,counts:report.counts,objects:report.objects.length,cameras:report.cameraViews.length,networkRequests:report.networkRequests.length,errors:report.errors.length}));
  }
}catch(error){report.passed=false;report.failure=String(error);throw error;}
finally{fs.writeFileSync(path.join(out,smoke?'gallery-final-smoke.json':'gallery-ui.json'),JSON.stringify(report,null,2));await browser.close();}
