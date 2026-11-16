// Offline UI and same-mesh diagnostic checks; run only after workers finish.
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(root,'.runtime/browsers');
const {chromium}=await import('playwright');
const folder=path.join(root,'cities/ceske-budejovice/experiments/roof-components');
const out=path.join(root,'.work/cb-roof-components/qa');
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
  if(report.counts.groups!==6||report.counts.buildings!==7)throw Error('Expected six objects/seven frozen footprints');
  const input=await page.evaluate(()=>D.gallery.inputs.find(i=>i.path.endsWith('/results.json')));
  const actual=createHash('sha256').update(fs.readFileSync(path.join(folder,'results.json'))).digest('hex');
  if(input?.sha256!==actual)throw Error('Gallery does not contain current results');
  report.resultsSha256=actual;
  report.sourceRows=await page.locator('#source-counts tr').count();
  if(report.sourceRows!==7)throw Error('Missing point-cloud provenance rows');
  report.depthRegression=await page.evaluate(()=>{
    const canvas=document.createElement('canvas');canvas.width=20;canvas.height=20;const ctx=canvas.getContext('2d');
    const face=(ps,role)=>({f:[0,1,2],i:0,ps,g:{normals:[[0,0,1]],roles:[role],byFace:[[]]}});
    const a=face([[0,0,9],[18,0,0],[0,18,0]],'roof'),b=face([[0,0,4],[18,0,4],[0,18,4]],'wall');
    depthRender(ctx,[a,b],1,false,false);const near=[...ctx.getImageData(1,1,1,1).data],far=[...ctx.getImageData(6,6,1,1).data],one=canvas.toDataURL();
    depthRender(ctx,[b,a],1,false,false);return {near,far,orderIndependent:one===canvas.toDataURL(),roof:shade([0,0,1],'roof').match(/\d+/g).map(Number),wall:shade([0,0,1],'wall').match(/\d+/g).map(Number)};
  });
  if(!report.depthRegression.orderIndependent||report.depthRegression.near.slice(0,3).join()!=report.depthRegression.roof.join()||report.depthRegression.far.slice(0,3).join()!=report.depthRegression.wall.join())throw Error('Rear wall occludes roof');
  const ids=await page.locator('#building option').evaluateAll(os=>os.map(o=>o.value));
  const methodIds=await page.locator('#variant-b option').evaluateAll(os=>os.map(o=>o.value));
  const selectors=['variant-a','variant-b','variant-c'];
  const defaults=await page.evaluate(()=>D.default_comparison_variants||D.methods.slice(0,3).map(m=>m.id));
  async function state(){await page.evaluate(()=>new Promise(requestAnimationFrame));return page.evaluate(()=>window.__drawState);}
  async function setVariants(values){for(let i=0;i<3;i++)await page.locator('#'+selectors[i]).selectOption(values[i]||values[0]);return state();}
  async function links(){const hrefs=await page.locator('a[href]').evaluateAll(as=>as.map(a=>a.getAttribute('href')).filter(h=>h&&!h.startsWith('#')&&!/^[a-z]+:/i.test(h)));for(const href of new Set(hrefs)){const exists=fs.existsSync(path.resolve(folder,href));report.links.push({href,exists});if(!exists)throw Error('Broken local link: '+href);}}
  if(smoke){
    report.recommendationCount=await page.evaluate(()=>Array.isArray(D.recommendations)?D.recommendations.length:Object.keys(D.recommendations||{}).length);
    if(!report.recommendationCount)throw Error('No final recommendations');
    for(const id of ids){await page.locator('#building').selectOption(id);const s=await state();const recommendation=await page.locator('#recommendation').textContent();if(!s.bounds.every(Number.isFinite)||!recommendation.trim())throw Error('Invalid final view '+id);report.objects.push({id,state:s,recommendation});}
    await links();
  }else{
    if(await page.locator('#wireframe').isChecked()||await page.locator('#component-masks').isChecked())throw Error('Diagnostics must default off');
    report.tJunction=await page.evaluate(()=>{const model={vertices:[[0,0,1],[2,0,1],[2,2,1],[0,2,1],[1,1,1]],faces:[[0,1,2],[0,4,3],[4,2,3]],face_semantics:['roof','roof','roof'],face_region_ids:[0,0,0],comparison_roof_regions:[{id:0,polygon:{type:'Polygon',coordinates:[[[0,0],[2,0],[2,2],[0,2],[0,0]]]},plane:[0,0,1]}]};const g=geometry(model);return{filteredFaces:g.regionFilteredFaces,segments:g.byFace.flat().length};});
    if(report.tJunction.filteredFaces!==3||report.tJunction.segments!==4)throw Error('T-junction exposed technical diagonal');
    report.maskProjection=await page.evaluate(()=>{const m={vertices:[[0,0,2],[2,0,4],[0,2,2]],faces:[[0,1,2]],face_semantics:['roof']};return{inside:modelRoofZ(m,.5,.5),outside:modelRoofZ(m,3,3)};});
    if(Math.abs(report.maskProjection.inside-2.5)>1e-8||report.maskProjection.outside!==null)throw Error('Mask height projection invented a surface');
    const configured=await page.evaluate(()=>D.comparison_sets||[]);
    const sets=configured.length?configured:[{id:'default',variants:defaults}];
    for(const id of ids){
      await page.locator('#building').selectOption(id);
      await page.locator('#all-variants').check();
      const s=await state();
      const expected=await page.evaluate(id=>{const bs=D.groups.find(g=>g.id===id).building_ids;return [...new Set(D.runs.filter(r=>bs.includes(r.id)).map(r=>r.variant))];},id);
      if(s.cards.length!==expected.length)throw Error('Missing method cards: '+id);
      if(!s.bounds.every(Number.isFinite)||!Number.isFinite(s.scale)||s.scale<=0)throw Error('Invalid camera bounds');
      const canvases=await page.locator('#models canvas').evaluateAll(cs=>cs.map(c=>{const px=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let pixels=0;for(let i=3;i<px.length;i+=4)if(px[i]>200)pixels++;return{faces:+c.dataset.drawnFaces,pixels,scale:+c.dataset.scale};}));
      if(canvases.some(c=>c.faces>0&&c.pixels<100)||new Set(canvases.map(c=>c.scale)).size!==1)throw Error('Blank or differently scaled geometry');
      report.objects.push({id,variants:expected,state:s,canvases});
      await page.locator('#all-variants').uncheck();
      for(const set of sets){const variants=set.variants.filter(v=>methodIds.includes(v));if(!variants.length)continue;await setVariants(variants);await page.locator('#models').screenshot({path:path.join(out,set.id.replace(/[^a-z0-9_-]/gi,'_')+'-'+id.replace(/[^a-z0-9_-]/gi,'_')+'.png')});}
      await setVariants(defaults);
    }
    // Test a real supplied mask if any, without claiming successful detection.
    const masked=await page.evaluate(()=>D.runs.find(r=>r.model?.faces?.length&&r.component_masks?.length)?{id:D.runs.find(r=>r.model?.faces?.length&&r.component_masks?.length).id,variant:D.runs.find(r=>r.model?.faces?.length&&r.component_masks?.length).variant}:null);
    report.realMaskAvailable=!!masked;
    if(masked){const group=await page.evaluate(id=>D.groups.find(g=>g.building_ids.includes(id)).id,masked.id);await page.locator('#building').selectOption(group);await setVariants([masked.variant]);const before=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());await page.locator('#component-masks').check();const s=await state();const after=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());report.maskState=s;report.maskToggleChangesImage=before!==after;if(!s.cards.some(c=>c.masks>0)||before===after)throw Error('Supplied mask is not visible');await page.locator('#models').screenshot({path:path.join(out,'component-mask-reference.png')});await page.locator('#component-masks').uncheck();}
    await page.locator('#building').selectOption(ids[0]);await setVariants(defaults);
    const cameraImages=[];
    for(const view of ['iso','top','front','side']){await page.locator(`[data-view="${view}"]`).click();report.cameraViews.push({view,state:await state()});cameraImages.push(await page.locator('#models canvas').first().evaluate(c=>c.toDataURL()));}
    if(new Set(cameraImages).size!==4)throw Error('Camera presets ineffective');
    await page.locator('[data-view="iso"]').click();const solid=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());await page.locator('#wireframe').check();await state();const wire=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());if(solid===wire||!await page.locator('#diagnostic-note').isVisible())throw Error('Triangulation toggle ineffective');await page.locator('#wireframe').uncheck();
    await page.locator('#edges').uncheck();if((await state()).cards.some(c=>c.edges))throw Error('Edges remain after disabling');await page.locator('#edges').check();const full=await state();await page.locator('#roof-only').check();const roofs=await state();if(!roofs.cards.some((c,i)=>c.faces<full.cards[i].faces))throw Error('Roof filter ineffective');await page.locator('#roof-only').uncheck();
    if(await page.locator('#points').isEnabled()){const before=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());await page.locator('#points').check();await state();const after=await page.locator('#models canvas').first().evaluate(c=>c.toDataURL());if(before===after)throw Error('Point toggle ineffective');await page.locator('#points').uncheck();}
    for(const method of methodIds){await page.locator('#variant-b').selectOption(method);await state();}
    report.methodSelectorValues=methodIds;await links();
    await page.setViewportSize({width:390,height:900});await page.evaluate(()=>new Promise(r=>setTimeout(r,120)));report.mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);await page.locator('header').screenshot({path:path.join(out,'mobile-header.png')});
    if(report.mobileOverflow)throw Error('Mobile overflow');
  }
  report.passed=!report.errors.length&&!report.networkRequests.length;
  if(!report.passed)throw Error('JavaScript or unexpected network errors');
  console.log(JSON.stringify({passed:true,mode:report.mode,counts:report.counts,objects:report.objects.length,resultsSha256:actual}));
}catch(error){report.passed=false;report.failure=String(error);throw error;}
finally{fs.writeFileSync(path.join(out,smoke?'gallery-final-smoke.json':'gallery-ui.json'),JSON.stringify(report,null,2));await browser.close();}
