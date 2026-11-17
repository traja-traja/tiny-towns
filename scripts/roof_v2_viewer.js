/* Interactive review only: no model inference or visual quality scoring. */
const data = JSON.parse(document.getElementById('roof-data').textContent);
const $ = id => document.getElementById(id);
const names = {flat:'Plochá',multi_flat:'Více plochých úrovní',flat_levels:'Více plochých úrovní',shed:'Pultová',skillion:'Pultová',gabled:'Sedlová',hipped:'Valbová',pyramidal:'Stanová',pyramid:'Stanová',compound:'Složená',butterfly:'Úžlabní',sawtooth:'Pilová',barrel:'Valená',fallback:'Odhad'};
Object.assign(names,{straight:'Přímý hřeben',bent:'Hřeben do L',u_shaped:'Hřeben do U',ring:'Uzavřený hřeben',parallel_gables:'Souběžné sedlové střechy',connected_wings:'Navazující střechy křídel'});
const flagNames={weak_plane_evidence:'Slabá podpora orientace střešních ploch v bodech',insufficient_data:'Nedostatek vstupních bodů',fallback_geometry_not_roof_classification:'Záložní objem; typ střechy nebyl určen',poor_template_fit:'Šablona má velké odchylky od bodů',ambiguous_type:'Dva typy dosáhly blízkého skóre',incomplete_point_coverage:'Body nepokrývají dostatečně celý půdorys',part_boundaries_need_review:'Hranice částí vyžadují kontrolu',optimizer_iteration_limit:'Dosažen limit iterací',higher_ranked_mesh_rejected:'Lépe hodnocený kandidát neprošel kontrolou geometrie',source_type_disagrees:'Zvolený typ se liší od typu uvedeného ve zdrojových datech'};
const buildings = Array.isArray(data.buildings) ? data.buildings : [];
Object.assign(flagNames,{flat_majority_whole_building_simplification:'Převaha vodorovných ploch: zjednodušený plochý základ střechy',flat_roof_protrusions_added:'Nad plochou střechou zachovány naměřené nástavby',simpler_near_equivalent_candidate:'Při podobné shodě vybrána jednodušší střecha'});
const issues = [];
window.addEventListener('error', e => issues.push(e.message));
window.addEventListener('unhandledrejection', e => issues.push(String(e.reason)));
const state = {index:0, theta:-0.8, phi:0.92, zoom:1, panX:0, panY:0, radius:20, part:'all', layers:{roof:true,walls:true,edges:true,ridge:true,eave:false,points:false,holdout:false}};
const canvas = $('view');
let renderer, camera, scene, group, grid, target = new THREE.Vector3(), center = new THREE.Vector3(), bounds;
let geometryStats = {}, activeParts = [], selectedBuilding;
let dirty = true;
function text(tag, value, cls) {const e=document.createElement(tag);e.textContent=String(value ?? '');if(cls)e.className=cls;return e;}
function label(value) {return Array.isArray(value) ? value.join(', ') : (typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? ''));}
function format(value, digits=2) {return Number.isFinite(value) ? value.toLocaleString('cs-CZ',{maximumFractionDigits:digits}) : '—';}
function pretty(value) {return JSON.stringify(value ?? {},null,2);}
function resultOf(part) {return part.result || {};}
function modelOf(part) {return resultOf(part).model || {};}
function finitePoint(p) {return Array.isArray(p) && p.length>=3 && p.slice(0,3).every(Number.isFinite);}
function sourceText(b) {return label(b.source || data.source || data.point_source || 'Zdroj není uveden');}
function flagsOf(part) {const d=resultOf(part).diagnostics || {}; const r=d.reasons || d.flags || d.warnings || resultOf(part).warnings || [];return Array.isArray(r) ? r : [r];}
function statusOf(part) {const r=resultOf(part),d=r.diagnostics || {};return part.error?'Chyba výpočtu':d.status || r.status || (d.review_required || flagsOf(part).length ? 'Ke kontrole' : 'Spočítáno');}
function typeOf(part) {const m=modelOf(part);return m.type || m.shape || 'unknown';}
function rebuildList(filter='') {
  const query=filter.trim().toLocaleLowerCase('cs');const select=$('building');select.replaceChildren();
  buildings.forEach((b,i)=>{const title=label(b.address || b.name || b.id || ('Objekt '+(i+1)));if(query && !(title+' '+label(b.name)+' '+b.id).toLocaleLowerCase('cs').includes(query))return;const o=text('option',title);o.value=String(i);select.append(o);});
  const found=[...select.options].some(o=>Number(o.value)===state.index);if(found)select.value=String(state.index);else if(select.options.length)select.value=select.options[0].value;
  $('found').textContent=select.options.length+' / '+buildings.length+' objektů';
}
function disposeGroup() {
  if(!group)return;const geometries=new Set(),materials=new Set();group.traverse(o=>{if(o.geometry)geometries.add(o.geometry);if(o.material)(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>materials.add(m));});geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());scene.remove(group);
}
function geometryFromFaces(vertices, faces, offset, kind) {
  const positions=[];let rejected=0;
  for(const f of faces || []){if(!Array.isArray(f)||f.length<3){rejected++;continue;}for(let j=1;j+1<f.length;j++){const ids=[f[0],f[j],f[j+1]];if(!ids.every(i=>Number.isInteger(i)&&i>=0&&i<vertices.length&&finitePoint(vertices[i]))){rejected++;continue;}for(const i of ids){const v=vertices[i];positions.push(v[0]+offset[0],v[2]+offset[2],-(v[1]+offset[1]));}}}
  geometryStats.invalid_faces+=rejected;geometryStats[kind+'_triangles']=(geometryStats[kind+'_triangles']||0)+positions.length/9;
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));g.computeVertexNormals();return g;
}
function extractLines(value) {
  if(!value)return [];
  if(value.type==='Feature')return extractLines(value.geometry);
  if(value.type==='LineString')return [value.coordinates];
  if(value.type==='MultiLineString')return value.coordinates;
  if(Array.isArray(value)){if(value.length===0)return [];if(finitePoint(value[0]))return [value];return value.flatMap(extractLines);}
  return extractLines(value.points || value.vertices || value.coordinates || value.line || value.segments);
}
function lineLayer(lines, offset, color, layer) {
  const positions=[];
  for(const line of extractLines(lines))for(let i=1;i<line.length;i++){const a=line[i-1],b=line[i];if(!finitePoint(a)||!finitePoint(b)){geometryStats.invalid_lines++;continue;}for(const v of [a,b])positions.push(v[0]+offset[0],v[2]+offset[2]+0.015,-(v[1]+offset[1]));}
  if(!positions.length)return;const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));const m=new THREE.LineBasicMaterial({color,depthTest:false,transparent:true,opacity:0.95});const o=new THREE.LineSegments(g,m);o.userData.layer=layer;o.visible=state.layers[layer];o.renderOrder=4;group.add(o);geometryStats[layer+'_segments']=(geometryStats[layer+'_segments']||0)+positions.length/6;
}
function pointLayer(raw, offset, color, layer) {
  const xyz=Array.isArray(raw) ? raw : (raw?.points || raw?.xyz || []);const positions=[];
  for(const v of xyz){if(!finitePoint(v)){geometryStats.invalid_points++;continue;}positions.push(v[0]+offset[0],v[2]+offset[2],-(v[1]+offset[1]));}
  if(!positions.length)return;const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));const m=new THREE.PointsMaterial({color,size:2.5,sizeAttenuation:false,transparent:true,opacity:0.70,depthTest:true});const o=new THREE.Points(g,m);o.userData.layer=layer;o.visible=state.layers[layer];group.add(o);geometryStats[layer+'_count']=(geometryStats[layer+'_count']||0)+positions.length/3;
}
function metricRows(part) {
  const r=resultOf(part), d=r.diagnostics || {}, ext=part.external_metrics || r.external_metrics || {}, train=d.train || {};
  if(data.report?.batch){
    const m=modelOf(part).metadata || {}, t=r.timing || {};
    const rows=[['Čas výpočtu střechy',Number.isFinite(t.total_seconds)?format(t.total_seconds,3)+' s':'—'],
      ['Algoritmus',r.algorithm || '—'],['Typ střechy',names[typeOf(part)] || typeOf(part)],
      [(m.main_roof_type || typeOf(part))==='pyramidal'?'Vrchol':'Tvar hřebene',(m.main_roof_type || typeOf(part))==='pyramidal'?'Jeden bod, bez hřebene':names[m.ridge_kind] || m.ridge_kind || '-'],['Stav',statusOf(part)]];
    for(const [key,label] of [['ridge_height_m',(m.main_roof_type || typeOf(part))==='pyramidal'?'Výška vrcholu':'Výška hřebene'],['eave_height_m','Výška hlavních okapů'],['courtyard_eave_height_m','Výška říms do dvora'],['roof_height_m','Převýšení střechy']])if(Number.isFinite(m[key]))rows.push([label,format(m[key])+' m']);
    for(const [key,label] of [['preprocessing_seconds','Příprava bodů'],['fitting_seconds','Hledání a výběr střechy'],['geometry_seconds','Tvorba geometrie'],['input_read_seconds','Načtení vstupu'],['cpu_seconds','CPU výpočtu']])if(Number.isFinite(t[key]))rows.push([label,format(t[key],3)+' s']);
    if(Number.isFinite(m.parallel_ridge_count))rows.push(['Počet souběžných hřebenů',format(m.parallel_ridge_count,0)]);
    if(Array.isArray(m.ridge_heights_m))rows.push(['Výšky hřebenů',m.ridge_heights_m.map(h=>format(h)+' m').join(' / ')]);
    if(m.main_roof_type)rows.push(['Hlavní střecha',names[m.main_roof_type] || m.main_roof_type]);
    if(Number.isFinite(m.annex_count))rows.push(['Oddělené přístavky',format(m.annex_count,0)]);
    if(d.flat_majority?.enabled){
      if(Number.isFinite(d.flat_majority.covered_area_fraction))rows.push(['Vodorovné plochy z půdorysu',format(100*d.flat_majority.covered_area_fraction,1)+' %']);
      if(Number.isFinite(d.flat_majority.largest_patch_area_fraction))rows.push(['Největší souvislá plochá část',format(100*d.flat_majority.largest_patch_area_fraction,1)+' %']);
      if(Number.isFinite(d.flat_majority.min_patch_area_fraction))rows.push(['Minima: část / největší / součet',[d.flat_majority.min_patch_area_fraction,d.flat_majority.min_largest_patch_fraction,d.flat_majority.min_coverage_fraction].map(v=>format(100*v,0)+' %').join(' / ')]);
      rows.push(['Převaha ploché střechy',d.flat_majority.accepted?(m.protrusion_count?'Ano — plochý základ a nástavby':'Ano — jedna rovina pro celý dům'):'Ne']);
      if(d.flat_majority.accepted)rows.push(['Volba výšky','Největší doložená vodorovná plocha']);
    }
    if(d.flat_protrusions?.enabled){
      rows.push(['Nástavby nad plochou střechou',format(m.protrusion_count || 0,0)]);
      if(Number.isFinite(m.max_protrusion_height_m))rows.push(['Nejvyšší nástavba nad střechou',format(m.max_protrusion_height_m)+' m']);
      if(Number.isFinite(m.building_top_height_m))rows.push(['Celková výška s nástavbami',format(m.building_top_height_m)+' m']);
    }
    if(Number.isFinite(t.flat_protrusions_seconds))rows.push(['Nástavby: detekce a geometrie',format(t.flat_protrusions_seconds*1000,2)+' ms']);
    if(m.connected_wings){
      rows.push(['Střešní křídla',format(m.connected_wings.wing_count,0)],['Společný sklon',format(m.connected_wings.pitch_degrees,1)+'°']);
      if(Array.isArray(m.connected_wings.wing_eaves_m))rows.push(['Okapy křídel',m.connected_wings.wing_eaves_m.map(v=>format(v)+' m').join(', ')]);
      if(m.connected_wings.unsupported_wings?.length)rows.push(['Křídla bez dostatečných bodů',format(m.connected_wings.unsupported_wings.length,0)]);
    }
    if(Number.isFinite(t.connected_wings_seconds))rows.push(['Křídla: kandidáti a geometrie',format(t.connected_wings_seconds*1000,2)+' ms']);
    if(Number.isFinite(t.flat_majority_seconds))rows.push(['Detekce ploché střechy',format(t.flat_majority_seconds*1000,2)+' ms']);
    for(const [key,label] of [['annex_2d_seconds','Přístavky: půdorys'],['annex_profiles_seconds','Přístavky: dva profily'],['annex_evaluation_seconds','Přístavky: ověření včetně profilů'],['annex_assembly_seconds','Přístavky: spojení geometrie']])if(Number.isFinite(t[key]))rows.push([label,format(t[key]*1000,2)+' ms']);
    rows.push(['Vstupních bodů',format(train.n,0)],['Výpočetních buněk',format(d.fit_cells,0)]);
    if(Number.isFinite(d.selection_score))rows.push(['Výběrové skóre',format(d.selection_score,4)]);
    if(Number.isFinite(d.runner_up_gap))rows.push(['Rozdíl druhého kandidáta',format(d.runner_up_gap,4)]);
    rows.push(['Podlaží ve zdroji',format(m.source_floor_count,0)],['Nový odhad podlaží',format(m.estimated_floor_count,0)]);
    return rows;
  }
  if(data.comparison_mode==='level-ridge'){
    const m=modelOf(part).metadata || {}, rows=[['Typ',names[typeOf(part)] || typeOf(part)]];
    if(Number.isFinite(m.ridge_height_m))rows.push(['Výška hřebene',format(m.ridge_height_m)+' m'],['Výška okapů',format(m.eave_height_m)+' m']);
    if(Number.isFinite(r.timing?.total_seconds))rows.push(['Výpočet modelu',format(r.timing.total_seconds,3)+' s']);
    return rows;
  }
  const rows=[['Typ',names[typeOf(part)] || typeOf(part)],['Stav',statusOf(part)],['Výpočetních bodů',format(train.n,0)],['Kontrolních bodů',format(ext.n ?? ext.count,0)],['RMSE na kontrolních bodech',Number.isFinite(ext.rmse_m)?format(ext.rmse_m,3)+' m':'—'],['Průměrná absolutní odchylka',Number.isFinite(ext.mae_m)?format(ext.mae_m,3)+' m':'—'],['90. percentil odchylky',Number.isFinite(ext.p90_abs_m ?? ext.p90_m)?format(ext.p90_abs_m ?? ext.p90_m,3)+' m':'—']];
  const fraction=ext.within_05m ?? ext.within_05_fraction ?? ext.within_0_5m_fraction;rows.push(['Kontrolní body do 0,5 m',Number.isFinite(fraction)?format(100*fraction,1)+' %':'—']);
  if(Number.isFinite(d.selection_score))rows.push(['Výběrové skóre',format(d.selection_score,4)]);
  if(Number.isFinite(d.runner_up_gap))rows.push(['Rozdíl proti druhému kandidátu',format(d.runner_up_gap,4)]);
  const t=r.timing || {};const secs=t.total_seconds ?? t.total_s ?? t.wall_seconds;if(Number.isFinite(secs))rows.push(['Výpočet modelu',format(secs,3)+' s']);
  return rows;
}
function populateDetails(b) {
  $('object-title').textContent=label(b.name || b.address || b.id);$('object-address').textContent=label(b.address || '');$('object-id').textContent=b.id || '';$('source').textContent=sourceText(b);
  const gps=Number.isFinite(b.lon)&&Number.isFinite(b.lat);$('osm-link').hidden=!gps;if(gps)$('osm-link').href='https://www.openstreetmap.org/?mlat='+b.lat+'&mlon='+b.lon+'#map=19/'+b.lat+'/'+b.lon;
  $('metrics').replaceChildren();$('candidate-tables').replaceChildren();
  activeParts.forEach(({part,index})=>{
    const block=document.createElement('section');block.className='part-info';block.append(text('h3',part.display_label || ('Část '+(index+1))));const dl=document.createElement('dl');metricRows(part).forEach(([k,v])=>{dl.append(text('dt',k),text('dd',v));});block.append(dl);
    if(part.error)block.append(text('p',part.error.message || label(part.error)));
    const flags=flagsOf(part);if(flags.length){block.append(text('p','Důvody ke kontrole','small'));const list=document.createElement('ul');flags.forEach(f=>list.append(text('li',flagNames[f] || label(f))));block.append(list);}
    $('metrics').append(block);
    const candidates=resultOf(part).candidates || [];
    if(candidates.length){
      const section=document.createElement('section');section.append(text('h3','Kandidáti · část '+(index+1)));
      const table=document.createElement('table'),head=document.createElement('thead'),hr=document.createElement('tr');
      ['Typ','Skóre','Stav a upozornění'].forEach(v=>hr.append(text('th',v)));head.append(hr);table.append(head);
      const body=document.createElement('tbody');
      candidates.forEach(c=>{
        const tr=document.createElement('tr'),status=document.createElement('td');
        const rejected=c.rejected || c.rejection_reasons || [],warnings=c.warnings || [];
        const rejectedList=Array.isArray(rejected)?rejected:[rejected],warningList=Array.isArray(warnings)?warnings:[warnings];
        const selected=c.type===typeOf(part) && c.score===resultOf(part).diagnostics?.selection_score;
        const statusLabel=rejectedList.length?'Vyřazeno: '+rejectedList.map(v=>flagNames[v] || label(v)).join(', '):(c.status || (selected?'Vybráno':'Ve výběru'));
        status.append(text('div',statusLabel,'candidate-status'));
        if(warningList.length)status.append(text('div','Upozornění: '+warningList.map(v=>flagNames[v] || label(v)).join(', '),'candidate-warning'));
        tr.append(text('td',names[c.type || c.shape] || c.type || c.shape || '—'),text('td',format(c.score ?? c.selection_score ?? c.metrics?.score,4)),status);body.append(tr);
      });table.append(body);section.append(table);$('candidate-tables').append(section);
    }
  });
  const raw={id:b.id,source:b.source,source_attributes:b.source_attributes,footprint_sources:b.footprint_sources,input_data:b.input_data,building_timing:b.timing,run_configuration:data.configuration,parts:activeParts.map(({part,index})=>({index,part_index:part.part_index,version:part.display_variant,origin_xy:part.origin_xy,ground_z:part.ground_z,ground_source:part.ground_source,footprint:part.footprint,cache:part.cache,measurement:part.measurement,error:part.error,external_metrics:part.external_metrics,diagnostics:resultOf(part).diagnostics,timing:resultOf(part).timing,candidates:resultOf(part).candidates,model:{type:typeOf(part),mesh_diagnostics:modelOf(part).mesh?.diagnostics,metadata:modelOf(part).metadata}}))};$('raw').textContent=pretty(raw);
  $('download').onclick=()=>{const payload=JSON.stringify(b,null,2);const url=URL.createObjectURL(new Blob([payload],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='roof-'+String(b.id || state.index).replace(/[^A-Za-z0-9_-]/g,'_')+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),2000);};
}
function updateCamera() {
  if(!camera)return;const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);const ratio=w/h,span=state.radius/state.zoom;camera.left=-span*ratio/2;camera.right=span*ratio/2;camera.top=span/2;camera.bottom=-span/2;camera.updateProjectionMatrix();
  const distance=Math.max(state.radius*3,50);target.copy(center);const right=new THREE.Vector3(Math.cos(state.theta),0,-Math.sin(state.theta));target.addScaledVector(right,state.panX);target.y+=state.panY;
  camera.position.set(target.x+distance*Math.sin(state.phi)*Math.sin(state.theta),target.y+distance*Math.cos(state.phi),target.z+distance*Math.sin(state.phi)*Math.cos(state.theta));camera.lookAt(target);dirty=true;
}
function resetView(mode='iso') {state.theta=-0.8;state.phi=mode==='top'?0.001:mode==='street'?1.36:0.92;state.zoom=1;state.panX=0;state.panY=0;updateCamera();}
function applyLayers(){if(group)group.traverse(o=>{if(o.userData.layer)o.visible=Boolean(state.layers[o.userData.layer]);});dirty=true;}
function loadBuilding(index, keepPart=false) {
  if(!Number.isInteger(index)||index<0||index>=buildings.length)return;state.index=index;const b=buildings[index];selectedBuilding=b;const parts=Array.isArray(b.parts)?b.parts:[];
  if(!keepPart){state.part='all';$('part').replaceChildren(text('option',data.comparison_mode?'Obě verze vedle sebe':'Všechny části'));$('part').options[0].value='all';parts.forEach((p,i)=>{const o=text('option',(p.display_label || ('Část '+(i+1)))+' · '+(names[typeOf(p)] || typeOf(p)));o.value=String(i);$('part').append(o);});$('part').value='all';}
  activeParts=parts.map((part,index)=>({part,index})).filter(p=>state.part==='all'||String(p.index)===state.part);disposeGroup();group=new THREE.Group();scene.add(group);geometryStats={invalid_faces:0,invalid_lines:0,invalid_points:0,roof_triangles:0,wall_triangles:0,rendered_parts:0};
  const reference=parts.find(p=>Array.isArray(p.origin_xy)&&p.origin_xy.slice(0,2).every(Number.isFinite));const refXY=reference?.origin_xy || [0,0],refZ=Number.isFinite(reference?.ground_z)?reference.ground_z:0;
  for(const {part} of activeParts){const model=modelOf(part),mesh=model.mesh || {};const vertices=mesh.vertices || model.vertices || [];const origin=part.origin_xy || refXY;const display=state.part==='all'?(part.display_offset_m || [0,0,0]):[0,0,0];const offset=[origin[0]-refXY[0]+display[0],origin[1]-refXY[1]+display[1],(Number.isFinite(part.ground_z)?part.ground_z:refZ)-refZ+display[2]];if(!offset.every(Number.isFinite)){geometryStats.invalid_parts=(geometryStats.invalid_parts||0)+1;continue;}
    const roof=geometryFromFaces(vertices,mesh.roof_faces || model.roof_faces,offset,'roof');const walls=geometryFromFaces(vertices,mesh.wall_faces || model.wall_faces,offset,'wall');
    for(const [g,col,layer] of [[roof,0x9d7464,'roof'],[walls,0xd5d0c4,'walls']]){if(!g.getAttribute('position').count){g.dispose();continue;}const object=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:col,roughness:1,metalness:0,side:THREE.DoubleSide,flatShading:true}));object.userData.layer=layer;object.visible=state.layers[layer];group.add(object);const edges=new THREE.LineSegments(new THREE.EdgesGeometry(g,5),new THREE.LineBasicMaterial({color:0x47504d,transparent:true,opacity:.56}));edges.userData.layer='edges';edges.visible=state.layers.edges;group.add(edges);}
    lineLayer(model.ridge_lines || model.ridges,offset,0x315a9c,'ridge');lineLayer(model.eave_lines || model.eaves,offset,0x218a79,'eave');pointLayer(part.point_preview || part.points_preview,offset,0x414853,'points');pointLayer(part.holdout_preview,offset,0xb66925,'holdout');geometryStats.rendered_parts++;
  }
  bounds=new THREE.Box3().setFromObject(group);if(bounds.isEmpty()){center.set(0,0,3);state.radius=25;$('empty').hidden=false;}else{bounds.getCenter(center);const size=bounds.getSize(new THREE.Vector3());state.radius=Math.max(size.x,size.y,size.z,8)*1.65;$('empty').hidden=false;$('empty').textContent=geometryStats.roof_triangles?'':'Model nemá dostupné střešní plochy';$('empty').hidden=geometryStats.roof_triangles>0;}
  if(grid){scene.remove(grid);grid.geometry.dispose();grid.material.dispose();}const gridSpan=Math.max(20,Math.ceil(state.radius/10)*10);grid=new THREE.GridHelper(gridSpan,Math.max(4,Math.round(gridSpan/5)),0xc1cbc7,0xe0e5e2);grid.position.set(center.x,bounds.isEmpty()?0:Math.min(0,bounds.min.y),center.z);scene.add(grid);
  populateDetails(b);$('building').value=String(index);$('previous').disabled=index===0;$('next').disabled=index===buildings.length-1;$('geometry').textContent=geometryStats.roof_triangles+' střešních trojúhelníků · '+geometryStats.wall_triangles+' stěnových trojúhelníků';$('point-legend').textContent=(geometryStats.points_count||0)+' zobrazených výpočetních bodů · '+(geometryStats.holdout_count||0)+' kontrolních';
  const tileUrl='tiles/report.html#'+encodeURIComponent(b.id || '');$('tile-link').href=tileUrl;
  if(b.id)try{history.replaceState(null,'','#'+encodeURIComponent(b.id));}catch{}resetView();dirty=true;
}
function initialize() {
  renderer=new THREE.WebGLRenderer({canvas,antialias:true,powerPreference:'default'});renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));renderer.setClearColor(0xf2f4f1);renderer.outputColorSpace=THREE.SRGBColorSpace;scene=new THREE.Scene();camera=new THREE.OrthographicCamera(-20,20,20,-20,.01,100000);scene.add(new THREE.HemisphereLight(0xffffff,0xa4a99e,2.1));const sunlight=new THREE.DirectionalLight(0xffffff,2.0);sunlight.position.set(-40,80,50);scene.add(sunlight);
  rebuildList();$('search').addEventListener('input',()=>rebuildList($('search').value));$('building').addEventListener('change',e=>loadBuilding(Number(e.target.value)));$('part').addEventListener('change',e=>{state.part=e.target.value;loadBuilding(state.index,true);});$('previous').onclick=()=>loadBuilding(Math.max(0,state.index-1));$('next').onclick=()=>loadBuilding(Math.min(buildings.length-1,state.index+1));$('reset').onclick=()=>resetView();$('top-view').onclick=()=>resetView('top');$('street-view').onclick=()=>resetView('street');$('zoom-in').onclick=()=>{state.zoom=Math.min(20,state.zoom*1.25);updateCamera();};$('zoom-out').onclick=()=>{state.zoom=Math.max(.12,state.zoom/1.25);updateCamera();};
  document.querySelectorAll('[data-layer]').forEach(input=>{input.checked=state.layers[input.dataset.layer];input.addEventListener('change',()=>{state.layers[input.dataset.layer]=input.checked;applyLayers();});});
  let drag=null;canvas.addEventListener('contextmenu',e=>e.preventDefault());canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,button:e.button,shift:e.shiftKey};canvas.setPointerCapture(e.pointerId);canvas.focus();});canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(drag.button===2||drag.shift){const scale=state.radius/state.zoom/Math.max(1,canvas.clientHeight);state.panX-=dx*scale;state.panY+=dy*scale;}else{state.theta-=dx*.008;state.phi=Math.max(.001,Math.min(Math.PI-.05,state.phi+dy*.007));}updateCamera();});for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>drag=null);canvas.addEventListener('wheel',e=>{e.preventDefault();state.zoom=Math.max(.12,Math.min(20,state.zoom*Math.exp(-e.deltaY*.001)));updateCamera();},{passive:false});canvas.addEventListener('keydown',e=>{if(e.key==='ArrowLeft')state.theta-=.1;else if(e.key==='ArrowRight')state.theta+=.1;else if(e.key==='ArrowUp')state.phi=Math.max(.001,state.phi-.1);else if(e.key==='ArrowDown')state.phi=Math.min(Math.PI-.05,state.phi+.1);else if(e.key==='+'||e.key==='=')state.zoom=Math.min(20,state.zoom*1.2);else if(e.key==='-')state.zoom=Math.max(.12,state.zoom/1.2);else if(e.key==='0'){resetView();return;}else return;e.preventDefault();updateCamera();});new ResizeObserver(updateCamera).observe(canvas.parentElement);
  const requested=decodeURIComponent(location.hash.slice(1)),targetIndex=buildings.findIndex(b=>b.id===requested);if(buildings.length)loadBuilding(targetIndex>=0?targetIndex:0);else{$('empty').hidden=false;$('empty').textContent='Výstup neobsahuje žádné budovy.';}
  function frame(){requestAnimationFrame(frame);if(dirty){renderer.render(scene,camera);dirty=false;}}frame();
  window.__ROOF_V2_QA={ready:true,count:buildings.length,errors:issues,select:index=>loadBuilding(index),setLayer:(name,on)=>{state.layers[name]=Boolean(on);const input=document.querySelector('[data-layer="'+name+'"]');if(input)input.checked=Boolean(on);applyLayers();},snapshot:()=>({selected_id:selectedBuilding?.id,index:state.index,part:state.part,geometry:{...geometryStats},layers:{...state.layers},finite_camera:[...camera.position.toArray(),...target.toArray()].every(Number.isFinite),renderer_calls:renderer.info.render.calls,renderer_triangles:renderer.info.render.triangles,webgl:Boolean(renderer.getContext()),errors:[...issues]})};$('loading').hidden=true;
}
try{initialize();}catch(error){issues.push(error.stack||error.message);$('loading').textContent='3D zobrazení se nepodařilo spustit: '+error.message;window.__ROOF_V2_QA={ready:false,errors:issues};}
